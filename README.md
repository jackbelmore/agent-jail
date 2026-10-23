<p align="center">
  <img src="docs/img/hero.svg" alt="agent-jail: an AI coding agent works inside a glowing box with your project folder, while your SSH keys, passwords, home network and other projects stay locked outside">
</p>

<p align="center">
  <a href="https://github.com/jackbelmore/agent-jail/actions/workflows/ci.yml"><img src="https://github.com/jackbelmore/agent-jail/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/platform-Linux-2dd4bf" alt="Platform: Linux">
  <img src="https://img.shields.io/badge/agents-8-38bdf8" alt="8 agents">
  <img src="https://img.shields.io/badge/licence-MIT-a78bfa" alt="Licence: MIT">
</p>

**agent-jail** runs AI coding agents (Claude Code, Codex, Antigravity, Copilot
and more) in a locked room on your Linux computer. Inside, the agent can work
on the project you started it in. Everything else on your computer stays out of
its reach.

## Why you need this

AI coding agents don't just suggest code. They **run commands on your computer**
with the same access you have, often without asking first. And all day long they
read text written by strangers: web pages, issues, other people's code. One
hidden instruction in any of it can take over the agent:

<p align="center">
  <img src="docs/img/story.svg" alt="How it goes wrong: 1, you ask the agent to fix a failing test. 2, it reads a file with a hidden instruction to upload your SSH keys and .env. 3, without agent-jail your keys are sent away; with agent-jail the keys are not there to send.">
</p>

Agents have their own permission settings, but the agent enforces those itself,
and "auto" or "yolo" modes turn many of them off. agent-jail puts the walls
**outside** the agent, in the Linux operating system, so they hold however the
agent is set up and whatever it's tricked into doing.

## Without and with agent-jail

<p align="center">
  <img src="docs/img/without-with.svg" alt="Without agent-jail, the agent can reach everything you can: SSH keys, saved passwords, other projects, cloud logins, your home router, apps on this PC and your terminal. With agent-jail, it gets this project and the public internet, and everything else is locked outside.">
</p>

## What it protects you from

<p align="center">
  <img src="docs/img/protects.svg" alt="What agent-jail protects you from: your keys and passwords, secret files in the project, your home network, traps planted for later, your terminal, API keys in your shell, your computer's memory, and other programs.">
</p>

## What it can't protect you from

No tool makes an AI agent completely safe. These three are still up to you:

<p align="center">
  <img src="docs/img/careful.svg" alt="What agent-jail can't protect you from: code the agent writes runs with all your access when you run it later; it can upload the project's files to the internet unless you use --allow-host; and it can delete or break the project folder, so commit to git first.">
</p>

> [!TIP]
> **Two good habits:** run `git commit` before you start the agent, and
> `git diff` to read what it changed before you run any of it.

> [!WARNING]
> agent-jail is a sandbox, not a virtual machine. It shares your computer's Linux
> kernel, so a serious kernel bug could let an agent out. The full list of limits
> is in the [threat model](docs/THREAT_MODEL.md).

## Get started in 3 steps

<p align="center">
  <img src="docs/img/steps.svg" alt="Get started in three steps: 1, install once with ./install.sh. 2, open your project with cd. 3, start an agent with agent-jail.">
</p>

```sh
git clone https://github.com/jackbelmore/agent-jail
cd agent-jail
./install.sh              # installs the agent-jail command and checks your system

cd ~/Projects/my-app      # any project of yours
agent-jail                # pick an agent from the list
```

`./install.sh` tells you if anything is missing and how to install it. Then
`agent-jail` shows the agents it knows. Pick one with the arrow keys and Enter.
If it isn't installed yet, `agent-jail` installs it for you, inside a jail too:

<p align="center">
  <img src="docs/picker.svg" alt="The agent-jail picker: eight coding agents, whether each is installed, and an offer to install Codex inside the jail">
</p>

## Supported agents

