# Threat model

## The adversary

The process running inside the jail: an AI coding agent with arbitrary code
execution as your user. It may be steered by a prompt injection (a README, issue,
web page or tool output it read), it may be mistaken, or the agent package itself
may be compromised. Assume it actively tries to get out.

## What is protected

| Asset | How |
|---|---|
| Files outside the working directory (SSH and GPG keys, browser profiles, password stores, other projects) | Not mounted. `$HOME` inside is an empty tmpfs; `/` is assembled from read-only `/usr` and a short list of `/etc` files. |
| Secret files inside the working directory (`.env`, private keys, `.netrc`) | Found by name before the run and covered with `/dev/null` on a `nodev` mount: opening them fails, and they can't be replaced, renamed, deleted or hard-linked. A symlink with a secret's name hides its target. |
| The jail's settings, in a project someone else wrote | A project's `.agent-jail` file can only make the jail stricter (a stricter `--net` or `--git`, more `--hide` patterns, lower limits); anything that would loosen it is ignored with a warning. A symlinked or unreadable one stops the run. |
| Secrets in your shell environment | `--clearenv`; only `HOME`, `USER`, `PATH`, `TERM`, `LANG` and profile settings are set. |
| Other runs of the same agent outside the jail | Agent state is private to the jail (`~/.local/share/agent-jail/<profile>`). The real config file is bound read-only. |
| Your files, while an agent is installed | `--install` and the picker run `npm install` in a jail that can write only the new package directory, with the same network filter. The installed package is read-only to the agent, and its command is refused if it leads outside the install. |
| Your next `git` command on the host | `.git/hooks`, `.git/config`, `config.worktree`, and those of submodules and worktrees are read-only; `.git` pointer files and `commondir` files are read-only; each `.git` directory and the directories above it are mount points, so a repository can't be moved aside and replaced by a fresh `git init`; new or replaced `.git` entries and new `commondir` files are reported after the run; symlinked hooks/config refuse to start. |
| Services on the host's loopback (local model servers, web UIs, databases) | Separate network namespace; only ports passed with `--host-port` are forwarded. |
| Your desktop session (X11, Wayland, D-Bus, PipeWire, systemd user manager) | `/run/user` is not mounted; abstract sockets such as X11's are unreachable from a separate network namespace. |
| The LAN, router, tailnet, cloud metadata endpoints | nftables in the jail's namespace rejects 10/8, 172.16/12, 192.168/16, 100.64/10, 169.254/16 (except the DNS forwarder), 127/8, multicast, IPv6 ULA and link-local. |
| Inbound exposure | pasta's automatic port forwarding (`-t`, `-u`, `-T`, `-U`, all `auto` by default) is set to `none`. |
| Other processes | PID namespace; no capabilities; nested user namespaces disabled (`--disable-userns`). |
| Your machine's memory and process table | With a systemd user session, the jail and pasta run in a scope with `MemoryMax` (50% of RAM), `MemorySwapMax=0` and `TasksMax` (4096). The jail's tmpfs `/tmp` and `$HOME` are charged to it. |
| Your terminal input | If the kernel still allows `TIOCSTI` keystroke injection, the agent is started in a new session. |

## What is not protected

Read these before trusting the jail with anything.

1. **Exfiltration.** The agent can send anything it can read (the working
   directory, its own API keys) to any public internet host, and to the model
   provider by design. Egress is filtered by address class, not allow-listed by
   destination. DNS queries can also carry data out.
2. **Secrets the hiding misses.** Files are hidden by name only. A secret in
   a file with an ordinary name, a copy committed to git history
   (`git show HEAD:.env`), or anything under `.git`, `node_modules` or a virtualenv
   is readable. Files the agent creates during the run aren't hidden. A file is
   hidden by mounting over it, so if a program on the host replaces it during the
   run (an editor that saves by writing a new file and renaming it over the old
   one, or `sed -i`), the jail sees the new, unhidden file.
3. **What it writes.** The working directory is the agent's output. Build files,
   `package.json` scripts, test files, `.envrc` and editor task files run
   unsandboxed when *you* run them. Review the diff. Git metadata, and agent and
   editor settings that can run commands (`.claude/`, `.codex/`, `.gemini/`,
   `.qwen/`, `.opencode/`, `.continue/`, `.vscode/`, `.mcp.json`, `opencode.json`,
   `.envrc`), are checked automatically and reported, not blocked. A tool that
   runs git on the host *while the agent is still running*, such as an editor's
   git integration, can run a new repository's or `commondir`'s hooks before you
   see the warning. An unfinished rebase the agent leaves behind can hold `exec`
   steps that run if you continue it.
4. **Other projects, through the agent's state.** A profile's state directory is
   shared by every project you run that agent in. An agent in one project can
   leave a plugin, hook or instruction there that the next jailed run, in a
   different project, loads. Use a separate `AGENT_JAIL_HOME` for projects you
   don't trust.
5. **Your terminal.** The agent writes to your terminal, so terminal escape
   sequences (for example OSC 52 clipboard writes, if your terminal allows them)
   reach the host.
6. **Kernel and bubblewrap bugs.** There is no seccomp filter beyond bubblewrap's
   own. A kernel privilege escalation from an unprivileged user namespace defeats
   the jail.
7. **Resource exhaustion.** Memory and task limits need a systemd user manager
   with the memory and pids controllers delegated (the default with cgroup v2);
   without one, there are none, and `--check` says so. CPU time and disk space
   are never limited: the agent can keep every core busy and fill the disk the
   project is on.
8. **Public addresses of things you own.** Only private ranges are blocked. A LAN
   device with a global IPv6 address, or a host service bound to all interfaces and
   reachable on one of the host's public addresses, can still be reached.
9. **`--net host`, `--git off`, `--ro`, `--force`, `--no-hide`, `--show`.** Each one removes a protection
   on purpose.
10. **The agents' own sandboxes.** Codex's sandbox can't run inside the jail and
   starts turned off there (see the README). The jail replaces it, but anything an
   agent's own sandbox would have blocked *inside* the working directory, such as
   writes to particular files, is no longer blocked.

## Verification

`tests/test_jail.py` attempts each escape listed under "What is protected" against
a real sandbox, using a throwaway `$HOME` with canary secrets. CI runs the suite on
every push.
