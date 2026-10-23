#!/usr/bin/env bash
# Install agent-jail for yourself: the command in ~/.local/bin, and tab
# completion for bash and fish. Run it again after a git pull to update.
#
#   ./install.sh              install or update, then check the setup
#   ./install.sh --uninstall  remove the command and completions (the agents'
#                             logins and installs in ~/.local/share/agent-jail stay)
set -euo pipefail

src=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
bin_dir=${AGENT_JAIL_BIN_DIR:-$HOME/.local/bin}
data=${XDG_DATA_HOME:-$HOME/.local/share}
config=${XDG_CONFIG_HOME:-$HOME/.config}

# file in this repository|mode|where it goes
files=(
    "bin/agent-jail|755|$bin_dir/agent-jail"
    "completions/agent-jail.bash|644|$data/bash-completion/completions/agent-jail"
)
command -v fish >/dev/null &&
    files+=("completions/agent-jail.fish|644|$config/fish/completions/agent-jail.fish")

tilde() { printf '%s\n' "${1/#"$HOME"/\~}"; }

case ${1:-} in
    '') ;;
    --uninstall)
        for f in "${files[@]}"; do
            dest=${f##*|}
            if [[ -e $dest ]]; then rm -f -- "$dest"; echo "removed $(tilde "$dest")"; fi
        done
        echo "The agents' logins and installs are still in $(tilde "$data/agent-jail");"
        echo "delete that folder to remove them too."
        exit 0 ;;
    -h|--help)
        sed -n '2,7s/^# \{0,1\}//p' "$0"
        exit 0 ;;
    *)
        echo "usage: $0 [--uninstall]" >&2
        exit 2 ;;
esac

for f in "${files[@]}"; do
    IFS='|' read -r from mode dest <<<"$f"
    install -D -m "$mode" -- "$src/$from" "$dest"
    echo "installed $(tilde "$dest")"
done

case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *)
        echo
        echo "$(tilde "$bin_dir") isn't on your PATH yet. Add it, then open a new terminal:"
        echo
        case ${SHELL##*/} in
            fish) echo "    fish_add_path $(tilde "$bin_dir")" ;;
            zsh)  echo "    echo 'export PATH=\"$bin_dir:\$PATH\"' >> ~/.zshrc" ;;
            *)    echo "    echo 'export PATH=\"$bin_dir:\$PATH\"' >> ~/.bashrc" ;;
        esac ;;
esac

"$bin_dir/agent-jail" --check
