# agent-jail

[![CI](https://github.com/jackbelmore/agent-jail/actions/workflows/ci.yml/badge.svg)](https://github.com/jackbelmore/agent-jail/actions/workflows/ci.yml)

Run an AI coding agent (OpenCode, Qwen Code, Continue, or a shell) so that it can
write only the directory you started it in, sees nothing else of your home
directory, and reaches the public internet but not your localhost services, your
X server, your LAN or your tailnet.

Agents' own permission prompts are policy checked by the agent itself, and
"yolo"/`--auto` modes turn them off. `agent-jail` puts the boundary in the kernel
instead, so it holds whatever the model is talked into doing.

```console
$ cd ~/Projects/some-repo
$ agent-jail opencode                     # cloud model, public internet only
$ agent-jail --host-port 11434 opencode   # plus a local Ollama on the host
$ agent-jail --net none qwen              # no network at all
$ agent-jail --shell opencode             # a shell with the agent's exact view
```

## What the agent gets

| | Inside the jail |
|---|---|
| Current directory | read/write |
| Agent's own config, sessions, cache | read/write, but in `~/.local/share/agent-jail/<profile>/`, **not** the agent's normal directories |
| Your real agent config file | read-only (you keep one config; the agent can't edit it) |
| Rest of `$HOME` (`~/.ssh`, browser profiles, other projects, other agents) | invisible (`$HOME` is an empty tmpfs) |
| `/usr` | read-only |
| `/etc` | `passwd`, `group`, TLS roots, timezone and a generated `hosts`/`resolv.conf` only |
| `.git/hooks`, `.git/config` | read-only (commits still work; `--git ro` blocks those too) |
| Environment | cleared (API keys and tokens in your shell don't leak in) |
| `/run/user` (D-Bus, Wayland, PipeWire) | absent |
| Network (`--net isolated`, the default) | own network namespace via [pasta]; nftables rejects loopback, RFC 1918, CGNAT/Tailscale, link-local and multicast; public internet works |
| Processes | own PID namespace; can't create user namespaces; no capabilities |

After the agent exits, `agent-jail` warns about any **new** `.git` directory or
pointer file it created, because git runs hooks and `core.fsmonitor` commands from
those the next time you type `git status` on the host.

What it does **not** protect against (exfiltration of what's in the directory, code
you later run, kernel bugs, resource exhaustion, DNS tunnelling) is listed in
[docs/THREAT_MODEL.md](docs/THREAT_MODEL.md).

## Why these particular defences

Each one closes a hole found in earlier versions of these scripts, which used
`bwrap --share-net` and bound the agent's real config directories:

1. **Persistence through the agent's own config.** The jailed agent could write
   `~/.config/opencode/`, which the *unjailed* `opencode` also reads (including its
   `node_modules/` plugins). A prompt-injected session could plant a plugin that
   runs outside the jail next time. Fixed by giving each profile private state and
   importing the real config read-only.
2. **Persistence through git.** `.git/hooks/` and `.git/config` were writable.
   Fixed by binding them read-only, re-binding worktree pointer files read-only, and
   reporting new git metadata after the run.
3. **The X server.** With `--share-net`, the jail shares the host's network
   namespace, and abstract Unix sockets (such as Xwayland's `@/tmp/.X11-unix/X0`)
   belong to the network namespace, not the filesystem. On the machine this was
   written on, the X server accepts any process of the same user
   (`SI:localuser`), so a "jailed" process could open an X11 connection and, from
   there, read and inject input into X11 windows. Fixed by giving the jail its own
   network namespace.
4. **Localhost, the LAN and the tailnet.** `--share-net` also exposed every
   service on `127.0.0.1` (an unauthenticated Ollama API, web UIs). Moving to pasta
   alone was not enough: pasta opens outbound connections from the host on the
   jail's behalf, so the router's admin page and the host's own Tailscale address
   were still reachable. Fixed by an nftables egress filter applied inside the
   jail's namespace, and by turning off pasta's default automatic port forwarding
   in all four directions.

Every one of these has a regression test in [tests/test_jail.py](tests/test_jail.py)
that attempts the escape.

## Install

Requirements: Linux with unprivileged user namespaces and a merged `/usr`,
[bubblewrap] 0.8 or newer, and for the default network mode `pasta` (package
`passt`) and `nft` (package `nftables`).

```sh
install -m 755 bin/agent-jail ~/.local/bin/
```

Profiles find the agent on your `PATH`. Each profile's state starts empty, so log
in once inside the jail (for example `agent-jail opencode auth login`); the keys
then live only in the jail's state directory.

## Usage

```
agent-jail [options] PROFILE [ARGS...]

  --net isolated|none|host   network mode (default isolated; host is unsafe)
  --host-port PORT           expose 127.0.0.1:PORT from the host (repeatable)
  --git protect|ro|off       git protection (default protect)
  --ro PATH                  expose an extra path read-only
  --shell                    run bash with the profile's sandbox instead
  --force                    run in a directory that is normally refused
  --dry-run                  print the pasta/bwrap command line
```

It refuses to start in `$HOME` or any directory above it, in top-level and
mount-root directories, and inside `~/.ssh`, `~/.config`, `~/.local` and similar.

Adding an agent is a short shell function: see `profile_opencode` in
[bin/agent-jail](bin/agent-jail).

## Tests

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -v
```

The tests run against a throwaway `$HOME`, start real sandboxes, and try each
escape: reading a canary SSH key, leaking an environment variable, writing a git
hook or `core.fsmonitor`, re-pointing a worktree's `.git` file, planting a plugin
in the agent's config, following a symlink planted at an import path, reaching a
host TCP service and a host abstract socket, and connecting to private address
ranges. CI runs them on Ubuntu 24.04 together with shellcheck, ruff and gitleaks.

## How this was built

The original `cn-jail`, `qwen-jail` and `opencode-jail` scripts came out of Claude
Code sessions in September and October 2026. I set the requirement (third-party
agents may only ever read the directory I run them in, and cloud models always go
through the jail); Claude wrote the bubblewrap invocations, probed from inside what
was still visible, and found and blocked a telemetry endpoint in one agent's
package.

This repository merges and hardens them. In October 2026 I asked Claude (Opus, in
Claude Code) to review my scripts before publishing them. That review found holes
1 and 2 above. While redesigning the network side, Claude tested and found 3 and 4
on my own machine and proposed the pasta + nftables design. Claude wrote most of
the code and the tests; I decided what to fix and publish and reviewed the result.
Commits carry `Co-Authored-By` trailers.

## Licence

MIT

[bubblewrap]: https://github.com/containers/bubblewrap
[pasta]: https://passt.top/
