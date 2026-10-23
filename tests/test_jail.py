"""Escape probes: each test tries something an untrusted agent might do."""

import fcntl
import os
import pty
import re
import select
import struct
import subprocess
import termios
import time
import uuid

import pytest
from conftest import JAIL, needs_node, needs_pasta, needs_systemd

CONNECT = """
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
try:
    socket.create_connection((host, port), timeout=3).close()
    print("OPEN")
except ConnectionRefusedError:
    print("REFUSED")
except OSError as e:
    print("ERROR", e)
"""

CONNECT_ABSTRACT = """
import socket, sys
s = socket.socket(socket.AF_UNIX)
try:
    s.connect("\\0" + sys.argv[1])
    print("OPEN")
except OSError:
    print("BLOCKED")
"""

FORK = """
import os, sys, time
started = 0
for _ in range(int(sys.argv[1])):
    try:
        if os.fork() == 0:
            time.sleep(5)
            os._exit(0)
    except OSError:
        break
    started += 1
print(started)
"""


def py(code: str, *args: str) -> str:
    quoted = " ".join(f"'{a}'" for a in args)
    return f"python3 -I -c '{code.replace(chr(39), chr(34))}' {quoted}"


# --- filesystem -------------------------------------------------------------

def test_rest_of_home_is_invisible(jail):
    r = jail.sh("cat ~/.ssh/id_canary; ls -A ~")
    assert "CANARY" not in r.stdout
    assert "No such file" in r.stderr
    assert r.stdout.split() == ["project"]


def test_can_write_the_working_directory(jail):
    r = jail.sh("echo hello > out.txt")
    assert r.returncode == 0, r.stderr
    assert (jail.work / "out.txt").read_text() == "hello\n"


def test_writes_outside_the_working_directory_do_not_persist(jail):
    marker = f"agent-jail-escape-{uuid.uuid4().hex}"
    r = jail.sh(f"touch ~/{marker} /tmp/{marker} && echo wrote")
    assert "wrote" in r.stdout
    assert not (jail.home / marker).exists()
    assert not os.path.exists(f"/tmp/{marker}")


def test_parent_directory_writes_do_not_persist(jail):
    # $HOME inside the jail is a throwaway tmpfs: writes succeed, then vanish.
    jail.sh("touch ../sibling")
    assert not (jail.home / "sibling").exists()


def test_environment_is_cleared(jail):
    r = jail.sh("env")
    assert "sk-canary-should-not-leak" not in r.stdout
    assert "AGENT_JAIL=shell" in r.stdout


def test_session_bus_and_runtime_dir_are_hidden(jail):
    # D-Bus, Wayland and PipeWire sockets live under /run/user/$UID.
    r = jail.sh("ls /run 2>&1; echo done")
    assert "No such file" in r.stdout


def test_host_processes_are_invisible(jail):
    r = jail.sh("ls /proc | grep -c '^[0-9]'")
    assert int(r.stdout.strip()) < 10


def test_cannot_create_user_namespaces(jail):
    r = jail.sh("unshare --user true && echo nested-userns")
    assert "nested-userns" not in r.stdout


# --- secret files in the project -------------------------------------------

def plant_secrets(work):
    (work / "certs").mkdir()
    (work / "deploy").mkdir()
    files = {
        ".env": "API_KEY=sk-canary-dotenv\n",
        ".env.production": "DB_PASSWORD=canary-prod\n",
        "certs/server.pem": "-----BEGIN PRIVATE KEY----- canary-pem\n",
        "deploy/id_ed25519": "OPENSSH PRIVATE KEY canary-ssh\n",
        ".env.example": "API_KEY=\n",
        "notes.txt": "visible\n",
    }
    for name, text in files.items():
        (work / name).write_text(text)
    return files


def test_secret_files_are_hidden(jail):
    files = plant_secrets(jail.work)
    names = " ".join(files)
    r = jail.sh(f"cat {names}; echo x > .env; rm .env; mv certs/server.pem stolen")
    assert "canary" not in r.stdout
    assert "API_KEY=\nvisible\n" in r.stdout  # templates and other files still show
    assert r.stderr.count("Permission denied") == 5
    assert "Device or resource busy" in r.stderr
    for name, text in files.items():
        assert (jail.work / name).read_text() == text
    # The hidden files are named before the agent starts.
    assert "hiding files that look like secrets" in r.stderr and ".env" in r.stderr