| Agent | Start it with | Log in the first time |
|---|---|---|
| Claude Code | `agent-jail claude` | Type `/login`, open the link, paste the code back |
| Codex | `agent-jail codex` | `agent-jail codex login --device-auth`, then enter the code it shows on the web page |
| Antigravity CLI | `agent-jail agy` | Choose "Google OAuth", open the link, paste the code back. Install it first with [Google's installer](https://antigravity.google/docs/getting-started?tab=cli) |
| Qwen Code | `agent-jail qwen` | Inside the app |
| OpenCode | `agent-jail opencode` | `agent-jail opencode auth login` |
| Continue | `agent-jail continue` | Uses your `~/.continue/config.yaml` |
| Crush | `agent-jail crush` | `agent-jail crush login` |
| GitHub Copilot CLI | `agent-jail copilot` | `agent-jail copilot login --device-code` |

> [!NOTE]
> Each agent logs in **once, inside the jail**, and that login is kept apart
> from your normal one. Logins that open your browser and wait for it to come
> back to `localhost` can't finish in the jail, which is why the table uses the
> ones that give you a code. More about each agent is in
> [the guide](docs/GUIDE.md#supported-agents).

## See for yourself

This is a real session inside the jail. An SSH key exists on the computer, but
not in the jail. The router and an app on the same computer (Ollama) can't be
reached. The public internet works. Git hooks can't be changed:

<p align="center">
  <img src="docs/inside.svg" alt="A shell inside agent-jail: the home directory holds only the project, an SSH key outside the jail is missing, the router and the host's Ollama refuse connections, example.com answers, and a git hook can't be written">
</p>

Run `agent-jail shell` in any project to look around yourself.

## Why not just...?

| | The agent's own settings | A Docker container | A virtual machine | **agent-jail** |
|---|:-:|:-:|:-:|:-:|
| Keeps your SSH keys, passwords and other projects away from the agent | ⚠️ varies; reading is often allowed everywhere | ✅ if you mount only the project | ✅ | ✅ |
| Keeps it off your home network and the apps on your computer | ⚠️ internet on or off | ❌ reachable by default | ⚠️ depends on setup | ✅ |
| Stops it booby-trapping your git hooks | ⚠️ varies by agent | ❌ `.git` is writable | ❌ if the folder is shared | ✅ |
| Holds even if the agent is tricked, or runs in "auto" mode | ⚠️ partly | ✅ | ✅ | ✅ |
| Holds against a bug in the Linux kernel | ❌ | ❌ | ✅ | ❌ |
| Setting it up | Learn each agent's settings | An image, mounts and logins | A whole second computer | One command |

**Use a virtual machine** if a kernel bug is a real worry for you. **Use
agent-jail** for strong everyday protection with no setup. Other sandboxes made
for AI agents (Docker Sandboxes, Anthropic's sandbox-runtime, ai-jail) are
compared fairly in [docs/ALTERNATIVES.md](docs/ALTERNATIVES.md).

## How it works

<p align="center">
  <img src="docs/img/how-it-works.svg" alt="How it works: four layers around the agent. Limits (systemd) cap memory and processes. Network (pasta and nftables) gives it its own connection that reaches only the public internet. Files (bubblewrap) give it its own view of the disk with only your project. Kernel rules (seccomp) refuse dangerous requests to the Linux kernel.">
</p>

Each layer is a standard Linux tool. bubblewrap is the same tool Flatpak uses to
sandbox desktop apps. agent-jail itself is one readable bash script that sets
them up together, and its tests try dozens of ways to break out. The details
are in [the guide](docs/GUIDE.md#how-it-works-in-simple-terms).

## Handy options

```sh
agent-jail codex                                   # start Codex straight away
agent-jail --net none claude                       # no internet at all
agent-jail --allow-host api.anthropic.com claude   # only the sites you list
agent-jail --host-port 11434 opencode              # let it use Ollama on this computer
agent-jail --shell codex                           # look around as the agent would
agent-jail --check                                 # check that everything is set up
```

Options you always want can go in `~/.config/agent-jail/config`. A project can
have an `.agent-jail` file too, but it can only make the jail stricter. Every
option is in [the guide](docs/GUIDE.md#usage).

## Questions

<details>
<summary><b>Is this a virtual machine?</b></summary>

No. It uses features built into Linux to give the agent a much smaller view of
your computer. It starts instantly and needs no setup, but it shares your
computer's Linux kernel.
</details>

<details>
<summary><b>Will my agent still work normally?</b></summary>

Mostly. The differences:

- It logs in separately, once, with a code instead of a browser redirect.
- It can't reach apps running on your own computer, unless you allow one with
  `--host-port`.
- Files outside the project aren't there. Add one with `--ro PATH` if the agent
  needs to read it.
- Debuggers such as `gdb` and `strace` don't work inside, unless you use
  `--seccomp off`.
</details>

<details>
<summary><b>Where do the agents' logins and settings go?</b></summary>

In `~/.local/share/agent-jail/<agent>/`, not in your normal folders, so nothing
the agent changes there affects the agent when you run it outside the jail.
</details>

<details>
<summary><b>What does it need?</b></summary>

Linux, plus bubblewrap, passt, nftables and Node.js. `./install.sh` checks for
them and tells you what to install:

```sh
sudo dnf install bubblewrap passt nftables npm          # Fedora
sudo apt install bubblewrap passt nftables nodejs npm   # Debian, Ubuntu
```

Full requirements, including a note for Ubuntu 24.04, are in
[the guide](docs/GUIDE.md#requirements).
</details>

<details>
<summary><b>How do I update or remove it?</b></summary>

To update, run `git pull` and then `./install.sh` again. To remove it, run
`./install.sh --uninstall`, then delete `~/.local/share/agent-jail` to remove
the agents' logins too.
</details>

## Learn more

- 📖 [The full guide](docs/GUIDE.md): every option, exactly what the agent can
  see, and the security holes each defence closes
- 🛡️ [Threat model](docs/THREAT_MODEL.md): what it protects against, and what it
  doesn't
- ⚖️ [Alternatives](docs/ALTERNATIVES.md): how it compares with other sandboxes
- 🔧 Design notes: [the seccomp filter](docs/SECCOMP.md) and
  [`--allow-host`](docs/ALLOW_HOST.md)

agent-jail was built with Claude (Anthropic's AI) in Claude Code; the story is
in [the guide](docs/GUIDE.md#how-this-was-built).

## Licence

MIT
