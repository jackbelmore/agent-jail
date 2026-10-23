"""The seccomp filter: its numbers, what the program returns, and what it
refuses in a real jail. Design: docs/SECCOMP.md."""

import platform
import re
import struct
import subprocess
from pathlib import Path

import pytest
from conftest import JAIL

EPERM, ENOSYS = 1, 38
KILL, ALLOW, ERRNO = 0x80000000, 0x7FFF0000, 0x50000
ARCHES = {"x86_64": 0xC000003E, "aarch64": 0xC00000B7}
TIOCSTI, TIOCLINUX, TIOCGWINSZ = 0x5412, 0x541C, 0x5413


def deny_table() -> list[tuple[str, int, int, str]]:
    """SECCOMP_DENY from bin/agent-jail: (name, x86_64, generic, errno)."""
    body = re.search(r"readonly SECCOMP_DENY=\((.*?)\n\)", JAIL.read_text(), re.S).group(1)
    rows = re.findall(r'"(\w+)\|(\d+)\|(\d+)\|(\w+)"', body)
    return [(n, int(x), int(g), e) for n, x, g, e in rows]


def header_numbers(path: str, prefix: str) -> dict[str, int]:
    text = Path(path).read_text()
    return {m[0]: int(m[1]) for m in re.findall(rf"#define {prefix}(\w+)\s+(\d+)\b", text)}


@pytest.mark.skipif(not Path("/usr/include/asm/unistd_64.h").exists() or
                    platform.machine() != "x86_64", reason="needs x86_64 kernel headers")
def test_x86_64_numbers_match_the_kernel_headers():
    nr = header_numbers("/usr/include/asm/unistd_64.h", "__NR_")
    for name, x86, _, _ in deny_table():
        assert nr[name] == x86, name


@pytest.mark.skipif(not Path("/usr/include/asm-generic/unistd.h").exists(),
                    reason="needs kernel headers")
def test_aarch64_numbers_match_the_generic_table():
    nr = header_numbers("/usr/include/asm-generic/unistd.h", "__NR(?:3264)?_")
    for name, _, generic, _ in deny_table():
        assert nr[name] == generic, name


# --- the program, run through a classic BPF interpreter ----------------------

def program(arch: str) -> list[tuple[int, int, int, int]]:
    out = subprocess.run([str(JAIL), "--print-seccomp", arch], capture_output=True,
                         check=True).stdout
    assert len(out) % 8 == 0
    return [struct.unpack("<HBBI", out[i:i + 8]) for i in range(0, len(out), 8)]


def run_filter(prog, nr: int, arch: int, args=(0,) * 6) -> int:
    """Evaluate prog on a struct seccomp_data, as the kernel would."""
    data = struct.pack("<iIQ6Q", nr, arch, 0, *args)
    acc, pc = 0, 0
    while True:
        code, jt, jf, k = prog[pc]
        if code == 0x20:            # ld [k]
            acc = struct.unpack_from("<I", data, k)[0]
            pc += 1
        elif code == 0x15:          # jeq #k
            pc += 1 + (jt if acc == k else jf)
        elif code == 0x35:          # jge #k
            pc += 1 + (jt if acc >= k else jf)
        elif code == 0x06:          # ret #k
            return k
        else:
            raise AssertionError(f"unexpected BPF instruction {code:#x}")


@pytest.mark.parametrize("arch", ARCHES)
def test_filter_refuses_each_listed_call_and_allows_the_rest(arch):
    prog = program(arch)
    native = ARCHES[arch]
    denied = {}
    for name, x86, generic, errno in deny_table():
        nr = x86 if arch == "x86_64" else generic
        denied[nr] = ERRNO | (ENOSYS if errno == "ENOSYS" else EPERM)
        assert run_filter(prog, nr, native) == denied[nr], name
    ioctl = 16 if arch == "x86_64" else 29
    for nr in range(0, 460):
        if nr not in denied and nr != ioctl:
            assert run_filter(prog, nr, native) == ALLOW, nr


