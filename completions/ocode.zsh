#compdef ocode
# zsh completion for ocode
_ocode() {
    local -a cmds flags
    cmds=(doctor:'diagnostics' index:'rebuild index' init:'workspace stubs')
    flags=(--conf: --odoo-bin: --db: --no-index --log-level: --config-dir: --ascii --version --help)
    if (( CURRENT == 3 )) && [[ $words[2] == doctor ]]; then
        _describe -t checks 'doctor check' '(keys)'
        return
    fi
    _arguments -C '1: :->cmd' '*:: :->args' && return
    case $state in
        cmd) _describe -t commands 'ocode' cmds ;;
        args) _arguments $flags ;;
    esac
}
_ocode "$@"