def test_symlink_to_a_secret_hides_the_secret(jail):
    (jail.work / "config").mkdir()
    (jail.work / "config" / "settings").write_text("canary-linked\n")
    (jail.work / ".env").symlink_to("config/settings")
    r = jail.sh("cat config/settings .env")
    assert "canary" not in r.stdout
    assert r.stderr.count("Permission denied") == 2


def test_hide_show_and_no_hide(jail):
    plant_secrets(jail.work)
    (jail.work / "token.secret").write_text("canary-custom\n")
    r = jail.sh("cat .env token.secret .env.example", "--hide", "*.secret", "--hide", "*.example",
                "--show", ".env")
    # --hide applies even to templates; --show beats both.
    assert r.stdout == "API_KEY=sk-canary-dotenv\n"
    assert r.stderr.count("Permission denied") == 2

    r = jail.sh("cat .env certs/server.pem", "--no-hide")
    assert "sk-canary-dotenv" in r.stdout and "canary-pem" in r.stdout
    assert "hiding" not in r.stderr

    assert jail.sh("true", "--hide", "certs/server.pem").returncode != 0


def test_secrets_in_dependency_trees_are_left_alone(jail):
    (jail.work / "node_modules" / "pkg").mkdir(parents=True)
    (jail.work / "node_modules" / "pkg" / "test.pem").write_text("fixture\n")
    r = jail.sh("cat node_modules/pkg/test.pem")
    assert r.stdout == "fixture\n"


# --- resource limits --------------------------------------------------------

@needs_systemd
def test_task_limit_stops_a_fork_bomb(jail):
    jail.with_user_session()
    r = jail.sh(py(FORK, "100"), "--tasks", "30")
    assert int(r.stdout.strip()) < 30, r.stderr


@needs_systemd
def test_memory_limit_stops_a_runaway(jail):
    jail.with_user_session()
    grab = "python3 -I -c 'b = bytes(300_000_000) + bytes(1); print(\"survived\")'"
    r = jail.sh(grab, "--memory", "64M")
    assert "survived" not in r.stdout
    # SIGKILL from the OOM killer, or SIGTERM from systemd stopping the scope
    # after it (OOMPolicy=stop): either way the jail is gone.
    assert r.returncode in (137, 143)
    assert "survived" in jail.sh(grab, "--memory", "2G").stdout


@needs_systemd
def test_limits_are_on_by_default(jail):
    jail.with_user_session()
    r = jail.run("--dry-run", "shell", net="none")
    assert r.stdout.startswith("systemd-run --user --scope")
    assert "MemoryMax=50%" in r.stdout and "TasksMax=4096" in r.stdout

    r = jail.run("--dry-run", "--memory", "off", "--tasks", "off", "shell", net="none")
    assert "systemd-run" not in r.stdout


def test_without_systemd_the_jail_runs_without_limits(jail):
    # The test XDG_RUNTIME_DIR has no systemd user manager in it.
    r = jail.sh("echo ran")
    assert r.stdout == "ran\n" and "limits" not in r.stderr
    # Asking for a limit that can't be enforced says so, but still runs.
    r = jail.sh("echo ran", "--memory", "1G")
    assert r.stdout == "ran\n"
    assert "without --memory and --tasks limits" in r.stderr


# --- git: things that run on the host later --------------------------------

def test_git_hooks_and_config_are_read_only(jail):
    r = jail.sh("echo 'touch /tmp/pwned' > .git/hooks/post-checkout; "
                "printf '[core]\\n\\tfsmonitor = touch /tmp/pwned\\n' >> .git/config")
    assert r.stderr.count("Read-only file system") == 2
    assert not (jail.work / ".git/hooks/post-checkout").exists()
    assert "fsmonitor" not in (jail.work / ".git/config").read_text()


