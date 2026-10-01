# Changelog (Semantic Versioning)

## Unreleased (M7)

- Git: branch/dirty statusbar, diff gutter, blame line, commit screen.
- Vim modal editing (`hjkl`, operators, visual, `:w`/`:q`).
- Databases: list/select/backup/duplicate/drop (`F9`, confirmed).
- Plugins: `ocode.plugins` entry points (commands + event bus, isolated
  failures, `doctor` listing).
- Docker: compose detection, up/stop/restart, exec updates, log streaming
  (real `systemctl` execution too).
- LSP: minimal stdio client + opt-in merged completions (`editor.lsp`).
- DAP: client over stdio/TCP, breakpoint gutter + persistence,
  debugpy launch with stop-to-jump.
- AI: offline-first provider (explain/docstring), `ocode.ai_providers`
  extension point, `Ctrl+Shift+E/D`. No network by default.

## 1.0.0-rc1 — M6: polish & release candidate

- Performance: coalesced log refresh (5k lines/s+), benchmark suite
  (`tests/test_perf.py`: buffer, logs, search, diagnostics).
- UX: real `F1` help cheat-sheet, `ocode doctor keys` terminal report,
  `--ascii` flag, Logs/Shell/Problems bottom tabs.
- Packaging: man page, bash/zsh/fish completions, `debian/` skeleton
  (`dh-virtualenv` strategy), PyPI metadata hardened.
- Fixes: pytest collection warning (`TestSpec` → `CaseSpec`), forkpty
  warning filter, non-blocking PTY poll (no UI stalls), hardened Odoo
  root scan (permission-safe sibling search).

## 0.1.0 — M0–M5 development series

- **M5**: 12 Jinja2 scaffolds with diff preview + access automation;
  embedded `odoo shell` (PTY, history, production guard).
- **M4**: SQLite knowledge index; Odoo completion/diagnostics/`pylint-odoo`;
  quick-fixes; hover/outline/goto; real lint gate.
- **M3**: server run/stop/restart/update; flag catalog + profiles; live logs
  with traceback links; failure hints.
- **M2**: Odoo detection; module tree; quick-open; content search;
  related-file jumping; sessions.
- **M1**: piece-table buffer; undo; multi-cursor; tabs; custom editor widget.
- **M0**: app shell; core services (bus/config/commands/tasks); CLI; MIT.
