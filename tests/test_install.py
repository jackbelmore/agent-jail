"""Installing agent-jail itself: install.sh, --check and shell completion."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import JAIL, needs_pasta

ROOT = JAIL.parent.parent
COMPLETIONS = ROOT / "completions"


def profiles() -> list[str]:
    usage = subprocess.run([str(JAIL), "--help"], capture_output=True, text=True,
                           check=True).stdout
    return re.search(r"^Profiles: (.*)$", usage, re.M).group(1).split()


def install(jail, *args: str):
    return subprocess.run([str(ROOT / "install.sh"), *args], env=jail.env,
                          capture_output=True, text=True, timeout=60, check=False)


@needs_pasta
def test_check_starts_a_test_jail(jail):
    r = jail.run("--check", net="")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "a test jail starts (--net isolated)" in r.stdout
    assert "isn't on your PATH" in r.stdout


@needs_pasta
def test_install_script_installs_and_uninstalls(jail):
    jail.env["SHELL"] = "/usr/bin/fish"
    r = install(jail)
    assert r.returncode == 0, r.stdout + r.stderr
    command = jail.home / ".local/bin/agent-jail"
    assert command.read_bytes() == JAIL.read_bytes()
    assert command.stat().st_mode & 0o111
    assert (jail.home / ".local/share/bash-completion/completions/agent-jail").exists()
    # ~/.local/bin isn't on the test PATH: say how to add it, in the user's shell.
    assert "fish_add_path ~/.local/bin" in r.stdout
    assert "The jail works" in r.stdout

    jail.env["PATH"] = f"{command.parent}:{jail.env['PATH']}"
    assert "Ready." in install(jail).stdout

    r = install(jail, "--uninstall")
    assert r.returncode == 0
    assert not command.exists()
    assert "still in ~/.local/share/agent-jail" in r.stdout


@pytest.mark.parametrize("name", ["agent-jail.bash", "agent-jail.fish"])
def test_completions_know_every_profile(name):
    words = set(re.findall(r"[\w-]+", (COMPLETIONS / name).read_text()))
    assert set(profiles()) <= words


def bash_complete(line: str) -> list[str]:
    words = line.split(" ")
    script = (f"source {COMPLETIONS / 'agent-jail.bash'};"
              f" COMP_WORDS=({' '.join(map(repr, words))}); COMP_CWORD={len(words) - 1};"
              " _agent_jail; printf '%s\\n' \"${COMPREPLY[@]}\"")
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    return out.stdout.split()


def test_bash_completion():
    assert bash_complete("agent-jail co") == ["codex", "continue"]
    assert bash_complete("agent-jail --net ") == ["isolated", "none", "host"]
    assert bash_complete("agent-jail --install q") == ["qwen"]
    # After the profile, words are the agent's.
    assert bash_complete("agent-jail codex --n") == []


@pytest.mark.skipif(not shutil.which("fish"), reason="needs fish")
def test_fish_completion():
    def complete(line: str) -> list[str]:
        script = f"source {COMPLETIONS / 'agent-jail.fish'}; complete -C '{line}'"
        out = subprocess.run(["fish", "--no-config", "-c", script], capture_output=True,
                             text=True, check=True)
        return [row.split("\t")[0] for row in out.stdout.splitlines()]

    assert complete("agent-jail co") == ["codex", "continue"]
    assert complete("agent-jail --ch") == ["--check"]
    assert complete("agent-jail codex --ne") == []


def test_install_script_has_usage():
    r = subprocess.run([str(ROOT / "install.sh"), "--help"], capture_output=True, text=True,
                       check=False)
    assert r.returncode == 0
    assert "--uninstall" in r.stdout
    assert Path(ROOT / "install.sh").stat().st_mode & 0o111
