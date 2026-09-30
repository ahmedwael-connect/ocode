# bash completion for ocode
_ocode_complete() {
    local cur prev cmds
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    cmds="doctor index init --conf --odoo-bin --db --no-index --log-level --config-dir --ascii --version --help"
    if [[ ${COMP_CWORD} -eq 2 && "${COMP_WORDS[1]}" == "doctor" ]]; then
        COMPREPLY=( $(compgen -W "keys" -- "$cur") )
        return 0
    fi
    COMPREPLY=( $(compgen -W "$cmds" -- "$cur") )
    return 0
}
complete -F _ocode_complete ocode
