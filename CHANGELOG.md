# Changelog

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
