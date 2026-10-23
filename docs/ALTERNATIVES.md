# Alternatives to agent-jail

Other tools confine coding agents too, and some do things `agent-jail` doesn't.
This is how they compare as of October 2026, from each project's own
documentation and, where there is source, its code. Corrections are welcome.

| | agent-jail | [ai-jail] | [sandbox-runtime] (`srt`) | [Docker Sandboxes] (`sbx`) |
|---|---|---|---|---|
| What it is | A bash script that runs npm-packaged CLI agents | A Rust launcher for AI agents | Anthropic's general-purpose process sandbox, made for Claude Code; a CLI and a library | Docker's product: a microVM per agent |
| Platforms | Linux | Linux, macOS | Linux, macOS (Windows in alpha) | macOS 14+ on Apple silicon, Windows 11, Ubuntu 24.04+ |
| Isolation | bubblewrap namespaces, seccomp, a systemd scope | bubblewrap, Landlock, seccomp, rlimits; `sandbox-exec` on macOS | bubblewrap and seccomp; Seatbelt on macOS | A hypervisor: the agent has its own kernel |
| Files, by default | The project read-write; agent state private to the jail; the rest of `$HOME` absent | The project read-write; a private `$HOME`, but the agent's real credential directory (`~/.claude`, ...) read-write | Reads allowed everywhere; writes only where you allow them | The project, mounted read-write (or a private clone of it), and a read-only skills store; nothing else from the host |
| Network, by default | Any public address; not localhost, the LAN or a tailnet | Only the agent's API host and package registries, through a proxy | None until you list domains | Deny by default, with a default list of allowed domains |
| Domain allowlist | `--allow-host`, opt-in | Yes | Yes | Yes, also by method and path |
| Secrets | Clears the environment; hides `.env` and key files in the project | Masks files you list; passes the agent's own API key in | Passes the environment through, apart from what you list; can mask credentials and swap them back in at the proxy | Swaps a placeholder for real API keys at the host proxy, so keys never enter the VM |
| Git hooks and config | Read-only, `.git` pinned against swaps, new metadata reported | Writable by default (documented; protected in `--lockdown`) | Always write-protected: hooks, `.git/config`, shell rc files, `.mcp.json`, IDE folders | Writable in direct mode (documented as a risk); clone mode keeps them out of the host repository |
| Needs | bubblewrap, pasta, nftables; Node for the agents; python3 for `--allow-host` | One binary and bubblewrap | Node, bubblewrap, socat, ripgrep | KVM, a Docker account (`sbx login`) |
| Licence | MIT | GPL-3.0 | Apache-2.0 | Proprietary (the CLI and local use are free) |
| Status | Personal project | Very active, frequent releases | "Beta research preview" | 0.x, actively released |

Where each one is the better choice:

- **Docker Sandboxes** if a kernel bug escaping the sandbox is in your threat
  model, or the agent needs to run Docker or install system packages with
  `sudo`. Its credential injection keeps API keys out of the agent's reach,
  which `agent-jail` can't do: here the agent holds its own login. It costs a VM
  per agent, KVM, a Docker login, and closed source.
- **sandbox-runtime** if you want to wrap arbitrary commands (MCP servers,
  build steps) rather than whole agents, embed the sandbox in your own tool, or
  need macOS. Its policy is yours to write, and the default lets the sandboxed
  process read your whole home directory.
- **ai-jail** if you want macOS and Linux, a stricter network by default, or
  Landlock as a second layer, and you accept its own description of itself:
  "an accident guard, not a security boundary". Sharing the agent's real
  credentials is convenient, and it's what `agent-jail` avoids.
- **agent-jail** if you're on Linux, want one command per agent with nothing in
  your home directory exposed, and want the things an agent writes that run
  later (git hooks, agent and editor settings) protected or reported by default.
  It shares the host kernel, has no credential injection, and its default
  network is the public internet unless you use `--allow-host`.

Two related tools work differently:

- [container-use] (Dagger, Apache-2.0) is an MCP server that gives each agent
  a container and a git branch of its own. The agent itself runs on your
  machine; only the work it routes through container-use's tools is contained.
  It is good for running several agents in parallel.
- [landrun] (MIT) is a Landlock-only sandbox for any command: no namespaces and
  no root, with filesystem and TCP-port rules. It doesn't filter by domain or
  address, and it knows nothing about agents.

None of `agent-jail`'s code comes from these projects. ai-jail is GPL-3.0, so it
was read for ideas only; the seccomp and `--allow-host` designs here are our own
(see [SECCOMP.md](SECCOMP.md) and
[ALLOW_HOST.md](ALLOW_HOST.md)).

[ai-jail]: https://github.com/akitaonrails/ai-jail
[sandbox-runtime]: https://github.com/anthropic-experimental/sandbox-runtime
[Docker Sandboxes]: https://docs.docker.com/ai/sandboxes/
[container-use]: https://github.com/dagger/container-use
[landrun]: https://github.com/Zouuup/landrun
