# bash completion for agent-jail. ./install.sh puts it where bash-completion
# finds it: ~/.local/share/bash-completion/completions/agent-jail

_agent_jail() {
    local cur=${COMP_WORDS[COMP_CWORD]} prev=${COMP_WORDS[COMP_CWORD - 1]} i
    local agents="claude codex gemini qwen opencode continue"

    # Options come before the profile; after it, every word is the agent's.
    for ((i = 1; i < COMP_CWORD; i++)); do
        [[ ${COMP_WORDS[i]} == -* ]] && continue
        case ${COMP_WORDS[i - 1]} in
            --net | --host-port | --git | --ro | --hide | --show | --install) continue ;;
        esac
        return 0
    done

    case $prev in
        --net)       mapfile -t COMPREPLY < <(compgen -W "isolated none host" -- "$cur"); return ;;
        --git)       mapfile -t COMPREPLY < <(compgen -W "protect ro off" -- "$cur"); return ;;
        --install)   mapfile -t COMPREPLY < <(compgen -W "$agents" -- "$cur"); return ;;
        --ro)        mapfile -t COMPREPLY < <(compgen -f -- "$cur"); return ;;
        --host-port | --hide | --show) return ;;
    esac
    if [[ $cur == -* ]]; then
        mapfile -t COMPREPLY < <(compgen -W "--net --host-port --git --ro --hide --show
            --no-hide --shell --list --check --install --force --dry-run --help --version" \
            -- "$cur")
    else
        mapfile -t COMPREPLY < <(compgen -W "$agents shell" -- "$cur")
    fi
}
complete -F _agent_jail agent-jail
