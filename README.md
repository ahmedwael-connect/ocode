# ocode — smart, Odoo-aware code editor for the terminal

> PRD: [`ocode-requirements.md`](ocode-requirements.md) · License: MIT · Status: v1.0.0-rc1 (M6)

`ocode` is a terminal (TUI) code editor built for Odoo developers working over
SSH or on headless servers. It combines editing, Odoo project awareness
(modules, models, views, security), server lifecycle (run/update/logs/shell),
static Odoo intelligence (index, completion, diagnostics, `pylint-odoo`) and
boilerplate generators — without leaving the terminal.

## Install

```bash
pipx install ocode            # recommended (isolated)
# or
pip install ocode
```

Ubuntu APT (M6: `debian/` skeleton ships `dh-virtualenv` rules; PPA publishing
is documented but not yet automated — see `debian/README.Debian`):

```bash
dpkg-buildpackage -b -uc -us   # from repo root on Ubuntu 22.04/24.04
sudo dpkg -i ../ocode_*.deb
```

Requirements: Python ≥ 3.10, Ubuntu 22.04/24.04 recommended.
Optional tools: `ripgrep` (fast search), `pylint-odoo` (Odoo lint),
`xclip`/`wl-clipboard` (clipboard over SSH uses OSC 52 otherwise).

## Quickstart

```bash
ocode /opt/odoo17            # open an Odoo installation (auto-detected)
ocode my_addons/sale_custom  # open a module folder
ocode models/sale_order.py:42
ocode doctor                 # environment + project diagnostics
ocode doctor keys            # terminal key-delivery report
ocode index                  # rebuild the knowledge index
ocode init                   # write .ocode/{config,servers}.toml stubs
```

Press `F1` inside the app for the full key cheat-sheet.

## Key bindings (default)

| Area | Keys |
|---|---|
| Quick open / module switch | `Ctrl+P` / `Ctrl+Shift+M` |
| Related file cycle / popup | `Alt+M` / `Alt+R` (`Ctrl+K M` / `Ctrl+K R` fallback) |
| Go to definition / references | `F12` / `Shift+F12` |
| Completion / snippet | `Ctrl+Space`, `Tab` accepts |
| Lint file / module, quick fix | `F8` / `Ctrl+F8`, `Ctrl+.` |
| Server start-stop / restart | `F6` / `F5` |
| Restart + update (current / choose) | `Ctrl+F5` / `Ctrl+Shift+F5` |
| Shell toggle / send to shell | ``Ctrl+` `` (or `F7`) / `Ctrl+Enter` |
| Bottom panel (Logs/Shell/Problems) | `Ctrl+J` cycles |
| Generators | `Ctrl+Shift+N` |
| Help / quit | `F1` / `Ctrl+Q` |

Some terminals swallow `Ctrl+Shift`, `Alt`, ``Ctrl+` `` and `Ctrl+Enter`.
Every command has a fallback (`ocode doctor keys` tells you what arrives).

## Configuration

| Purpose | Path |
|---|---|
| User config | `~/.config/ocode/config.toml` |
| Server profiles | `<workspace>/.ocode/servers.toml` |
| Template overrides | `~/.config/ocode/templates/*.j2` |
| Index cache (safe to delete) | `~/.cache/ocode/index/` |
| Sessions, swap, shell history, logs | `~/.local/state/ocode/` |

```toml
# servers.toml example
[profile.dev]
odoo_bin = "/opt/odoo17/odoo-bin"
python   = "/opt/odoo17/venv/bin/python"
conf     = "/etc/odoo17.conf"
db       = "mydb"
mode     = "managed"          # managed | systemd | docker
flags    = ["--dev=reload,qweb,xml", "--log-level=info"]
lint_before_restart = "warn"  # off | warn | block
```

## Plugins (M7)

Third-party extensions register through the `ocode.plugins` entry-point group:

```toml
[project.entry-points."ocode.plugins"]
myplug = "myplug:register"
```

```python
from ocode.core.plugins import PluginAPI

def register(api: PluginAPI) -> None:
    api.commands.register("myplug.hello", "Say Hello", lambda: api.notify("hi"))
    api.bus.subscribe("server.log", lambda record: ...)
```

A failing plugin is isolated and reported — it never breaks the host.
`ocode doctor` lists discovered plugins.

## Features by milestone
- **M0** — app shell, event bus, layered config, command registry, CLI.
- **M1** — piece-table buffer, undo groups, multi-cursor, tabs, find/replace,
  tree-sitter-ready highlighting, atomic saves, swap recovery.
- **M2** — Odoo detection (root/version/conf/modules/venv/systemd), module
  tree, quick-open, ripgrep content search, related-file jumping, sessions.
- **M3** — server run/stop/restart/update (managed/systemd/docker), flag
  catalog, profiles, live logs with traceback links, failure hints.
- **M4** — SQLite knowledge index, Odoo completion, 15-rule diagnostics,
  `pylint-odoo`/`ruff` runners, quick-fixes, hover/outline/goto.
- **M5** — 12 Jinja2 scaffolds with diff preview, access-CSV automation,
  embedded `odoo shell` (PTY, history, production guard).
- **M6** — perf pass, `F1` help, `doctor keys`, man page, completions,
  Debian skeleton, v1.0.0-rc1.
- **M7 (in progress)** — git integration, Vim modal editing, DB helpers,
  plugin API (`ocode.plugins` entry points).

## Troubleshooting

- **Keys don't work**: run `ocode doctor keys`; prefer Kitty/WezTerm/Alacritty
  with Kitty keyboard protocol, or remap (keymap file: post-1.0).
- **No completions/diagnostics**: wait for `Indexed … models` in the status
  bar, or run `ocode index`. The cache is safe to delete.
- **`pylint-odoo` missing**: install it into the same venv that runs Odoo;
  `F8` shows a one-key hint.
- **Port in use / DB missing**: the status bar and a toast explain the cause
  with file links where available.
- **Production DB**: the shell shows a red banner and asks for confirmation.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/ruff check src tests && .venv/bin/mypy src/ocode && .venv/bin/pytest
```