@pytest.mark.parametrize("name", ["venv", "target"])
def test_git_is_protected_in_a_directory_named_like_a_dependency_tree(jail, name):
    # Dependency trees are skipped when looking for .git; the project itself isn't.
    work = jail.home / name
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    r = jail.run("shell", "-c", "echo x > .git/hooks/pre-commit", cwd=work)
    assert "Read-only file system" in r.stderr
    assert not (work / ".git/hooks/pre-commit").exists()


def test_commits_still_work_in_protect_mode(jail):
    r = jail.sh("git -c user.name=t -c user.email=t@example.com "
                "commit -q --allow-empty -m from-jail && echo ok")
    assert "ok" in r.stdout, r.stderr


def test_git_ro_mode_blocks_commits(jail):
    r = jail.sh("git -c user.name=t -c user.email=t@example.com "
                "commit -q --allow-empty -m x && echo ok", "--git", "ro")
    assert "ok" not in r.stdout


def test_worktree_pointer_file_cannot_be_repointed(jail):
    (jail.work / ".git").rename(jail.home / "real.git")
    (jail.work / ".git").write_text(f"gitdir: {jail.home / 'real.git'}\n")
    r = jail.sh("echo 'gitdir: evil' > .git")
    assert "Read-only file system" in r.stderr
    assert "evil" not in (jail.work / ".git").read_text()


def test_new_git_metadata_is_reported(jail):
    r = jail.sh("git init -q vendor/lib")
    assert "created or replaced git metadata" in r.stderr
    assert "vendor/lib/.git" in r.stderr


def test_repository_cannot_be_moved_aside_and_replaced(jail):
    # A fresh .git in place of the protected one would have writable hooks.
    subprocess.run(["git", "init", "-q", str(jail.work / "vendor" / "lib")], check=True)
    r = jail.sh("mv .git .git-old; mv vendor z; git init -q && echo replaced")
    assert "cannot move '.git' to '.git-old': Device or resource busy" in r.stderr
    assert "cannot move 'vendor' to 'z': Device or resource busy" in r.stderr
    assert "replaced" not in r.stdout
    assert not (jail.work / ".git-old").exists()

    # A nested .git can only be copied away, not moved: the hooks stay put.
    r = jail.sh("mv vendor/lib/.git copy")
    assert (jail.work / "vendor/lib/.git/hooks").is_dir()
    assert "Read-only file system" in r.stderr


def test_commondir_redirect_is_reported_and_existing_ones_are_read_only(jail):
    # .git/commondir makes git read config and hooks from another directory.
    r = jail.sh("git init -q --bare .evil && echo \"$PWD/.evil\" > .git/commondir")
    assert r.returncode == 0, r.stderr
    assert "created or replaced git metadata" in r.stderr
    assert ".git/commondir" in r.stderr

    # Once there (or in a linked worktree's git dir), it can't be re-pointed.
    r = jail.sh("echo /tmp > .git/commondir")
    assert "Read-only file system" in r.stderr


def test_replaced_repository_is_reported(jail):
    # With --git off nothing is pinned, but the swap is still noticed afterwards.
    r = jail.sh("mv .git .git-old && git init -q && echo replaced", "--git", "off")
    assert "replaced" in r.stdout
    assert "created or replaced git metadata" in r.stderr
    assert f"{jail.work}/.git\n" in r.stderr


def test_secret_next_to_a_nested_repository_stays_hidden(jail):
    # The directories around a nested .git are pinned; that must not unhide.
    subprocess.run(["git", "init", "-q", str(jail.work / "vendor" / "lib")], check=True)
    (jail.work / "vendor" / ".env").write_text("canary-vendor\n")
    r = jail.sh("cat vendor/.env")
    assert "canary" not in r.stdout
    assert "Permission denied" in r.stderr


def test_symlinked_hooks_are_refused(jail, tmp_path):
    hooks = jail.work / ".git" / "hooks"
    subprocess.run(["rm", "-rf", str(hooks)], check=True)
    hooks.symlink_to(tmp_path)
    r = jail.sh("true")
    assert r.returncode != 0
    assert "symlink" in r.stderr


# --- agent state ------------------------------------------------------------

