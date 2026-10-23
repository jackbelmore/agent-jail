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
from conftest import JAIL, needs_node, needs_pasta

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


# --- git: things that run on the host later --------------------------------

def test_git_hooks_and_config_are_read_only(jail):
    r = jail.sh("echo 'touch /tmp/pwned' > .git/hooks/post-checkout; "
                "printf '[core]\\n\\tfsmonitor = touch /tmp/pwned\\n' >> .git/config")
    assert r.stderr.count("Read-only file system") == 2
    assert not (jail.work / ".git/hooks/post-checkout").exists()
    assert "fsmonitor" not in (jail.work / ".git/config").read_text()


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
    assert "created git metadata" in r.stderr
    assert "vendor/lib/.git" in r.stderr


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
    for name in ["Claude Code", "Codex", "Gemini CLI", "Qwen Code", "OpenCode", "Continue"]:
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
