# Changelog

## Unreleased

### Added

- Files in the project that look like secrets (`.env`, `.env.*`, `*.pem`,
  `*.key`, `id_ed25519`, `.netrc`, ...) are hidden: `/dev/null` is mounted over
  each one, so the agent can't read, change, rename or delete it. Templates such
  as `.env.example` stay visible. `--hide PATTERN` hides more, `--show PATTERN`
  keeps a file visible, and `--no-hide` turns it off.

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
