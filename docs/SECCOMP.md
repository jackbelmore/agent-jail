# The seccomp filter

bubblewrap can load a seccomp filter (`bwrap --seccomp FD`) that the kernel
checks on every system call the jailed process makes. This is the design of the
one `agent-jail` loads, and why it is built the way it is.

## What it is for

The jail's namespaces already decide what the agent can *reach*. The filter
narrows what it can *ask the kernel to do*. That matters in three ways:

1. **Terminal injection.** The `TIOCSTI` ioctl pushes characters into the
   terminal's input queue, and the shell runs them once the agent exits.
   Kernels since 6.2 can turn it off (`dev.tty.legacy_tiocsti=0`); where it is
   still on, `agent-jail` has had to start the agent in a new session, which
   detaches it from the terminal's job control and loses window resizes. A
   filter blocks `TIOCSTI` (and `TIOCLINUX`, which can do the same on a
   virtual console) without that cost.
2. **Shared kernel state.** The jail runs in your login session's *session
   keyring*. `keyctl` can read keys that host programs put there (Kerberos
   ticket caches, keys added with `keyctl add ... @s`) and add new ones.
3. **Kernel attack surface.** A kernel bug reachable from an unprivileged user
   namespace defeats the jail. Some interfaces have produced a large share of
   those bugs and are of no use to a coding agent: `io_uring`, `userfaultfd`,
   `bpf`, `perf_event_open`. Others need capabilities the jail doesn't have
   (mounting, modules, kexec), and refusing them up front means a permission
   check bug in one of them is not enough.

## Constraints

- **No build step.** `agent-jail` is one bash script that `install.sh` copies
  into place. A filter that needs a compiler, `libseccomp` headers or a Python
  module at install time would break that.
- **No binary blob we can't audit.** A precompiled `.bpf` file, or a helper
  binary with filters baked in, has to be trusted as shipped. Anthropic's
  sandbox-runtime, for example, ships per-architecture `apply-seccomp`
  binaries built from C and libseccomp. That is sound engineering, but the
  bytes in the package aren't something a reader can check against the
  source.

## Design

The filter is **assembled at run time by bash** from a table in
`bin/agent-jail`, written to the jail's private temporary directory, and handed
to bubblewrap on file descriptor 3. A classic BPF program is a flat list of
8-byte instructions (`u16 code, u8 jt, u8 jf, u32 k`); with only loads,
compare-and-jump and returns, a few lines of `printf` write it exactly. There
is nothing to install, and the program is short enough to read whole.

`agent-jail --print-seccomp [x86_64|aarch64]` writes the program to stdout for
inspection, and `tests/test_seccomp.py` runs it through a small BPF
interpreter to check what each system call gets.

The program, in order:

```
    ld   [4]                      ; seccomp_data.arch
    jeq  #AUDIT_ARCH_<native>, +1 ; x86_64 0xc000003e, aarch64 0xc00000b7
    ret  #KILL_PROCESS            ; any other ABI (i386 int 0x80, arm32)
    ld   [0]                      ; seccomp_data.nr
    jge  #0x40000000, 0, +1       ; x86_64 only: the x32 ABI
    ret  #KILL_PROCESS
    jeq  #__NR_ptrace, 0, +1      ; one pair per refused call...
    ret  #ERRNO(EPERM)
    ...
    jeq  #__NR_io_uring_setup, 0, +1
    ret  #ERRNO(ENOSYS)
    ...
    jeq  #__NR_ioctl, 0, +4
    ld   [24]                     ; low 32 bits of args[1], the ioctl command
    jeq  #TIOCSTI, +1, 0
    jeq  #TIOCLINUX, 0, +1
    ret  #ERRNO(EPERM)
    ret  #ALLOW
```

Points that are easy to get wrong, and how this handles them:

- **Other ABIs.** On x86_64 a 64-bit process can still make 32-bit system
  calls (`int 0x80`), which have different numbers; the x32 ABI uses the same
  architecture value with bit 30 set in the number. A filter that only matches
  x86_64 numbers misses both. Here both kill the process. 32-bit programs
  can't run in the jail as a result.
- **The ioctl command is 32 bits.** The kernel ignores the upper half of the
  second argument, so the filter must compare only the lower half (offset 24
  on little-endian machines), or `TIOCSTI | 1 << 32` slips past. Flatpak
  (CVE-2019-10063) and ai-jail (GHSA-w976-gw52-hvx2) both had this bug.
- **ENOSYS for io_uring.** Programs that try io_uring (libuv, Bun) fall back
  to ordinary system calls when it "doesn't exist"; with EPERM some report an
  error instead.
- **Numbers per architecture.** The table has the x86_64 and the generic
  (aarch64) number of each call; the test suite compares them with
  `asm/unistd_64.h` and `asm-generic/unistd.h` when the headers are installed.
  On other architectures there is no filter, and the jail falls back to the new
  session for `TIOCSTI`, as before.

## What it refuses

| Calls | Returns | Why |
|---|---|---|
| `ioctl(TIOCSTI)`, `ioctl(TIOCLINUX)` | EPERM | Typing into your terminal |
| `ptrace`, `process_vm_readv`, `process_vm_writev`, `kcmp`, `pidfd_getfd` | EPERM | Reading and rewriting other processes' memory, system calls and file descriptors |
| `keyctl`, `add_key`, `request_key` | EPERM | The session keyring is shared with your login session |
| `bpf`, `perf_event_open`, `userfaultfd` | EPERM | Frequent sources of kernel exploits; not needed by agents |
| `io_uring_setup`, `io_uring_enter`, `io_uring_register` | ENOSYS | The same, and io_uring operations bypass per-call filtering |
| `mount`, `umount2`, `pivot_root`, `open_tree`, `move_mount`, `fsopen`, `fsconfig`, `fsmount`, `fspick`, `mount_setattr` | EPERM | Need capabilities the jail lacks; refused up front |
| `init_module`, `finit_module`, `delete_module`, `kexec_load`, `kexec_file_load`, `reboot`, `swapon`, `swapoff`, `acct`, `syslog`, `quotactl`, `open_by_handle_at` | EPERM | The same |

Not in the filter, on purpose:

- **`unshare`, `clone` and `setns` with namespace flags.** Filtering `clone`
  flags means also refusing `clone3`, whose flags are in memory a filter can't
  read. bubblewrap's `--disable-userns` already stops the jail from making user
  namespaces, and without one the other namespace types need capabilities it
  doesn't have.
- **Socket families.** The network namespace and the nftables rules decide
  where sockets lead. Unix sockets are needed inside the jail.
- **`personality`.** Its flags mostly matter for 32-bit programs, which the
  filter already stops.

## What it costs

- `gdb`, `strace` and other debuggers don't work inside the jail.
- 32-bit programs are killed on their first system call.
- Programs that use the kernel keyring (`keyctl`, some Kerberos setups) fail.

`--seccomp off` turns the filter off for a run, or `seccomp = off` in the
config file for good. A project's `.agent-jail` can turn it on but not off.
