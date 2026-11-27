# Changelog

## Unreleased

### Added

- Opt-in `--blend` flag (and `blend` config option): launches Blender inside
  the jail (Wayland + GPU, sanitized read-only config) with `blender_mcp`
  auto-started on the jail's private `127.0.0.1:9876`. Ignored with a warning
  in a project's `.agent-jail`.
- Opt-in `--bin PATH` flag (and `bin = PATH` config option) to expose an
  executable read-only and place it on `PATH` (preserving symlink basenames);
  ignored with a warning in a project's `.agent-jail`.
- Opt-in `--jail-port PORT` flag to forward `127.0.0.1:PORT` from the host into
  the jail (useful for running tools like Blender's MCP server inside their own
  jail), and explicit `--gpu on` support (including NVIDIA device nodes) for
  non-desktop profiles.
- Opt-in `--wayland` flag (and `wayland` config option): binds only the Wayland
  socket (no GPU, X11 or D-Bus) so TUI agents like Codex can paste clipboard
  images on Wayland. Ignored with a warning in a project's `.agent-jail`.
- A profile for OpenAI's ChatGPT desktop app (the Codex app): `agent-jail
  chatgpt`. It is the first profile with a window: the jail passes in the
  Wayland socket and, unless you say `--gpu off`, the GPU's render node, and
  nothing else of your session (no D-Bus, no X11). The app's state is in the
  jail, Chromium's own sandbox and Codex's are off because the jail disables the
  user namespaces they need, and only the folder you start it in is writable.
  New option `--gpu on|off` (a project's `.agent-jail` can turn it off, not on).
- A profile for Google's Antigravity CLI (`agy`), which replaces Gemini CLI.
  `agent-jail` runs the `agy` that Google's installer put on your PATH, with its
  state in the jail; a project's `.agents/` folder is now watched too.
- `agent-jail codex` says to log in with `codex login --device-auth` until Codex
  has a login: its browser login can't reach the jail.
- A new README for people who are new to this: pictures of what the jail
  protects and what it doesn't, a three-step start, and a simple comparison with
  agents' own settings, Docker and virtual machines. The full reference moved to
  [docs/GUIDE.md](docs/GUIDE.md), and the detailed comparison of other sandboxes
  to [docs/ALTERNATIVES.md](docs/ALTERNATIVES.md).
- An "Alternatives" section in the README comparing ai-jail, Anthropic's
  sandbox-runtime and Docker Sandboxes (plus container-use and landrun), with
  where each is the better choice.
- Profiles for Crush (`crush`, `@charmland/crush`) and GitHub Copilot CLI
  (`copilot`, `@github/copilot`), each installed and run in the jail before
  adding it. Crush runs its Go binary directly with metrics off; Copilot starts
  with auto-update and its own sandbox off. Their project files that can run
  commands (`.crushrc`, `crush.json`, `.crush/commands`, `.github/`, `.cursor/`)
  are now watched too.
- Files in the project that look like secrets (`.env`, `.env.*`, `*.pem`,
  `*.key`, `id_ed25519`, `.netrc`, ...) are hidden: `/dev/null` is mounted over
  each one, so the agent can't read, change, rename or delete it. Templates such
  as `.env.example` stay visible. `--hide PATTERN` hides more, `--show PATTERN`
  keeps a file visible, and `--no-hide` turns it off.
- `--allow-host NAME` (repeatable, `*.example.com` and `:port` allowed) limits
  the network to HTTPS to the names you list. The jail gets no network of its
  own, only a Unix socket to a small proxy on the host, which refuses names that
  resolve to private addresses and lists what it refused after the run. A
  project's `.agent-jail` can narrow the list. Needs `python3`. Design in
  [docs/ALLOW_HOST.md](docs/ALLOW_HOST.md).
- A seccomp filter, on by default on x86_64 and aarch64: it refuses
  `TIOCSTI` and `TIOCLINUX` terminal injection, `ptrace` and other ways into
  other processes, the kernel keyring (shared with your login session),
  `io_uring`, `bpf`, `userfaultfd`, `perf_event_open`, and calls that need
  capabilities the jail lacks. bash assembles it at run time from a table, with
  no build step or precompiled file; `--print-seccomp` prints it, and
  [docs/SECCOMP.md](docs/SECCOMP.md) explains it line by line. Where it is on,
  agents no longer start in a new session on kernels that allow `TIOCSTI`.
  `--seccomp off` turns it off, for debuggers.
- Config files: `~/.config/agent-jail/config` sets options you always want
  (`net = none`, `hide = *.secret`, `memory = 8G`), and the command line wins
  over it. A project's `.agent-jail` file uses the same format but can only make
  the jail stricter; settings that would loosen it are ignored with a warning.
- Memory and process limits: with a systemd user session, the jail runs in a
  scope with at most 50% of RAM (no swap) and 4096 processes and threads.
  `--memory SIZE|PERCENT|off` and `--tasks N|off` change them. Without systemd
  the jail runs as before, and `--check` says the limits are off.

### Removed

- The Gemini CLI profile (`gemini`). Google is retiring Gemini CLI in favour
  of Antigravity CLI; use `agent-jail agy`. A copy installed with
  `--install gemini` stays in `~/.local/share/agent-jail/tools/gemini` until you
  delete it.

### Fixed

- An agent could get its own git hooks run on the host. It could move `.git`
  aside and `git init` a fresh repository in its place, or write
  `.git/commondir` to point git at a directory it made. Each `.git`, and every
  directory between it and the project root, is now a mount point that can't be
  renamed; existing `commondir` files are read-only, and new ones, like a
  replaced `.git`, are reported after the run.
- Git hooks and config were writable when the project directory itself was
  named `venv`, `target` or `node_modules`, because the search for `.git`
  skipped it as a dependency tree.
- `agent-jail codex` could stop at "Background server has incompatible feature
  settings". Codex's background app server updates itself into the jail's
  `~/.codex/packages`, so it got newer than the read-only Codex that starts it.
  The jail now runs Codex with `-c features.daemon_auto_start=false`, which
  keeps the server inside the Codex process.

## 0.2.0 (2026-10-22)

### Added

- Run `agent-jail` with no profile to pick an agent from a list (arrow keys or
  numbers), with whether each is installed and what the jail will allow.
- Agents that aren't installed are installed for you: `--install NAME` (or the
  picker) puts the npm package in `~/.local/share/agent-jail/tools/NAME/`, with
  npm and the package's install scripts running inside a jail that can write only
  the new copy. `--list` prints the list.
- Profiles for Claude Code (`claude`), Codex (`codex`) and Gemini CLI (`gemini`).
  Codex's own sandbox starts turned off, because it needs the user namespaces the
  jail disables.
- `./install.sh` installs the command in `~/.local/bin` with tab completion for
  bash and fish, says how to put it on `PATH` for your shell, and checks the
  setup; `./install.sh --uninstall` removes it.
- `agent-jail --check` reports missing requirements with the command that
  installs them for your distribution, and starts a test jail.
- After the run, a warning when the agent created or changed project files that
  agents, editors or direnv run commands from (`.claude/`, `.codex/`, `.mcp.json`,
  `.vscode/`, `.envrc`, ...).

### Changed

- Profiles use an agent installed by `agent-jail` before one on `PATH`, and run
  native binaries directly and scripts with `node`.
- Gemini CLI and Qwen Code start with auto-update off: their packages are
  read-only inside the jail, so update with `--install` instead.

## 0.1.0 (2026-10-10)

First release: one bubblewrap launcher for OpenCode, Qwen Code and Continue, with
private agent state, read-only git hooks and config, and a pasta + nftables
network that reaches the public internet only, plus escape tests and CI.
