# fish completion for ocode
complete -c ocode -f
complete -c ocode -n __fish_use_subcommand -a doctor -d 'diagnostics'
complete -c ocode -n __fish_use_subcommand -a index -d 'rebuild index'
complete -c ocode -n __fish_use_subcommand -a init -d 'workspace stubs'
complete -c ocode -n '__fish_seen_subcommand_from doctor' -a keys -d 'key report'
complete -c ocode -l conf -d 'Odoo config file' -r
complete -c ocode -l odoo-bin -d 'Path to odoo-bin' -r
complete -c ocode -l db -d 'Database name' -r
complete -c ocode -l no-index -d 'Disable background indexing'
complete -c ocode -l log-level -d 'Log level' -r
complete -c ocode -l config-dir -d 'Override config dir' -r
complete -c ocode -l ascii -d 'ASCII icons'
complete -c ocode -l version -d 'Print version'