def test_agent_state_is_private_to_the_jail(jail):
    jail.fake_npm_tool("opencode-ai", "opencode")
    real_cfg = jail.home / ".config" / "opencode"
    real_cfg.mkdir(parents=True)
    (real_cfg / "opencode.json").write_text('{"model": "x"}\n')

    # The attack: plant a plugin where the *unjailed* agent will load it.
    r = jail.run("--shell", "opencode", "-c",
                 "echo 'module.exports = {}' > ~/.config/opencode/plugin.js && echo planted; "
                 "cat ~/.config/opencode/opencode.json; "
                 "echo '{}' > ~/.config/opencode/opencode.json")
    assert "planted" in r.stdout
    assert '"model": "x"' in r.stdout          # real config is imported...
    assert "Read-only file system" in r.stderr  # ...but cannot be changed
    assert not (real_cfg / "plugin.js").exists()
    jailed = jail.home / ".local/share/agent-jail/opencode/.config/opencode/plugin.js"
    assert jailed.exists()


def test_planted_symlink_at_an_import_is_not_followed(jail, tmp_path):
    jail.fake_npm_tool("opencode-ai", "opencode")
    real_cfg = jail.home / ".config" / "opencode"
    real_cfg.mkdir(parents=True)
    (real_cfg / "opencode.json").write_text("{}\n")
    victim = tmp_path / "victim"
    victim.write_text("untouched\n")
    planted = jail.home / ".local/share/agent-jail/opencode/.config/opencode/opencode.json"
    planted.parent.mkdir(parents=True)
    planted.symlink_to(victim)

    jail.run("--shell", "opencode", "-c", "true")
    assert victim.read_text() == "untouched\n"
    assert not planted.is_symlink()


def test_profile_package_is_read_only(jail):
    pkg = jail.fake_npm_tool("opencode-ai", "opencode")
    r = jail.run("--shell", "opencode", "-c", f"echo x > {pkg}/bin/opencode")
    assert "Read-only file system" in r.stderr


def test_changed_agent_settings_are_reported(jail):
    (jail.work / ".vscode").mkdir()
    (jail.work / ".vscode" / "settings.json").write_text("{}\n")
    r = jail.sh("true")
    assert "changed files" not in r.stderr

    # Project hooks and MCP servers run when you next open the project unjailed.
    r = jail.sh("mkdir .claude && echo '{\"hooks\": {}}' > .claude/settings.json; "
                "echo '{}' > .mcp.json")
    assert "changed files" in r.stderr
    assert ".claude/settings.json" in r.stderr and ".mcp.json" in r.stderr
    assert ".vscode/settings.json" not in r.stderr


# --- installing agents ------------------------------------------------------

def test_list_shows_every_agent(jail):
    r = jail.run("--list", net="")
    assert r.returncode == 0
    for name in ["Claude Code", "Codex", "Gemini CLI", "Qwen Code", "OpenCode", "Continue",
                 "Crush", "Copilot CLI"]:
        assert name in r.stdout
    assert "installs @openai/codex" in r.stdout


@needs_node
@needs_pasta
def test_install_scripts_run_inside_the_jail(jail):
    jail.fake_npm()
    r = jail.run("--install", "codex", net="isolated")
    assert r.returncode == 0, r.stderr
    assert not (jail.home / "escaped").exists()
    assert not (jail.tools("codex").parent / "planted").exists()

    r = jail.run("codex")
    assert r.returncode == 0, r.stderr
    assert "fake-agent @openai/codex" in r.stdout
    assert "CANARY" not in r.stdout and "sk-canary" not in r.stdout


@needs_node
@needs_pasta
def test_failed_install_keeps_the_previous_one(jail):
    jail.fake_npm()
    assert jail.run("--install", "codex", net="isolated").returncode == 0
    (jail.bin / "npm").write_text("process.exit(1)\n")
    r = jail.run("--install", "codex", net="isolated")
    assert r.returncode != 0
    assert "fake-agent" in jail.run("codex").stdout


@needs_node
@needs_pasta
def test_installed_agent_is_read_only(jail):
    jail.fake_npm()
    jail.run("--install", "codex", net="isolated")
    cli = jail.tools("codex") / "lib/node_modules/@openai/codex/bin/cli.js"
    r = jail.run("--shell", "codex", "-c", f"echo x > {cli}")
    assert "Read-only file system" in r.stderr


