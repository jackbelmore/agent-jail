# bash completion for agent-jail. ./install.sh puts it where bash-completion
# finds it: ~/.local/share/bash-completion/completions/agent-jail

_agent_jail() {
    local cur=${COMP_WORDS[COMP_CWORD]} prev=${COMP_WORDS[COMP_CWORD - 1]} i
    local agents="claude codex agy qwen opencode continue crush copilot chatgpt"

    # Options come before the profile; after it, every word is the agent's.
    for ((i = 1; i < COMP_CWORD; i++)); do
        [[ ${COMP_WORDS[i]} == -* ]] && continue
        case ${COMP_WORDS[i - 1]} in
            --net | --allow-host | --host-port | --jail-port | --git | --ro | --bin | --hide | --show | --seccomp | --gpu | --memory | --tasks | --install)
                continue ;;
        esac
        return 0
    done

    case $prev in
        --net)       mapfile -t COMPREPLY < <(compgen -W "isolated none host" -- "$cur"); return ;;
        --seccomp)   mapfile -t COMPREPLY < <(compgen -W "on off" -- "$cur"); return ;;
        --gpu)       mapfile -t COMPREPLY < <(compgen -W "on off" -- "$cur"); return ;;
        --git)       mapfile -t COMPREPLY < <(compgen -W "protect ro off" -- "$cur"); return ;;
        --install)   mapfile -t COMPREPLY < <(compgen -W "$agents" -- "$cur"); return ;;
        --ro | --bin) mapfile -t COMPREPLY < <(compgen -f -- "$cur"); return ;;
        --memory)    mapfile -t COMPREPLY < <(compgen -W "25% 50% 75% 4G 8G off" -- "$cur"); return ;;
        --tasks)     mapfile -t COMPREPLY < <(compgen -W "1024 4096 off" -- "$cur"); return ;;
        --allow-host | --host-port | --jail-port | --hide | --show) return ;;
    esac
    if [[ $cur == -* ]]; then
        mapfile -t COMPREPLY < <(compgen -W "--net --allow-host --host-port --jail-port --git --ro --bin --hide --show
            --no-hide --seccomp --wayland --blend --gpu --memory --tasks --shell --list --check --install --force --dry-run --help --version" \
            -- "$cur")
    else
        mapfile -t COMPREPLY < <(compgen -W "$agents shell" -- "$cur")
    fi
}
complete -F _agent_jail agent-jail
