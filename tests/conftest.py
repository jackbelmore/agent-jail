import os
import shutil
import socket
import subprocess
import threading
from pathlib import Path

import pytest

JAIL = Path(__file__).resolve().parent.parent / "bin" / "agent-jail"


def _userns_works() -> bool:
    if not shutil.which("bwrap"):
        return False
    probe = subprocess.run(
        ["bwrap", "--unshare-user", "--ro-bind", "/", "/", "true"],
        capture_output=True, check=False,
    )
    return probe.returncode == 0


if not _userns_works():
    pytest.skip("bubblewrap with unprivileged user namespaces is not available",
                allow_module_level=True)

needs_pasta = pytest.mark.skipif(
    not (shutil.which("pasta") and shutil.which("nft")),
    reason="--net isolated needs pasta and nft",
)


class Jail:
    """A throwaway $HOME with a project directory to run agent-jail in."""

    def __init__(self, root: Path):
        self.home = root / "home"
        self.work = self.home / "project"
        self.work.mkdir(parents=True)
        (self.home / ".ssh").mkdir()
        (self.home / ".ssh" / "id_canary").write_text("PRIVATE KEY CANARY\n")
        self.bin = root / "bin"
        self.bin.mkdir()
        self.env = {
            "HOME": str(self.home),
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "XDG_RUNTIME_DIR": str(root),
            "TERM": "dumb",
            "CANARY_TOKEN": "sk-canary-should-not-leak",
        }
        subprocess.run(["git", "init", "-q", str(self.work)], check=True)

    def run(self, *args: str, cwd: Path | None = None, net: str = "none"):
        cmd = [str(JAIL)]
        if net:
            cmd += ["--net", net]
        cmd += list(args)
        return subprocess.run(
            cmd, cwd=cwd or self.work, env=self.env,
            capture_output=True, text=True, timeout=60, check=False,
        )

    def sh(self, script: str, *opts: str, net: str = "none"):
        return self.run(*opts, "shell", "-c", script, net=net)

    def fake_npm_tool(self, package: str, command: str) -> Path:
        """Install a stand-in for an npm-packaged agent CLI on PATH."""
        pkg = self.home / ".npm-global" / "lib" / "node_modules" / package
        (pkg / "bin").mkdir(parents=True)
        exe = pkg / "bin" / command
        exe.write_text("#!/bin/sh\necho fake-agent \"$@\"\n")
        exe.chmod(0o755)
        (self.bin / command).symlink_to(exe)
        return pkg


@pytest.fixture
def jail(tmp_path):
    return Jail(tmp_path)


@pytest.fixture
def host_tcp_server():
    """A TCP listener on the host's 127.0.0.1, standing in for e.g. Ollama."""
    srv = socket.create_server(("127.0.0.1", 0))
    stop = threading.Event()

    def serve():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
                conn.sendall(b"HOST-SERVICE\n")
                conn.close()
            except OSError:
                pass

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    yield srv.getsockname()[1]
    stop.set()
    t.join()
    srv.close()


@pytest.fixture
def host_abstract_socket():
    """An abstract unix socket on the host, like Xwayland's @/tmp/.X11-unix/X0."""
    name = f"agent-jail-test-{os.getpid()}-{threading.get_ident()}"
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind("\0" + name)
    s.listen()
    yield name
    s.close()