def test_installed_command_pointing_outside_is_not_followed(jail):
    # An install script could re-point the command at a host secret; following
    # it would bind the secret into the jail.
    bin_dir = jail.tools("codex") / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "codex").symlink_to(jail.home / ".ssh" / "id_canary")
    r = jail.run("--shell", "codex", "-c", f"cat {jail.home}/.ssh/id_canary")
    assert "CANARY" not in r.stdout
    assert "points outside its install" in r.stderr


def test_install_needs_the_network(jail):
    r = jail.run("--install", "codex", net="none")
    assert r.returncode != 0
    assert "network" in r.stderr


@needs_node
def test_codex_starts_with_its_own_sandbox_off(jail):
    # Codex's bundled bubblewrap cannot create namespaces inside the jail.
    jail.fake_npm_tool("@openai/codex", "codex")
    r = jail.run("--shell", "codex", "-c", "cat ~/.codex/config.toml")
    assert 'sandbox_mode = "danger-full-access"' in r.stdout


def test_crush_runs_its_binary_with_metrics_off(jail):
    # The npm command is a node wrapper; the profile runs the Go binary it fetched.
    pkg = jail.fake_npm_tool("@charmland/crush", "crush")
    (pkg / "bin" / "crush").rename(pkg / "run-crush.js")
    (jail.bin / "crush").unlink()
    (jail.bin / "crush").symlink_to(pkg / "run-crush.js")
    (pkg / "bin" / "crush").write_text("#!/bin/sh\necho fake-crush $CRUSH_DISABLE_METRICS\n")
    (pkg / "bin" / "crush").chmod(0o755)
    r = jail.run("crush")
    assert r.stdout == "fake-crush 1\n", r.stderr


@needs_node
def test_copilot_starts_with_updates_and_its_sandbox_off(jail):
    jail.fake_npm_tool("@github/copilot", "copilot")
    r = jail.run("--shell", "copilot", "-c",
                 "echo $COPILOT_AUTO_UPDATE; cat ~/.copilot/settings.json; ls -d ~/.cache/copilot")
    assert r.stdout.startswith("false\n"), r.stderr
    assert '"autoUpdate": false' in r.stdout and '"enabled": false' in r.stdout
    assert "/.cache/copilot" in r.stdout


def test_crush_and_copilot_project_files_are_watched(jail):
    r = jail.sh("echo 'echo hi' > .crushrc; mkdir -p .github/hooks .crush/logs; "
                "echo '{}' > .github/hooks/x.json; echo log > .crush/logs/crush.log")
    assert ".crushrc" in r.stderr and ".github/hooks/x.json" in r.stderr
    assert "crush.log" not in r.stderr  # logs change every run


def test_uninstalled_agent_is_refused_without_a_terminal(jail):
    r = jail.run("codex")
    assert r.returncode != 0
    assert "--install codex" in r.stderr


def pty_run(jail, keys, *args, term="xterm-256color"):
    """Run agent-jail on a 100-column terminal, typing each of keys when the
    output goes quiet. Returns the exit status and everything it printed."""
    pid, fd = pty.fork()
    if pid == 0:
        fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
        os.chdir(jail.work)
        os.execve(str(JAIL), [str(JAIL), *args], {**jail.env, "TERM": term})
    out, keys, deadline = b"", list(keys), time.time() + 30
    while time.time() < deadline:
        if select.select([fd], [], [], 0.5)[0]:
            try:
                data = os.read(fd, 4096)
            except OSError:  # EIO: agent-jail has exited
                break
            if not data:
                break
            out += data
        elif keys:
            os.write(fd, keys.pop(0).encode())
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status), out.decode(errors="replace")


def plain(out: str) -> str:
    """out without colours and cursor movement."""
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", out)


def test_picker_lists_agents_and_runs_the_choice(jail):
    status, out = pty_run(jail, ["s", "echo in-jail-$AGENT_JAIL; exit\r"], "--net", "none")
    assert "Codex" in out and "Claude Code" in out
    assert "in-jail-shell" in out
    assert status == 0