@pytest.mark.parametrize("arch", ARCHES)
def test_filter_refuses_terminal_injection_whatever_the_upper_bits(arch):
    prog = program(arch)
    ioctl = 16 if arch == "x86_64" else 29
    for cmd in (TIOCSTI, TIOCLINUX, TIOCSTI | 1 << 32, TIOCLINUX | 0xFFFF << 48):
        assert run_filter(prog, ioctl, ARCHES[arch], (0, cmd, 0, 0, 0, 0)) == ERRNO | EPERM
    assert run_filter(prog, ioctl, ARCHES[arch], (0, TIOCGWINSZ, 0, 0, 0, 0)) == ALLOW


@pytest.mark.parametrize("arch", ARCHES)
def test_filter_kills_other_abis(arch):
    prog = program(arch)
    for other in (0x40000003, 0x40000028, 0):  # i386, arm32, none
        assert run_filter(prog, 39, other) == KILL
    if arch == "x86_64":
        assert run_filter(prog, 0x40000000 | 39, ARCHES[arch]) == KILL  # x32 getpid


def test_no_filter_for_other_architectures():
    r = subprocess.run([str(JAIL), "--print-seccomp", "riscv64"], capture_output=True,
                       text=True, check=False)
    assert r.returncode != 0 and "no seccomp filter" in r.stderr


# --- in a real jail ----------------------------------------------------------

needs_filter = pytest.mark.skipif(platform.machine() not in ARCHES,
                                  reason="no seccomp filter on this architecture")

PROBE = """
import ctypes, fcntl, os, sys, termios
libc = ctypes.CDLL(None, use_errno=True)
nr = {"x86_64": dict(ptrace=101, keyctl=250, io_uring_setup=425),
      "aarch64": dict(ptrace=117, keyctl=219, io_uring_setup=425)}[os.uname().machine]
def call(n, *a):
    r = libc.syscall(n, *a)
    return "ok" if r >= 0 else os.strerror(ctypes.get_errno())
print("ptrace", call(nr["ptrace"], 0, 0, 0, 0))                    # PTRACE_TRACEME
print("keyctl", call(nr["keyctl"], 0, ctypes.c_long(-3), 0))      # the session keyring
print("io_uring", call(nr["io_uring_setup"], 1, 0))
try:
    fcntl.ioctl(0, termios.TIOCSTI, b"x")
    print("tiocsti ok")
except OSError as e:
    print("tiocsti", e.strerror)
"""


def probe(jail, *opts):
    r = jail.run(*opts, "shell", "-c", f"python3 -I -c '{PROBE}' </dev/null")
    return dict(line.split(" ", 1) for line in r.stdout.splitlines()), r


@needs_filter
def test_jail_refuses_ptrace_keyring_io_uring_and_tiocsti(jail):
    seen, r = probe(jail)
    assert seen == {"ptrace": "Operation not permitted", "keyctl": "Operation not permitted",
                    "io_uring": "Function not implemented",
                    "tiocsti": "Operation not permitted"}, r.stderr


@needs_filter
def test_seccomp_off_and_projects_cannot_turn_it_off(jail):
    seen, _ = probe(jail, "--seccomp", "off")
    assert seen["ptrace"] == "ok" and seen["tiocsti"] != "Operation not permitted"

    (jail.work / ".agent-jail").write_text("seccomp = off\n")
    seen, r = probe(jail)
    assert seen["ptrace"] == "Operation not permitted"
    assert "ignoring 'seccomp = off'" in r.stderr


@needs_filter
@pytest.mark.skipif(platform.machine() != "x86_64", reason="x32 is x86_64 only")
def test_x32_system_calls_kill_the_process(jail):
    r = jail.sh("python3 -I -c 'import ctypes; ctypes.CDLL(None).syscall(0x40000027)'; "
                "echo status=$?")
    assert "status=159" in r.stdout  # 128 + SIGSYS


@needs_filter
def test_seccomp_replaces_the_new_session(jail):
    r = jail.run("--dry-run", "shell", net="none")
    assert "--seccomp 3" in r.stdout and "--new-session" not in r.stdout
