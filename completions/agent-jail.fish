# fish completion for agent-jail. ./install.sh puts it where fish finds it:
# ~/.config/fish/completions/agent-jail.fish

set -l profiles claude codex gemini qwen opencode continue crush copilot shell
# Options come before the profile; after it, every word is the agent's.
set -l before "not __fish_seen_subcommand_from $profiles"

complete -c agent-jail -f
complete -c agent-jail -n $before -a claude -d 'Claude Code'
complete -c agent-jail -n $before -a codex -d Codex
complete -c agent-jail -n $before -a gemini -d 'Gemini CLI'
complete -c agent-jail -n $before -a qwen -d 'Qwen Code'
complete -c agent-jail -n $before -a opencode -d OpenCode
complete -c agent-jail -n $before -a continue -d Continue
complete -c agent-jail -n $before -a crush -d Crush
complete -c agent-jail -n $before -a copilot -d 'GitHub Copilot CLI'
complete -c agent-jail -n $before -a shell -d "bash with the jail's view"

complete -c agent-jail -n $before -l net -x -a 'isolated none host' -d 'Network mode'
complete -c agent-jail -n $before -l allow-host -x -d 'Reach only this host, over HTTPS'
complete -c agent-jail -n $before -l host-port -x -d 'Forward 127.0.0.1:PORT to the host'
complete -c agent-jail -n $before -l git -x -a 'protect ro off' -d 'Git protection'
complete -c agent-jail -n $before -l ro -r -F -d 'Also expose a path read-only'
complete -c agent-jail -n $before -l hide -x -d 'Also hide project files named like this'
complete -c agent-jail -n $before -l show -x -d "Don't hide files named like this"
complete -c agent-jail -n $before -l no-hide -d 'Hide no files, not even .env and keys'
complete -c agent-jail -n $before -l seccomp -x -a 'on off' -d 'The seccomp filter'
complete -c agent-jail -n $before -l memory -x -a '25% 50% 75% 4G 8G off' -d 'Memory limit'
complete -c agent-jail -n $before -l tasks -x -a '1024 4096 off' -d 'Process and thread limit'
complete -c agent-jail -n $before -l shell -d "Start bash with the agent's view"
complete -c agent-jail -n $before -l list -d 'List the agents'
complete -c agent-jail -n $before -l check -d 'Check that everything needed is installed'
complete -c agent-jail -n $before -l install -x -a 'claude codex gemini qwen opencode continue crush copilot' \
    -d 'Install or update an agent'
complete -c agent-jail -n $before -l force -d 'Run in a directory that is normally refused'
complete -c agent-jail -n $before -l dry-run -d 'Print the sandbox command'
complete -c agent-jail -n $before -s h -l help -d 'Show help'
complete -c agent-jail -n $before -l version -d 'Print the version'