def test_picker_arrow_keys_lead_to_an_install_offer(jail):
    # Down from Claude Code to Codex, Enter, then decline the install.
    status, out = pty_run(jail, ["\x1b[B", "\r", "n\r"], "--net", "none")
    assert "Codex is not installed" in plain(out)
    assert "@openai/codex" in out
    assert status != 0
    assert not jail.tools("codex").exists()


def test_picker_restores_the_terminal_when_left(jail):
    status, out = pty_run(jail, ["q"], "--net", "none")
    assert status == 0
    # Cursor shown and line wrap back on.
    assert out.endswith("\x1b[?25h\x1b[?7h")


def test_picker_takes_numbers_on_a_dumb_terminal(jail):
    status, out = pty_run(jail, ["s\r", "echo in-jail-$AGENT_JAIL; exit\r"], "--net", "none",
                          term="dumb")
    assert "\x1b[" not in out.split("in-jail")[0]  # no cursor movement or colour
    assert "in-jail-shell" in out
    assert status == 0


def test_without_a_terminal_no_profile_prints_usage(jail):
    r = jail.run(net="none")
    assert r.returncode == 2
    assert "Usage:" in r.stderr


# --- config files -----------------------------------------------------------

def user_config(jail, text: str) -> None:
    cfg = jail.home / ".config" / "agent-jail" / "config"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(text)


@needs_pasta
def test_user_config_sets_defaults_and_the_command_line_wins(jail):
    (jail.work / "token.secret").write_text("canary-custom\n")
    user_config(jail, "# my settings\nnet = none\n\n  hide = *.secret  \n")
    r = jail.run("--dry-run", "shell", net="")
    assert "pasta" not in r.stdout
    assert "token.secret" in r.stdout  # hidden
    r = jail.run("--dry-run", "--net", "isolated", "shell", net="")
    assert "pasta" in r.stdout


@pytest.mark.parametrize("text, error", [
    ("force\n", "unknown setting"),
    ("install = codex\n", "unknown setting"),
    ("net\n", "no value"),
    ("net =\n", "needs a value"),
    ("memory = lots\n", "--memory must be"),
])
def test_user_config_errors_stop_the_run(jail, text, error):
    user_config(jail, text)
    r = jail.sh("echo ran")
    assert r.returncode != 0 and "ran" not in r.stdout
    assert error in r.stderr


@needs_pasta
def test_project_file_can_make_the_jail_stricter(jail):
    (jail.work / "token.secret").write_text("canary-custom\n")
    (jail.work / ".agent-jail").write_text("net = none\ngit = ro\nhide = *.secret\n")
    r = jail.run("--dry-run", "--net", "isolated", "--host-port", "11434", "shell", net="")
    assert "pasta" not in r.stdout
    assert "makes the jail stricter: net none, git ro, hide *.secret, no host ports" in r.stderr
    r = jail.sh("cat token.secret; git -c user.name=t -c user.email=t@example.com "
                "commit -q --allow-empty -m x && echo committed")
    assert "canary" not in r.stdout and "committed" not in r.stdout


@needs_pasta
def test_project_file_cannot_loosen_the_jail(jail, host_tcp_server):
    plant_secrets(jail.work)
    (jail.work / ".agent-jail").write_text(
        f"net = host\ngit = off\nhost-port = {host_tcp_server}\nro = /etc\n"
        "show = .env\nno-hide\nmemory = off\ntasks = off\n")
    r = jail.sh(py(CONNECT, "127.0.0.1", str(host_tcp_server)) + "; cat .env; "
                "echo x > .git/hooks/pre-commit; ls /etc/shadow", net="isolated")
    assert r.stdout.split() == ["REFUSED"], r.stderr
    assert "Read-only file system" in r.stderr and "Permission denied" in r.stderr
    for setting in ["net = host", "git = off", f"host-port = {host_tcp_server}", "ro = /etc",
                    "show = .env", "no-hide", "memory = off", "tasks = off"]:
        assert f"ignoring '{setting}' in .agent-jail" in r.stderr


@needs_systemd
def test_project_file_can_only_lower_limits(jail):
    jail.with_user_session()
    (jail.work / ".agent-jail").write_text("memory = 1G\ntasks = 100000\n")
    r = jail.run("--dry-run", "--memory", "2G", "shell", net="none")
    assert "MemoryMax=1G" in r.stdout and "TasksMax=4096" in r.stdout
    assert "ignoring 'tasks = 100000'" in r.stderr


