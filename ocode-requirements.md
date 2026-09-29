# ocode — Project Requirements Document (PRD)

| Field | Value |
|---|---|
| **Product name** | `ocode` |
| **Tagline** | A smart, Odoo-aware code editor for the terminal |
| **Platform** | Ubuntu 22.04 LTS / 24.04 LTS (Debian-based distros as best effort) |
| **Language / UI** | Python 3.10+ / [Textual](https://textual.textualize.io/) (modern TUI) |
| **Distribution** | PyPI (`pip` / `pipx`) and APT (`.deb`, Launchpad PPA) |
| **Version of this doc** | 0.1 (draft) |
| **License** | LGPL-3.0 or MIT (to be decided; see Open Questions) |

---

## 1. Introduction

### 1.1 Purpose
`ocode` is a terminal-based code editor built specifically for Odoo developers. It combines a fast text editor with deep knowledge of Odoo's project structure (addons paths, modules, manifests, models, views, security files) and integrates the Odoo server lifecycle (run, stop, restart, update modules, logs, shell) in a single interface, so a developer working over SSH or in a headless server can do the whole edit → update → test → debug loop without leaving the terminal.

### 1.2 Problem Statement
Odoo developers on remote servers usually juggle `nano`/`vim`, several terminals for logs and the Odoo shell, and repetitive boilerplate (models, views, access rights). General editors have no understanding of Odoo's cross-file relationships (model ↔ view ↔ security ↔ manifest). `ocode` fixes this.

### 1.3 Goals
1. Zero-configuration detection of Odoo installations, addons paths, and modules.
2. One-keystroke navigation between related Odoo files.
3. Boilerplate generation that follows Odoo conventions and updates dependent files (manifest, access CSV) automatically.
4. Built-in server control, live logs, and an interactive Odoo shell.
5. Odoo-aware autocompletion, highlighting, and diagnostics (including `pylint-odoo`).
6. Fast, responsive, and installable with a single command.

### 1.4 Non-Goals (v1.0)
- Not a GUI editor and not a replacement for a full IDE (no debugger UI in v1).
- No Odoo.sh / cloud deployment management.
- No support for Windows/macOS as first-class targets (may work, not guaranteed).
- No collaborative/multi-user editing.

### 1.5 Target Users
- Odoo developers working on remote/headless Ubuntu servers over SSH.
- Odoo devops/sysadmins making quick module fixes.
- Developers who prefer keyboard-driven terminal workflows.

### 1.6 Supported Odoo Versions
Odoo 14.0 through the latest stable (17.0, 18.0+), Community and Enterprise. Version-specific behavior (e.g., `<tree>` → `<list>` in newer versions, `attrs` → inline `invisible=` expressions in 17+) must be handled through a per-version profile.

---

## 2. Technology Stack

| Area | Choice | Notes |
|---|---|---|
| TUI framework | Textual (+ Rich) | Layout, CSS styling, mouse, async workers |
| Language | Python ≥ 3.10 | Ubuntu 22.04 ships 3.10 |
| Syntax parsing | `tree-sitter` + grammars (python, xml, javascript, css, scss, json, yaml, csv, html) | Incremental parsing, highlighting, folding |
| Python analysis | `ast` + `jedi` (or `pyright` via LSP as optional) | Odoo index uses `ast` (no import of Odoo code) |
| XML analysis | `lxml` | Well-formedness, XPath validation |
| Linting | `pylint` + `pylint-odoo`, `ruff` (optional), `flake8` fallback | Run as subprocess, async |
| Process control | `asyncio.subprocess`, `ptyprocess` / `pyte` | Server process, shell PTY emulation |
| Config | TOML (`tomllib` / `tomli`), Odoo `.conf` via `configparser` | |
| Storage | SQLite (`sqlite3`) | Odoo symbol index cache |
| File watching | `watchfiles` | External change detection, reindex |
| Packaging | `pyproject.toml` (hatchling), `debhelper` + `dh-python` | |
| Testing | `pytest`, `pytest-asyncio`, Textual `Pilot` | |
| Typing / quality | `mypy`, `ruff` | |

---

## 3. System Architecture

### 3.1 High-Level Layers

```
┌────────────────────────────────────────────────────────────┐
│                      Textual UI Layer                      │
│  Screens · Widgets · Panels · Command Palette · Themes     │
├────────────────────────────────────────────────────────────┤
│                       Engine Layer                         │
│  SMN · OMLS · OSS · OTE · OPD · OSG · OKI · OSH · GIT ...  │
├────────────────────────────────────────────────────────────┤
│                    Core Services Layer                     │
│  Event Bus · Config · Keymap · Logging · Task Scheduler    │
├────────────────────────────────────────────────────────────┤
│                    System / OS Layer                       │
│  Filesystem · Subprocess · PTY · Clipboard · Watchers      │
└────────────────────────────────────────────────────────────┘
```

### 3.2 Engines Overview

| Code | Engine | Responsibility |
|---|---|---|
| **SMN** | Smart Module Navigation & File Engine | File tree, module awareness, search, related-file jumping |
| **OMLS** | Odoo Multi-Language Support Engine | Highlighting, autocomplete, diagnostics, linting for all Odoo languages |
| **OSS** | Odoo Server System Engine | Server run/stop/restart/update, flags, logs, config |
| **OTE** | Odoo Text Editor Engine | The editor core: buffer, cursor, editing, views, undo, search/replace |
| **OPD** | Odoo Project Detection Engine *(added)* | Detect Odoo root, `odoo-bin`, `addons_path`, version, config file |
| **OKI** | Odoo Knowledge Index Engine *(added)* | Index models, fields, XML IDs, menus, actions, groups for completion/navigation |
| **OSG** | Odoo Scaffolding & Generator Engine *(added)* | Model/view/security/wizard/report/controller templates |
| **OSH** | Odoo Shell Engine *(added)* | Embedded interactive `odoo shell` with `env`/`cr` |
| **GIT** | Git Integration Engine *(added)* | Status badges, diff gutter, stage/commit basics |
| **CFG** | Configuration & Keymap Engine *(added)* | User settings, workspace settings, keybinding remap |
| **CMD** | Command Palette & Action Engine *(added)* | Unified command registry (`Ctrl+Shift+P`) |
| **SES** | Session & Recovery Engine *(added)* | Restore open tabs, layout, swap/crash recovery |

### 3.3 Architectural Principles
- **Engines are decoupled**: they communicate only through the **Event Bus** and public service interfaces (no engine imports another engine's internals).
- **UI never blocks**: anything longer than ~16 ms (parsing, indexing, linting, search, subprocess I/O) runs in async workers/threads/processes.
- **Odoo code is never imported** for analysis; static parsing only (safe, fast, works without a DB or running server).
- **Everything is a command**: each action is registered in CMD, so it is bindable, searchable in the palette, and testable.
- **Plugin-ready**: engines register through an entry-point group (`ocode.engines`), enabling future third-party extensions.

### 3.4 Suggested Package Layout

```
ocode/
├── pyproject.toml
├── debian/                     # APT packaging
├── src/ocode/
│   ├── __main__.py             # CLI entry: `ocode [path]`
│   ├── app.py                  # Textual App
│   ├── core/                   # event bus, config, keymap, commands, tasks
│   ├── engines/
│   │   ├── smn/  omls/  oss/  ote/  opd/  oki/  osg/  osh/  git/
│   ├── ui/                     # screens, widgets, themes (.tcss)
│   ├── templates/              # Jinja2 scaffolding templates
│   ├── data/                   # per-Odoo-version profiles, snippets
│   └── utils/
└── tests/
```

---

## 4. Functional Requirements

**Priority legend (MoSCoW):** **M** = Must (v1.0), **S** = Should, **C** = Could, **W** = Won't (v1.0).

### 4.1 CLI Interface (Entry Point)

| ID | Requirement | Pri |
|---|---|---|
| FR-CLI-001 | `ocode` opens in the current directory; `ocode <path>` opens a file or folder. | M |
| FR-CLI-002 | `ocode <file>:<line>[:<col>]` opens at a position. | S |
| FR-CLI-003 | Flags: `--conf <odoo.conf>`, `--odoo-bin <path>`, `--db <name>`, `--version`, `--help`, `--no-index`, `--log-level`, `--config-dir`. | M |
| FR-CLI-004 | Sub-commands: `ocode doctor` (environment diagnostics), `ocode index` (rebuild index), `ocode init` (create workspace config). | S |
| FR-CLI-005 | Run as `sudo -e`/`EDITOR` compatible: `EDITOR=ocode` works for `git commit`, `crontab -e` (blocking mode, proper exit codes). | S |

### 4.2 Project & Environment Detection (OPD)

| ID | Requirement | Pri |
|---|---|---|
| FR-OPD-001 | Detect Odoo root by locating `odoo-bin` / `odoo/release.py` / `openerp-server`, walking up and down from the opened path. | M |
| FR-OPD-002 | Detect Odoo version from `odoo/release.py` and select the matching version profile. | M |
| FR-OPD-003 | Parse Odoo config (`/etc/odoo.conf`, `~/.odoorc`, `--conf`) to read `addons_path`, `db_name`, `db_user`, `http_port`, `logfile`, `data_dir`. | M |
| FR-OPD-004 | Detect module folders (directory containing `__manifest__.py` or legacy `__openerp__.py`). | M |
| FR-OPD-005 | Classify module locations: core (`odoo/addons`), enterprise, custom, third-party. | S |
| FR-OPD-006 | Detect Python interpreter / virtualenv used by Odoo (`venv`, `.venv`, systemd unit, `--python`). | S |
| FR-OPD-007 | Detect systemd service name (e.g., `odoo`, `odoo16`) for restart operations. | S |
| FR-OPD-008 | Detect Docker-based setups (docker-compose service running Odoo) and offer exec-mode commands. | C |
| FR-OPD-009 | Support multiple Odoo instances in one workspace; user selects an active profile. | S |

### 4.3 Smart Module Navigation & File Engine (SMN)

#### 4.3.1 File Tree
| ID | Requirement | Pri |
|---|---|---|
| FR-SMN-001 | Sidebar tree with two switchable views: **Files** (raw folders) and **Modules** (addons grouped by addons path, then module). | M |
| FR-SMN-002 | Module-aware nodes: icon/badge for module state (installed status if DB info available, version, has-errors). | S |
| FR-SMN-003 | Module virtual sub-groups: *Models, Views, Security, Data, Controllers, Wizards, Reports, Static, i18n, Tests*. | M |
| FR-SMN-004 | Tree operations: new file/folder, rename, delete (to trash), duplicate, copy path, reveal, collapse/expand all. | M |
| FR-SMN-005 | Respect `.gitignore` and configurable ignore globs (`__pycache__`, `*.pyc`, `node_modules`, `.git`). | M |
| FR-SMN-006 | Lazy loading for large trees (Odoo core has thousands of files); tree stays responsive (<100 ms expand). | M |
| FR-SMN-007 | Pinned/bookmarked files and folders per workspace. | S |
| FR-SMN-008 | Git status coloring in tree (modified, untracked, staged). | S |

#### 4.3.2 Navigation
| ID | Requirement | Pri |
|---|---|---|
| FR-SMN-010 | Navigate tree and open files using arrow keys, `Enter`, `Space` (preview), and mouse. | M |
| FR-SMN-011 | Hotkey focus switching between tree ↔ editor (`Ctrl+B` toggle sidebar, `Ctrl+0` focus tree, `Ctrl+1..9` focus editor group). | M |
| FR-SMN-012 | Tab bar with open files, dirty indicator, close/reorder, `Ctrl+Tab` MRU switching, `Alt+←/→` back/forward navigation history. | M |
| FR-SMN-013 | **Module Quick Jump** (`Ctrl+Shift+M`): fuzzy switch between modules across all addons paths. | M |
| FR-SMN-014 | **Key-file Quick Jump**: hotkeys to jump to the current module's `__manifest__.py`, `__init__.py`, `security/ir.model.access.csv`, main `views/*.xml`, and to the project's Odoo config file. | M |
| FR-SMN-015 | Breadcrumb bar showing `addons_path › module › folder › file › symbol`. | S |

#### 4.3.3 Related-File Jumping (Odoo relationships)
| ID | Requirement | Pri |
|---|---|---|
| FR-SMN-020 | `Alt+M` from a model file (`models/sale_order.py`) jumps to its view file (`views/sale_order_views.xml`); pressing again cycles through all related files. | M |
| FR-SMN-021 | Relationship map (resolved via OKI, falling back to naming conventions): **Model ↔ Views ↔ Security (access CSV / record rules) ↔ Data ↔ Report templates ↔ Wizard ↔ Controller ↔ JS/OWL component ↔ Tests ↔ i18n `.po`**. | M |
| FR-SMN-022 | "Related Files" popup (`Alt+R`) listing every related target with type icon; select with arrows. | M |
| FR-SMN-023 | Go-to-definition for Odoo references: `_inherit`/`comodel_name` → model class, `ref="module.xml_id"` → record, `action=`/`parent=` menu ids, `groups=` → group definition, `template t-call` → QWeb template, `model="..."` in view → Python model. | M |
| FR-SMN-024 | Find-references (reverse): from a model/field/xml-id list all XML, Python, and CSV usages. | S |
| FR-SMN-025 | Jump to inherited parent definitions and list all overrides of a method across modules (MRO-aware view). | S |
| FR-SMN-026 | All jump keybindings are remappable (see CFG). Because terminals send `Alt` as an `Esc` prefix, ocode must provide equivalents that do not rely on Alt (e.g., `Ctrl+K M`). | M |

#### 4.3.4 Smart Search
| ID | Requirement | Pri |
|---|---|---|
| FR-SMN-030 | **Quick Open** (`Ctrl+P`): fuzzy file search with ranking (recent files, current module boosted). | M |
| FR-SMN-031 | Search **types** selectable in the search bar: `Files`, `Folders`, `Modules`, `Symbols` (models, fields, methods, XML IDs), `In-File content`. Prefix syntax e.g. `>` commands, `@` symbols, `#` XML IDs, `:` line. | M |
| FR-SMN-032 | **Extension filter**: restrict by extensions, e.g. `ext:py,xml,json` or through a filter chip UI. | M |
| FR-SMN-033 | **Content search** across files/modules/workspace (`Ctrl+Shift+F`) with regex, case, whole-word toggles, include/exclude globs, and scope (*current file, module, addons path, workspace, Odoo core*). | M |
| FR-SMN-034 | Use `ripgrep` if installed (fast path); fall back to a built-in async Python searcher. | M |
| FR-SMN-035 | Streaming results with preview pane and jump-to-line; cancel long searches. | M |
| FR-SMN-036 | Replace-in-files with preview diff and per-hit confirmation. | S |
| FR-SMN-037 | Search history and saved searches. | C |

---

### 4.4 Odoo Multi-Language Support Engine (OMLS)

Supported languages: **Python, XML, HTML (QWeb), JavaScript (incl. OWL templates), CSS, SCSS, CSV, JSON, YAML, `.po/.pot`**, plus `__manifest__.py` (special-cased as a Python-literal dict with schema validation).

#### 4.4.1 Syntax Highlighting
| ID | Requirement | Pri |
|---|---|---|
| FR-OMLS-001 | Tree-sitter based highlighting for all languages above with theme-mapped capture groups. | M |
| FR-OMLS-002 | Odoo-specific semantic highlighting: field types (`fields.Char`), ORM decorators (`@api.depends`), magic attributes (`_name`, `_inherit`), QWeb directives (`t-if`, `t-foreach`, `t-esc`), XML view tags/attributes, domains and context strings. | M |
| FR-OMLS-003 | Embedded-language highlighting: Python expressions inside XML attributes (`domain`, `context`, `attrs`, `invisible`, `t-att-*`), inline `<style>`/`<script>`, and JS inside QWeb. | S |
| FR-OMLS-004 | Highlighting must be incremental and never block typing (files up to 5 MB stay fluid). | M |

#### 4.4.2 Autocomplete (Tab-accept)
| ID | Requirement | Pri |
|---|---|---|
| FR-OMLS-010 | Completion popup with `Tab`/`Enter` to accept, `Esc` to dismiss, `Ctrl+Space` to force, arrows to navigate, with documentation side-panel. | M |
| FR-OMLS-011 | **Python**: standard completion (jedi/LSP) plus Odoo context — `self.env['<model>']` model names, field names on `self`/recordsets, `fields.*` types and their parameters, `api.*` decorators, ORM methods (`search`, `browse`, `mapped`, `filtered`, `write`, `create`…), `comodel_name`, `related='partner_id.name'` path completion, `_inherit` targets. | M |
| FR-OMLS-012 | **XML**: tag/attribute completion for Odoo view architecture (`form`, `list`/`tree`, `kanban`, `search`, `graph`, `pivot`, `calendar`), `<field name="">` from the model resolved by the surrounding `model=`, `ref=`/`inherit_id=` XML IDs, `groups=`, `action`, `menuitem` attributes, `xpath expr/position` values. | M |
| FR-OMLS-013 | **QWeb / HTML**: `t-*` directive completion, template IDs for `t-call`, variables in scope. | S |
| FR-OMLS-014 | **JS/OWL**: Odoo module paths (`@web/...`, `@odoo-module`), registry names, OWL hooks. | S |
| FR-OMLS-015 | **CSV**: header autocompletion for `ir.model.access.csv` and data CSVs (model/group xml-id columns). | M |
| FR-OMLS-016 | **Manifest**: key completion (`name`, `depends`, `data`, `assets`…), module names for `depends`, file paths for `data`. | M |
| FR-OMLS-017 | **Snippet expansion** (`Tab` after trigger): e.g. `omodel`, `ofield`, `oform`, `otree`, `oxpath`, `ocompute`, `oonchange`, `oconstraint`; user-definable snippets. | M |
| FR-OMLS-018 | Completion ranking: current module/dependency modules prioritized; only models/fields from modules in the dependency closure of the current module are offered first. | S |

#### 4.4.3 Diagnostics (Syntax & Semantic Error Flags)
| ID | Requirement | Pri |
|---|---|---|
| FR-OMLS-020 | Real-time syntax errors for all languages, shown as underline/gutter marker and in a Problems panel. | M |
| FR-OMLS-021 | Odoo semantic checks (no server needed): unknown model in `_inherit`/`comodel_name`; unknown field in view; unknown/missing XML ID; view field not defined on model; `depends` referencing missing module; file listed in manifest but missing (and vice versa: data XML not listed in manifest); duplicate XML IDs; missing `ir.model.access` line for a model; import missing in `__init__.py`; XPath expression that doesn't match parent view (best effort). | M |
| FR-OMLS-022 | Manifest schema validation (required keys, valid `version` format, `installable`, `license`, `data` ordering hints such as security before views). | M |
| FR-OMLS-023 | Severity levels (error, warning, info, hint) with per-rule enable/disable in config. | M |
| FR-OMLS-024 | Quick Fixes (`Ctrl+.`): add missing import to `__init__.py`, add file to manifest `data`, add missing access rule, add missing dependency, fix deprecated attributes (`attrs` → direct expressions for Odoo 17+, `tree` → `list` for 18+). | S |
| FR-OMLS-025 | Deprecated-API warnings using per-version profiles. | S |

#### 4.4.4 Linter Integration
| ID | Requirement | Pri |
|---|---|---|
| FR-OMLS-030 | Run **`pylint-odoo`** on save / on demand (`--load-plugins=pylint_odoo`, `--valid-odoo-versions=<detected>`), parse output, and map to inline diagnostics. | M |
| FR-OMLS-031 | Optional runners: `ruff`, `flake8`, `black --check`, `prettier` (JS/XML), `xmllint`. | S |
| FR-OMLS-032 | Lint scopes: current file, current module, whole workspace; run headless/pre-restart ("**Lint before restart**" gate configurable to block or warn). | M |
| FR-OMLS-033 | Detect missing linter installation and offer one-key install hint into the correct virtualenv. | S |
| FR-OMLS-034 | Respect project config (`.pylintrc`, `.pre-commit-config.yaml`, `pyproject.toml`, `setup.cfg`). | S |
| FR-OMLS-035 | Formatting on save (optional): `black`/`ruff format` for Python, XML pretty-printer preserving Odoo style. | C |

---

### 4.5 Odoo Server System Engine (OSS)

#### 4.5.1 Lifecycle Control
| ID | Requirement | Pri |
|---|---|---|
| FR-OSS-001 | **Start** Odoo in the foreground-managed mode (ocode owns the child process) with configured binary, python, conf file, and flags. | M |
| FR-OSS-002 | **Stop** gracefully (`SIGINT`/`SIGTERM`), escalating to `SIGKILL` after a configurable timeout. | M |
| FR-OSS-003 | **Restart** (stop + start) with a single hotkey (`F5`). | M |
| FR-OSS-004 | **Restart with update**: `-u <module1,module2>` using selectable modules (current module preselected; option "current + dependents"). | M |
| FR-OSS-005 | **Install** modules (`-i`), and **update all** (`-u all`) with a confirmation prompt. | M |
| FR-OSS-006 | Support **two control modes**: (a) *Managed process* (spawned by ocode), (b) *systemd service* (`systemctl restart odoo`, needs sudo/polkit), (c) *Docker/compose* (optional). Mode is auto-detected and configurable. | M/S |
| FR-OSS-007 | One-shot update mode: run `odoo-bin -u mod --stop-after-init`, then start the normal server (avoids stale state). | S |
| FR-OSS-008 | Status indicator in status bar (Stopped / Starting / Running / Updating / Crashed) with PID, port, uptime, DB. | M |
| FR-OSS-009 | Auto-restart on file save (dev mode) and support `--dev=reload,qweb,xml,werkzeug` flags; optional "auto-update module on save of XML/CSV". | S |
| FR-OSS-010 | Detect and report failure causes (port in use, DB missing, Python traceback at startup, module load error) with jump-to-file-line links. | S |

#### 4.5.2 Odoo Flags & Server Settings
| ID | Requirement | Pri |
|---|---|---|
| FR-OSS-020 | **Server Profiles**: named launch configurations (e.g., `dev`, `test`, `debug`) storing conf path, DB, ports, flags, env vars, python path. | M |
| FR-OSS-021 | Flag editor UI with a **catalog of Odoo CLI flags** (grouped: *database, http, logging, dev, testing, workers, i18n, advanced*), descriptions, value types, per-version availability, and validation. | M |
| FR-OSS-022 | Support common flags out of the box: `-c`, `-d`, `-i`, `-u`, `--addons-path`, `--dev`, `--log-level`, `--log-handler`, `--logfile`, `--http-port`, `--longpolling-port`/`--gevent-port`, `--workers`, `--max-cron-threads`, `--limit-*`, `--test-enable`, `--test-tags`, `--stop-after-init`, `--without-demo`, `--load-language`, `-l`, `--db-filter`, `--data-dir`, `--save`. | M |
| FR-OSS-023 | Free-form "extra args" field and full command-line preview before launching. | M |
| FR-OSS-024 | Edit `odoo.conf` in a form UI (parse → edit → save with backup and comments preserved). | S |
| FR-OSS-025 | Environment variables and pre/post-launch hooks (e.g., activate venv, run migration script). | S |
| FR-OSS-026 | Database helpers: list/select DB, drop/duplicate/backup DB via `psql`/`odoo db` (with confirmation). | C |
| FR-OSS-027 | Run test workflows: `--test-enable -u module --test-tags /module` from hotkey, with a Test Results panel parsing pass/fail and linking to failing tests. | S |

#### 4.5.3 Live Log Streaming
| ID | Requirement | Pri |
|---|---|---|
| FR-OSS-030 | **Log panel** with split-view (bottom or right), resizable/collapsible/maximizable, showing the managed process's stdout/stderr in real time. | M |
| FR-OSS-031 | Tail external log files (`tail -f`-like on `logfile` from conf, e.g. `/var/log/odoo/odoo-server.log`) with rotation handling (`inode` change). | M |
| FR-OSS-032 | Log-level coloring (DEBUG/INFO/WARNING/ERROR/CRITICAL), highlighted timestamps, DB, logger name. | M |
| FR-OSS-033 | Filters: level, logger (`odoo.addons.my_module`), regex, module; pause/resume auto-scroll; clear; search inside logs; wrap toggle. | M |
| FR-OSS-034 | **Traceback detection**: Python tracebacks collapse into a single expandable block; clicking a `File "...", line N` opens that file at that line in the editor. | M |
| FR-OSS-035 | Ring-buffer with configurable max lines (default 20 000) and optional save to file. | M |
| FR-OSS-036 | Notification badge in status bar on new ERROR/WARNING lines. | S |
| FR-OSS-037 | Tail multiple logs in tabs (server, nginx, postgres, custom). | C |

---

### 4.6 Odoo Text Editor Engine (OTE)

The OTE is the core editing component. It must be built as a standalone, well-tested engine (`ocode.engines.ote`) that renders through a custom Textual widget (not the stock `TextArea`), to allow full control of performance and Odoo-specific features.

#### 4.6.1 Buffer & Data Model
| ID | Requirement | Pri |
|---|---|---|
| FR-OTE-001 | Text buffer implemented as a **piece table or rope** with O(log n) edits and cheap snapshots; handles files ≥ 50 MB in "large-file mode" (highlighting/analysis disabled). | M |
| FR-OTE-002 | Encoding detection & preservation (UTF-8 default, UTF-8 BOM, Latin-1, etc.); line-ending detection & preservation (LF/CRLF), with status-bar switchers. | M |
| FR-OTE-003 | Preserve trailing newline policy and file permissions on save; atomic saves (write temp + rename). | M |
| FR-OTE-004 | Multiple buffers can view the same document (split panes share state). | S |
| FR-OTE-005 | Read-only mode & permission-denied handling with "**Save as root**" (`sudo tee`) flow for `/etc/odoo.conf`, `/opt/odoo` files. | M |

#### 4.6.2 Cursor, Selection & Editing
| ID | Requirement | Pri |
|---|---|---|
| FR-OTE-010 | Standard navigation: arrows, `Home/End`, `Ctrl+←/→` word, `PgUp/PgDn`, `Ctrl+Home/End`, `Ctrl+G` go-to-line, smart Home (first non-blank toggle). | M |
| FR-OTE-011 | Selection by keyboard (`Shift+…`), mouse drag, double-click word, triple-click line, `Ctrl+A`, `Ctrl+L` select line, expand/shrink selection by syntax node (`Alt+Shift+↑/↓`). | M |
| FR-OTE-012 | **Multi-cursor**: add cursor by `Ctrl+D` (next occurrence), `Ctrl+Alt+↑/↓` (add above/below), mouse `Alt+Click`; select all occurrences. | M |
| FR-OTE-013 | Block/column selection. | S |
| FR-OTE-014 | Line operations: duplicate, delete, move up/down (`Alt+↑/↓`), join, sort lines, toggle comment (`Ctrl+/`, language aware incl. `<!-- -->` for XML), indent/outdent (`Tab`/`Shift+Tab` on selection). | M |
| FR-OTE-015 | Clipboard: cut/copy/paste with system clipboard integration (OSC 52 for SSH, `xclip`/`wl-clipboard` fallback), bracketed-paste support, internal clipboard ring. | M |
| FR-OTE-016 | Auto-indentation aware of language (Python blocks after `:`, XML nesting), tabs vs. spaces detection, configurable width (Odoo default: 4 spaces Python, 4 spaces XML/JS). | M |
| FR-OTE-017 | Auto-close and surround: brackets, quotes, XML tags (typing `<field` + `>` inserts `</field>` closing or self-close per rule), wrap selection in brackets/quotes/tag. | M |
| FR-OTE-018 | **XML linked tag rename** (rename open tag ↔ closing tag simultaneously). | S |
| FR-OTE-019 | Emmet-lite for XML/HTML (`div.class>span` expansion) and Odoo XML abbreviations (e.g., `f:name` → `<field name="name"/>`). | C |
| FR-OTE-020 | Trim trailing whitespace / ensure final newline on save (configurable). | M |
| FR-OTE-021 | Rename symbol within file / project (Python via jedi/rope, XML IDs via OKI with preview). | S |

#### 4.6.3 Undo/Redo & History
| ID | Requirement | Pri |
|---|---|---|
| FR-OTE-030 | Unlimited undo/redo with grouping by typing bursts / commands; multi-cursor edits undo atomically. | M |
| FR-OTE-031 | **Undo tree** (branching history) viewer. | C |
| FR-OTE-032 | Persistent undo across sessions (per file, hash-validated). | C |
| FR-OTE-033 | Local history: automatic snapshots on save, diff & restore UI. | S |

#### 4.6.4 View & Rendering
| ID | Requirement | Pri |
|---|---|---|
| FR-OTE-040 | Line numbers (absolute/relative), current-line highlight, indent guides, whitespace rendering (toggle), rulers (e.g., col 79/120), scroll-past-end option. | M |
| FR-OTE-041 | Gutter with diagnostics icons, git diff markers, breakpoints marks (future), fold markers. | M |
| FR-OTE-042 | Soft wrap toggle (word/column) with correct cursor movement across visual lines. | M |
| FR-OTE-043 | **Code folding** based on syntax tree (classes, methods, XML elements, `<record>`, `<template>`), fold all/unfold all, fold level N. | M |
| FR-OTE-044 | Bracket/tag matching highlight and jump to matching bracket (`Ctrl+M`); XML tag pair highlight. | M |
| FR-OTE-045 | Occurrence highlighting of the word/symbol under the cursor; search matches highlighting. | M |
| FR-OTE-046 | Sticky scroll (current class/def/record header pinned at top). | C |
| FR-OTE-047 | Minimap/scroll bar with diagnostic and search markers (vertical scroll bar with markers at minimum). | S |
| FR-OTE-048 | Unicode-correct rendering: wide chars (CJK, emoji), combining marks, RTL text awareness (Arabic — Odoo has large Arabic-speaking user base; ensure `.po` Arabic strings remain editable and cursor movement is correct). | S |
| FR-OTE-049 | Truecolor/256-color/16-color fallback; theme system (`dark`, `light`, `high-contrast`, Odoo-purple) with user themes in TOML/TCSS. | M |

#### 4.6.5 Layout: Tabs, Splits, Panes
| ID | Requirement | Pri |
|---|---|---|
| FR-OTE-050 | Split editor horizontally/vertically (side-by-side related files like model ↔ view), each pane with its own tab group. | M |
| FR-OTE-051 | **Peek definition** inline popup (`Alt+F12`) for models, fields, XML IDs. | S |
| FR-OTE-052 | Diff editor: compare file with saved/git HEAD/another file, side-by-side and unified. | S |
| FR-OTE-053 | Zen/focus mode (hide all panels). | C |

#### 4.6.6 Find & Replace (in file)
| ID | Requirement | Pri |
|---|---|---|
| FR-OTE-060 | Incremental find (`Ctrl+F`) with regex / case / whole word toggles, match counter, next/prev; replace/replace all (`Ctrl+H`). | M |
| FR-OTE-061 | Find in selection; preserve case on replace; multi-line regex. | S |
| FR-OTE-062 | Regex-capture replacement preview. | C |

#### 4.6.7 File Handling & Safety
| ID | Requirement | Pri |
|---|---|---|
| FR-OTE-070 | Dirty-state tracking; prompt on close/quit with *Save / Discard / Cancel*. | M |
| FR-OTE-071 | **Auto-save** options (off / on focus change / after delay). | S |
| FR-OTE-072 | **Swap/backup files** and crash recovery (SES engine) — reopening after a crash/SSH disconnect offers recovery. | M |
| FR-OTE-073 | External change detection (file modified on disk / by git / by another process): reload prompt or auto-reload if not dirty. | M |
| FR-OTE-074 | File locking hints (warn if another ocode instance has the file open). | C |
| FR-OTE-075 | Binary/unsupported file guard (image/PDF/`.pyc`); hex-preview optional. | S |
| FR-OTE-076 | `.editorconfig` support. | S |

#### 4.6.8 Odoo-Specific Editor Features
| ID | Requirement | Pri |
|---|---|---|
| FR-OTE-080 | **Hover info** (`Ctrl+K Ctrl+I`): field definition (type, string, required, comodel), model summary, XML ID target, method docstring, Odoo config key help. | M |
| FR-OTE-081 | **CodeLens-style hints** (inline, toggleable): "N views use this model", "N overrides", "N references". | C |
| FR-OTE-082 | Outline/Symbol panel: classes, fields, methods (Python); records, templates, views, menus (XML). | M |
| FR-OTE-083 | Inline "domain" and "context" validity hints. | C |
| FR-OTE-084 | Translation helper: highlight untranslated `_()` strings and jump to `.po`; export `.pot` via server command. | C |
| FR-OTE-085 | "Extract to method / field / view" refactor helpers. | C |

---

### 4.7 Boilerplate Generators (OSG)

| ID | Requirement | Pri |
|---|---|---|
| FR-OSG-001 | **New Module wizard**: name, technical name, version (auto from detected Odoo), depends, category, license, author, website → creates folder tree (`__init__.py`, `__manifest__.py`, `models/`, `views/`, `security/`, `data/`, `static/description/icon.png`, `tests/`, `i18n/`, `controllers/`, `wizard/`, `report/`). | M |
| FR-OSG-002 | **Model scaffold**: form-driven (`_name`, `_description`, `_inherit`/`_inherits`, `_order`, `_rec_name`, mixins like `mail.thread`, `mail.activity.mixin`, fields table with type/string/required/default/help/relations, computed/related options). Creates `models/<name>.py`, updates `models/__init__.py`. | M |
| FR-OSG-003 | **Inherited model scaffold**: pick an existing model via OKI → generate extension class with selected fields/method overrides using correct `super()` calls. | M |
| FR-OSG-004 | **View scaffold** (`form`, `list/tree`, `kanban`, `search`, `pivot`, `graph`, `calendar`, `activity`, `gantt`*): fields taken from the model definition; generates `ir.ui.view` record, `ir.actions.act_window`, `menuitem`. Updates manifest `data`. | M |
| FR-OSG-005 | **XPath view inheritance scaffold**: pick parent view (by XML ID via OKI), pick an anchor (field/group/page) via list, choose position (`before/after/inside/replace/attributes`) → generates `<record>` with correct `inherit_id` and `xpath`. | M |
| FR-OSG-006 | **Access rights automation**: on model creation, add/update lines in `security/ir.model.access.csv` (create file with header if missing; standard `access_<model>_user/manager` lines; group selector); idempotent updates, no duplicates, preserving custom lines; add file to manifest. | M |
| FR-OSG-007 | **Record rules** scaffold (`ir.rule`) and security groups (`res.groups`, category). | S |
| FR-OSG-008 | Additional scaffolds: wizard (TransientModel + view + action), QWeb report (`ir.actions.report` + template), controller (`http.route`), cron job (`ir.cron`), server action, sequence, data/demo XML, mail template, JS/OWL component, tests (`TransactionCase`), migration script (`pre-/post-migrate`), website snippet. | S |
| FR-OSG-009 | **Live preview & diff** of each generated change before applying (never silently overwrite). | M |
| FR-OSG-010 | Templates are **Jinja2**, version-aware (Odoo 14–18 differences), and user-overridable from `~/.config/ocode/templates/`. | M |
| FR-OSG-011 | Naming helpers: derive `_name`, class name, file names, XML IDs, menu names from a single input following OCA/Odoo guidelines. | M |
| FR-OSG-012 | Insert-at-cursor snippets (fields, methods, decorators) separate from file generators. | M |
| FR-OSG-013 | All generators reachable from context menu (right-click / `Ctrl+Shift+N`) and command palette. | M |

---

### 4.8 Interactive Odoo Shell (OSH)

| ID | Requirement | Pri |
|---|---|---|
| FR-OSH-001 | Embedded terminal panel running `odoo-bin shell -d <db> -c <conf>` (PTY-backed, full color, resize aware), with `env`, `self`, `cr` available. | M |
| FR-OSH-002 | Panel is toggleable (`Ctrl+\``), can coexist with log panel as a tab, and survives closing/reopening. | M |
| FR-OSH-003 | **Send to shell**: run selected code / current line / current file / current method in the shell (`Ctrl+Enter`). | M |
| FR-OSH-004 | Smart shell helpers: auto-inject `env.ref`, `self = env['model']` from the current file's model, shortcut to reload module code (`importlib.reload`). | S |
| FR-OSH-005 | Support `--shell-interface=ipython/ptpython/bpython` when available. | S |
| FR-OSH-006 | Safety: banner showing DB name and a warning color when DB looks like production (configurable patterns); explicit `env.cr.commit()` reminder — shell sessions default to rollback-on-exit (`--dev` behavior) unless user disables. | M |
| FR-OSH-007 | Multiple concurrent shells (different DBs). | C |
| FR-OSH-008 | Shell history persisted per DB. | S |

---

### 4.9 Odoo Knowledge Index (OKI)

| ID | Requirement | Pri |
|---|---|---|
| FR-OKI-001 | Background static indexer parses Python (`ast`) and XML/CSV to build an SQLite index of: modules & dependency graph, models (`_name`, `_inherit`, `_inherits`), fields (type, params, comodel), methods (with decorators), XML IDs (records, templates, menus, actions, groups, rules), view architectures & inheritance chains, security ACLs. | M |
| FR-OKI-002 | **Model resolution**: compute the final merged model (all `_inherit` extensions across modules in dependency order). | M |
| FR-OKI-003 | Incremental updates on file change (file-hash based) and on `git checkout`; full rebuild via `ocode index`. | M |
| FR-OKI-004 | Initial indexing of Odoo core + Enterprise + custom addons must show progress; the editor is usable immediately (partial results). Target: ≤ 60 s cold for core + 100 custom modules on a 4-core VM; ≤ 200 ms for incremental updates. | M |
| FR-OKI-005 | Optional **live-DB enrichment**: query the DB (`ir.model`, `ir.model.fields`, `ir.ui.view`, `ir.model.data`, `ir.module.module`) for installed state, custom Studio fields, and actual view arch. Read-only, opt-in. | C |
| FR-OKI-006 | Index cache stored in `~/.cache/ocode/index/<workspace-hash>.sqlite`; safe to delete. | M |
| FR-OKI-007 | Public query API used by SMN, OMLS, OSG; must be stable and documented for plugins. | S |

---

### 4.10 Git Integration (GIT)

| ID | Requirement | Pri |
|---|---|---|
| FR-GIT-001 | Show branch name and dirty state in the status bar. | S |
| FR-GIT-002 | Diff gutter (added/modified/removed lines) in the editor. | S |
| FR-GIT-003 | Stage/unstage/commit panel, view diff, discard hunk. | C |
| FR-GIT-004 | Blame for the current line (inline, toggle). | C |
| FR-GIT-005 | Works when the addons directory is a submodule/separate repo (multi-repo aware). | S |

---

### 4.11 Command Palette, Keymap & Settings (CMD / CFG)

| ID | Requirement | Pri |
|---|---|---|
| FR-CMD-001 | Command palette (`Ctrl+Shift+P`) with fuzzy search over every registered command, showing bound key. | M |
| FR-CMD-002 | All commands have stable IDs (`ocode.file.save`, `ocode.oss.restart`) usable in keymap and future scripting. | M |
| FR-CFG-001 | Config hierarchy: **defaults → user (`~/.config/ocode/config.toml`) → workspace (`.ocode/config.toml`)**. | M |
| FR-CFG-002 | Keymap file (`keymap.toml`), with presets: *Default*, *VS Code-like*, *Vim* (modal, `Could`), *Emacs-lite*. | M/C |
| FR-CFG-003 | Settings UI screen for common options (searchable), writing to TOML. | S |
| FR-CFG-004 | Live reload of config without restarting. | S |
| FR-CFG-005 | Keybinding conflict detector and terminal-compat check (`ocode doctor keys` shows which key combos the current terminal delivers). | S |

---

### 4.12 Session & Recovery (SES)

| ID | Requirement | Pri |
|---|---|---|
| FR-SES-001 | Restore open files, cursor positions, folds, layout, panel visibility, active server profile per workspace. | M |
| FR-SES-002 | Detached-safe: on SSH disconnect/SIGHUP, dirty buffers are written to swap files before exit. | M |
| FR-SES-003 | Optional `tmux`/`screen`-friendly behavior (no reliance on unusual escape sequences; graceful degradation). | S |

---

## 5. User Interface Specification

### 5.1 Default Layout

```
┌ ocode ─ [odoo17] my_addons › sale_custom › models › sale_order.py ────────────────┐
│ ▸ EXPLORER  [Files|Modules] │ sale_order.py ● │ sale_order_views.xml │ __manif… │
│ ▾ sale_custom               │  1  from odoo import models, fields, api          │
│   ▸ models                  │  2                                                │
│   ▸ views                   │  3  class SaleOrder(models.Model):                │
│   ▸ security                │  4      _inherit = 'sale.order'                   │
│   __manifest__.py           │  5      x_ref = fields.Char()   ⚠ unused field    │
│ ▸ OUTLINE                   │                                                   │
├─────────────────────────────┴───────────────────────────────────────────────────┤
│ [Logs] [Shell] [Problems] [Search] [Tests]                                      │
│ 2026-09-29 10:21:03 INFO mydb odoo.modules.loading: 12 modules loaded           │
├─────────────────────────────────────────────────────────────────────────────────┤
│ ● Running :8069 │ db: mydb │ 17.0 │ main ✱ │ Py │ UTF-8 │ LF │ Ln 5, Col 12    │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 UI Requirements
| ID | Requirement | Pri |
|---|---|---|
| UI-001 | Panels (Explorer, Editor groups, Bottom panel, Right panel) are resizable by mouse and keyboard, toggleable, and remembered. | M |
| UI-002 | Mouse support everywhere (click, drag, scroll, right-click context menus); everything is also fully keyboard-operable. | M |
| UI-003 | Modal dialogs/wizards use consistent Textual screens with focus trapping and `Esc` to cancel. | M |
| UI-004 | Minimum supported terminal: 80×24 (degraded layout: auto-hides sidebar); recommended ≥ 120×35. | M |
| UI-005 | Themes styled with Textual CSS (`.tcss`); high-contrast and color-blind-friendly themes. | S |
| UI-006 | Non-blocking notifications (toasts) and a notification center. | S |
| UI-007 | Nerd-Font icons with ASCII fallback (`--ascii`). | S |
| UI-008 | Built-in help screen (`F1`) and keybinding cheat-sheet overlay (`Ctrl+K Ctrl+S`). | M |

### 5.3 Default Keybindings (initial proposal)

| Action | Key | Fallback |
|---|---|---|
| Command palette | `Ctrl+Shift+P` | `F1` |
| Quick open file | `Ctrl+P` | |
| Switch module | `Ctrl+Shift+M` | |
| Jump to related file (cycle) | `Alt+M` | `Ctrl+K M` |
| Related files popup | `Alt+R` | `Ctrl+K R` |
| Go to definition | `F12` / `Ctrl+Click` | |
| Peek definition | `Alt+F12` | |
| Find references | `Shift+F12` | |
| Search in files | `Ctrl+Shift+F` | |
| Toggle sidebar | `Ctrl+B` | |
| Toggle bottom panel | `Ctrl+J` | |
| Toggle Odoo shell | ``Ctrl+` `` | |
| Server: start/stop | `F6` | |
| Server: restart | `F5` | |
| Server: restart + update current module | `Ctrl+F5` | |
| Server: update module (choose) | `Ctrl+Shift+F5` | |
| Lint current file / module | `F8` / `Ctrl+F8` | |
| Next/previous problem | `F4` / `Shift+F4` | |
| Generate (new model/view/…) | `Ctrl+Shift+N` | |
| Save / Save all | `Ctrl+S` / `Ctrl+K S` | |
| Quit | `Ctrl+Q` | |

> **Note:** Some terminals cannot distinguish certain combinations (e.g., `Ctrl+Shift+*`, `Ctrl+Enter`). Every command must have an alternative binding, and `ocode doctor keys` must report what is supported. Use the Kitty keyboard protocol where available.

---

## 6. Non-Functional Requirements

### 6.1 Performance
| ID | Requirement |
|---|---|
| NFR-PERF-001 | Cold start to interactive UI ≤ 500 ms (without indexing), ≤ 1.5 s on a typical VPS (2 vCPU). |
| NFR-PERF-002 | Keystroke-to-render latency ≤ 30 ms for files up to 10k lines; ≤ 100 ms for 100k lines (large-file mode). |
| NFR-PERF-003 | Memory ≤ 150 MB idle with a mid-size workspace; ≤ 500 MB peak during full indexing. |
| NFR-PERF-004 | Log panel sustains ≥ 5 000 lines/s without UI freezes (batching, frame-rate limiting). |
| NFR-PERF-005 | Content search over Odoo core (~600 MB) returns first results ≤ 300 ms with ripgrep. |

### 6.2 Reliability & Safety
- Never lose user text: swap files, atomic saves, crash-safe session data.
- Never leave orphan Odoo processes: on exit ocode stops managed servers (configurable: *stop / keep running / ask*).
- Destructive actions (delete file, drop DB, update all) require confirmation.
- Editing files in Odoo core paths shows a warning banner (customary Odoo rule: don't modify core).
- No network calls by default; no telemetry unless explicitly opted in (must be documented if ever added).

### 6.3 Security
- Do not execute code from workspace files during analysis (static analysis only).
- Sudo/privileged actions go through explicit prompts; passwords are never stored or logged.
- Config files with secrets (`admin_passwd`, `db_password`) are masked in UI and logs by default.
- Subprocess invocations use argument lists (no shell injection), with quoting for user-provided flags.

### 6.4 Compatibility
- Ubuntu 22.04 (Python 3.10), 24.04 (Python 3.12), and later; x86_64 and arm64.
- Works in common terminals: GNOME Terminal, Konsole, Alacritty, Kitty, WezTerm, iTerm2 (bonus), Windows Terminal/WSL2, and inside `tmux`/`screen` and over SSH.
- Graceful degradation for 16-color terminals and no-mouse environments.

### 6.5 Accessibility & Internationalization
- UI strings extracted for translation (gettext); initial languages: English, Arabic (RTL-aware layout for menus is *Could*).
- High-contrast theme and no reliance on color alone for status.

### 6.6 Maintainability
- ≥ 80 % unit test coverage for engine cores (OTE buffer, OSG templates, OKI parsers); UI snapshot tests through Textual's `Pilot`/snapshot plugin.
- Strict typing (mypy) for `core/` and `engines/`.
- Semantic versioning; CHANGELOG; documented public engine APIs.

---

## 7. Configuration Files & Data Locations

| Purpose | Path |
|---|---|
| User config | `~/.config/ocode/config.toml` |
| Keymap | `~/.config/ocode/keymap.toml` |
| Themes | `~/.config/ocode/themes/*.toml` / `*.tcss` |
| User snippets / templates | `~/.config/ocode/snippets/`, `~/.config/ocode/templates/` |
| Workspace config | `<workspace>/.ocode/config.toml` (commit-friendly) |
| Server profiles | `<workspace>/.ocode/servers.toml` |
| Index cache | `~/.cache/ocode/index/` |
| Sessions & swap | `~/.local/state/ocode/` |
| Logs (ocode's own) | `~/.local/state/ocode/ocode.log` |

**Example `servers.toml`:**

```toml
[profile.dev]
odoo_bin   = "/opt/odoo17/odoo-bin"
python     = "/opt/odoo17/venv/bin/python"
conf       = "/etc/odoo17.conf"
db         = "mydb"
mode       = "managed"          # managed | systemd | docker
flags      = ["--dev=reload,qweb,xml", "--log-level=debug"]
env        = { PYTHONUNBUFFERED = "1" }
lint_before_restart = "warn"    # off | warn | block
```

---

## 8. Packaging & Distribution

### 8.1 PyPI (`pip`)
- Project name: `ocode` (verify availability; fallback `ocode-editor`, `odoo-ocode`).
- `pyproject.toml` with `[project.scripts] ocode = "ocode.__main__:main"`.
- Extras: `ocode[lint]` (pylint-odoo, ruff), `ocode[lsp]`, `ocode[all]`.
- Prebuilt wheels dependency on `tree-sitter` grammar wheels; pure-Python wheel for ocode itself.
- Recommended install: `pipx install ocode`; supports `python -m ocode`.
- Reproducible builds, signed releases (Trusted Publishing through GitHub Actions), `twine check` in CI.

### 8.2 APT (`.deb`)
- Package name `ocode`; architecture `all` (pure Python) — or `amd64/arm64` if bundling native wheels.
- `debian/control`: `Depends: python3 (>= 3.10), python3-textual (>= X), python3-rich, python3-lxml, python3-jinja2, python3-watchfiles, python3-tree-sitter`, `Recommends: ripgrep, git, python3-pylint-odoo | pipx`, `Suggests: xclip | wl-clipboard`.
- Because some dependencies (e.g., recent `textual`, `pylint-odoo`) are not in Ubuntu repositories, choose one strategy (decision required, see Open Questions):
  1. **`dh-virtualenv`** — ship a private virtualenv in `/opt/ocode` with pinned wheels; symlink `/usr/bin/ocode`. *(recommended for reliability)*
  2. Package each missing dependency separately (high maintenance).
- Distribute through a **Launchpad PPA** (`ppa:<owner>/ocode`) and a signed self-hosted APT repository (`reprepro`/`aptly`) for CI-built releases (jammy, noble).
- Include man page (`ocode.1`), bash/zsh/fish completions, desktop-independent `.desktop` file *not required*, and `/etc/ocode/` optional system defaults.
- Debian policy compliance (`lintian` clean), `postinst` must not require network access.

### 8.3 CI/CD
- GitHub Actions: lint (ruff, mypy) → tests (matrix: Python 3.10–3.13, Ubuntu 22.04/24.04) → Textual snapshot tests → build wheel/sdist → build `.deb` in `sbuild`/Docker → publish on tag.
- Integration test job that spins up Odoo (Docker) + PostgreSQL to test OSS/OSH/OKI end-to-end.

---

## 9. Testing Strategy

| Level | Scope | Tools |
|---|---|---|
| Unit | OTE buffer/undo/multi-cursor, OSG templates, OKI parsers, config, flag catalog | `pytest`, `hypothesis` (property tests for buffer) |
| Component/UI | Screens, palette, panels, keybindings | Textual `Pilot`, snapshot tests |
| Integration | Real Odoo in Docker: start/stop/update, logs, shell, lint | `pytest` + Docker Compose |
| Fixtures | Sample Odoo addons repos (14–18), malformed manifests, huge files | |
| Performance | Benchmarks for keystroke latency, indexing time, log throughput | `pytest-benchmark` |
| Compatibility | Terminal emulator matrix (manual + `ocode doctor`) | |
| Packaging | Install `.deb` and wheel in clean containers (jammy/noble) | Docker, `lintian` |

**Definition of Done for any feature:** requirement ID referenced, tests added, docs updated, works with keyboard-only, no UI blocking > 50 ms, and included in the command palette.

---

## 10. Milestones & Roadmap

| Milestone | Scope | Outcome |
|---|---|---|
| **M0 – Foundations** (2–3 wks) | Repo, packaging skeleton, CI, Textual app shell, event bus, config, command registry, theme system | `pip install` gives an empty app shell |
| **M1 – Core Editor (OTE)** (5–6 wks) | Buffer, cursor/selection, undo, find/replace, tabs, splits, tree-sitter highlighting, save/recovery | Usable general-purpose editor |
| **M2 – Project Awareness (OPD + SMN)** (4 wks) | Odoo detection, module tree, quick open, content search, related-file jump (`Alt+M`), session restore | Odoo-aware navigation |
| **M3 – Server System (OSS)** (4 wks) | Managed/systemd modes, flags editor, profiles, log panel with tracebacks, update/restart hotkeys | Full run/update loop inside the editor |
| **M4 – Language Support (OKI + OMLS)** (6–8 wks) | Indexer, Odoo completion (py/xml/csv/manifest), diagnostics, `pylint-odoo` integration, quick fixes | Smart editing |
| **M5 – Generators & Shell (OSG + OSH)** (4 wks) | Model/view/xpath/security scaffolds, access CSV automation, embedded Odoo shell | Productivity features complete |
| **M6 – Polish & Release Candidate** (3 wks) | Performance tuning, docs, man page, `.deb` + PPA, terminal compatibility matrix | **v1.0.0-rc1** |
| **M7 – Post-1.0** | Git panel, plugin API, Vim keymap, DB tools, DAP debugger (`debugpy`), Docker mode, LSP client, AI-assist plug-in | Roadmap |

---

## 11. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Stock Textual `TextArea` too limited/slow for advanced editing | High | Custom editor widget on Textual's Line API + own buffer (OTE); prototype early with benchmarks |
| Terminal key-combo limitations (Alt/Ctrl+Shift) | Medium | Alternative chord bindings, Kitty protocol, `doctor keys`, remapping |
| Static analysis inaccuracies (dynamic Odoo patterns) | Medium | Best-effort with confidence levels; optional live-DB enrichment; allow silencing rules |
| Large Odoo code base indexing time | Medium | Incremental, parallel (multiprocessing), SQLite cache, partial availability |
| Odoo version divergence (14–18+) | Medium | Version profiles data-driven (`data/versions/*.toml`), CI fixtures per version |
| APT dependency freshness (Textual) | Medium | `dh-virtualenv` bundling approach |
| Managing privileged server control safely | Medium | Explicit prompts, polkit rules docs, managed-process default |
| Embedded PTY complexity (shell) | Medium | Use `pyte` + `ptyprocess`, extensive resize/color tests; fallback to line-based REPL |
| Scope creep | High | Strict MoSCoW; ship Musts for 1.0 |

---

## 12. Open Questions

1. **License:** LGPL-3.0 (Odoo-friendly) vs. MIT/Apache-2.0?
2. **Modal editing:** Is Vim-style keymap required for 1.0 or post-1.0?
3. **Analysis backend:** Bundle `jedi` (light) vs. optional `pyright`/LSP for Python intelligence?
4. **Live DB access:** Should OKI enrichment from a live database be in 1.0?
5. **Docker workflows:** Priority of Docker/compose control mode for 1.0?
6. **APT strategy:** `dh-virtualenv` bundle vs. per-dependency Debian packaging?
7. **Debugger:** Integrate `debugpy`/DAP in 1.x? (Odoo `--dev=pdb` may suffice initially.)
8. **Extensibility:** Public plugin API in 1.0 or after?
9. **Branding:** Confirm the name `ocode` is free on PyPI/PPA (possible collision with other tools).

---

## 13. Glossary

| Term | Meaning |
|---|---|
| **Addons path** | Directories Odoo scans for modules (`addons_path` in conf). |
| **Module** | Odoo package with `__manifest__.py`. |
| **XML ID** | External identifier `module.record_id` for records. |
| **QWeb** | Odoo's XML/HTML templating language. |
| **OWL** | Odoo Web Library — JS component framework (Odoo 14+ front-end). |
| **PTY** | Pseudo-terminal used to embed interactive programs. |
| **TUI** | Terminal User Interface. |
| **OSS/OMLS/SMN/OTE/OKI/OSG/OSH** | Engine codenames defined in §3.2. |

---

## 14. Acceptance Criteria for v1.0

1. `pip install ocode` and `apt install ocode` both produce a working `ocode` command on clean Ubuntu 22.04 and 24.04.
2. Opening any folder inside an Odoo installation auto-detects root, version, addons path, and modules with no configuration.
3. `Alt+M` (and fallback chord) cycles model ↔ view ↔ security ↔ manifest for a standard module.
4. Creating a model via the generator produces the Python file, `__init__` import, and access CSV lines, and registers everything in the manifest.
5. A developer can edit a module, press `Ctrl+F5`, watch logs stream, click a traceback to jump to the failing line, and open an Odoo shell in the same window.
6. `pylint-odoo` results appear inline as diagnostics for a module.
7. All **Must** requirements pass automated tests; no known data-loss bugs; performance targets in §6.1 are met on reference hardware.
