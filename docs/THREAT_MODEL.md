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
| Secrets in your shell environment | `--clearenv`; only `HOME`, `USER`, `PATH`, `TERM`, `LANG` and profile settings are set. |
| Other runs of the same agent outside the jail | Agent state is private to the jail (`~/.local/share/agent-jail/<profile>`). The real config file is bound read-only. |
| Your files, while an agent is installed | `--install` and the picker run `npm install` in a jail that can write only the new package directory, with the same network filter. The installed package is read-only to the agent, and its command is refused if it leads outside the install. |
| Your next `git` command on the host | `.git/hooks`, `.git/config`, `config.worktree`, and those of submodules and worktrees are read-only; `.git` pointer files are read-only; new `.git` entries are reported after the run; symlinked hooks/config refuse to start. |
| Services on the host's loopback (local model servers, web UIs, databases) | Separate network namespace; only ports passed with `--host-port` are forwarded. |
| Your desktop session (X11, Wayland, D-Bus, PipeWire, systemd user manager) | `/run/user` is not mounted; abstract sockets such as X11's are unreachable from a separate network namespace. |
| The LAN, router, tailnet, cloud metadata endpoints | nftables in the jail's namespace rejects 10/8, 172.16/12, 192.168/16, 100.64/10, 169.254/16 (except the DNS forwarder), 127/8, multicast, IPv6 ULA and link-local. |
| Inbound exposure | pasta's automatic port forwarding (`-t`, `-u`, `-T`, `-U`, all `auto` by default) is set to `none`. |
| Other processes | PID namespace; no capabilities; nested user namespaces disabled (`--disable-userns`). |
| Your terminal input | If the kernel still allows `TIOCSTI` keystroke injection, the agent is started in a new session. |

## What is not protected

Read these before trusting the jail with anything.

1. **Exfiltration.** The agent can send anything it can read (the working
   directory, its own API keys) to any public internet host, and to the model
   provider by design. Egress is filtered by address class, not allow-listed by
   destination. DNS queries can also carry data out.
2. **What it writes.** The working directory is the agent's output. Build files,
   `package.json` scripts, test files, `.envrc` and editor task files run
   unsandboxed when *you* run them. Review the diff. Git metadata, and agent and
   editor settings that can run commands (`.claude/`, `.codex/`, `.gemini/`,
   `.qwen/`, `.opencode/`, `.continue/`, `.vscode/`, `.mcp.json`, `opencode.json`,
   `.envrc`), are checked automatically and reported, not blocked.
3. **Other projects, through the agent's state.** A profile's state directory is
   shared by every project you run that agent in. An agent in one project can
   leave a plugin, hook or instruction there that the next jailed run, in a
   different project, loads. Use a separate `AGENT_JAIL_HOME` for projects you
   don't trust.
4. **Your terminal.** The agent writes to your terminal, so terminal escape
   sequences (for example OSC 52 clipboard writes, if your terminal allows them)
   reach the host.
5. **Kernel and bubblewrap bugs.** There is no seccomp filter beyond bubblewrap's
   own. A kernel privilege escalation from an unprivileged user namespace defeats
   the jail.
6. **Resource exhaustion.** No CPU, memory, PID or disk limits. A fork bomb or a
   full disk is your problem.
7. **Public addresses of things you own.** Only private ranges are blocked. A LAN
   device with a global IPv6 address, or a host service bound to all interfaces and
   reachable on one of the host's public addresses, can still be reached.
8. **`--net host`, `--git off`, `--ro`, `--force`.** Each one removes a protection
   on purpose.
9. **The agents' own sandboxes.** Codex's sandbox can't run inside the jail and
   starts turned off there (see the README). The jail replaces it, but anything an
   agent's own sandbox would have blocked *inside* the working directory, such as
   writes to particular files, is no longer blocked.

## Verification

`tests/test_jail.py` attempts each escape listed under "What is protected" against
a real sandbox, using a throwaway `$HOME` with canary secrets. CI runs the suite on
every push.