def test_bad_or_symlinked_project_file_stops_the_run(jail, tmp_path):
    (jail.work / ".agent-jail").write_text("net = nowhere\n")
    r = jail.sh("echo ran")
    assert "ran" not in r.stdout and ".agent-jail:1: net must be" in r.stderr

    (jail.work / ".agent-jail").unlink()
    (tmp_path / "elsewhere").write_text("net = none\n")
    (jail.work / ".agent-jail").symlink_to(tmp_path / "elsewhere")
    r = jail.sh("echo ran")
    assert "ran" not in r.stdout and "not a symlink" in r.stderr


# --- refusals and arguments -------------------------------------------------

@pytest.mark.parametrize("where", ["home", "ssh", "toplevel"])
def test_refuses_dangerous_directories(jail, where):
    cwd = {"home": jail.home, "ssh": jail.home / ".ssh", "toplevel": "/usr"}[where]
    r = jail.run("shell", "-c", "true", cwd=cwd)
    assert r.returncode != 0
    assert "refusing" in r.stderr


def test_rejects_bad_arguments(jail):
    assert jail.run("--host-port", "99999", "shell").returncode != 0
    assert jail.run("--net", "bogus", "shell").returncode != 0
    assert jail.run("no-such-profile").returncode != 0
    for opts in (["--memory", "lots"], ["--memory", "0"], ["--memory", "150%"],
                 ["--tasks", "-1"], ["--tasks", "many"]):
        assert jail.run(*opts, "shell").returncode != 0, opts


@needs_pasta
def test_dry_run_shows_the_sandbox(jail):
    r = jail.run("--dry-run", "shell", net="")
    assert r.returncode == 0
    assert "bwrap" in r.stdout and "--clearenv" in r.stdout
    assert "pasta" in r.stdout and "--no-map-gw" in r.stdout


# --- network ----------------------------------------------------------------

@needs_pasta
def test_isolated_net_blocks_host_loopback(jail, host_tcp_server):
    r = jail.sh(py(CONNECT, "127.0.0.1", str(host_tcp_server)), net="isolated")
    assert r.stdout.strip() == "REFUSED", r.stderr


@needs_pasta
def test_host_port_forwards_only_that_port(jail, host_tcp_server):
    r = jail.sh(py(CONNECT, "127.0.0.1", str(host_tcp_server)),
                "--host-port", str(host_tcp_server), net="isolated")
    assert r.stdout.strip() == "OPEN", r.stderr


@needs_pasta
def test_isolated_net_blocks_host_abstract_sockets(jail, host_abstract_socket):
    r = jail.sh(py(CONNECT_ABSTRACT, host_abstract_socket), net="isolated")
    assert r.stdout.strip() == "BLOCKED", r.stderr


def test_host_net_exposes_abstract_sockets(jail, host_abstract_socket):
    # Documents why --net host is unsafe: this is how X11 becomes reachable.
    r = jail.sh(py(CONNECT_ABSTRACT, host_abstract_socket), net="host")
    assert r.stdout.strip() == "OPEN", r.stderr


@needs_pasta
@pytest.mark.parametrize("addr", ["10.255.255.1", "192.168.255.1", "100.100.100.100"])
def test_isolated_net_rejects_private_ranges(jail, addr):
    r = jail.sh(py(CONNECT, addr, "80"), net="isolated")
    assert r.stdout.strip() == "REFUSED", r.stderr


def test_no_net_has_no_route(jail):
    r = jail.sh(py(CONNECT, "1.1.1.1", "443"), net="none")
    assert r.stdout.strip() != "OPEN"


@needs_pasta
@pytest.mark.skipif(os.environ.get("AGENT_JAIL_OFFLINE") == "1", reason="offline")
def test_isolated_net_reaches_the_internet(jail):
    code = ("import urllib.request; "
            "print(urllib.request.urlopen('https://example.com', timeout=10).status)")
    r = jail.sh(f'python3 -I -c "{code}"', net="isolated")
    assert r.stdout.strip() == "200", r.stderr
