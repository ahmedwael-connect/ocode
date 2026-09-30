"""Textual app with M1 editor + M2 project awareness (tree, quick-open, related, grep, session)."""

from __future__ import annotations

from collections.abc import Coroutine
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Static

from ocode import __version__
from ocode.core.commands import CommandRegistry
from ocode.core.config import OcodeConfig
from ocode.core.events import EventBus
from ocode.core.tasks import TaskScheduler
from ocode.engines.oki.db import OkiDb, index_path_for
from ocode.engines.oki.indexer import Indexer
from ocode.engines.oki.query import OkiQuery
from ocode.engines.omls.complete import complete_at
from ocode.engines.omls.diagnostics import Diagnostic, FileCtx, analyze_file
from ocode.engines.omls.quickfix import apply_fix, available_fixes
from ocode.engines.omls.snippets import SNIPPETS, expand_snippet, render_snippet
from ocode.engines.opd.detector import OdooProject, detect_project
from ocode.engines.osg.applier import PlannedChange, apply_changes, preview_diff
from ocode.engines.osh.shell import ShellSession, is_production_db, shell_command
from ocode.engines.oss.manager import ServerManager
from ocode.engines.oss.profiles import ServerProfile, default_profile, load_profiles, save_profiles
from ocode.engines.ote.document import Document
from ocode.engines.ote.highlight import detect_language
from ocode.engines.ote.search import FindOptions
from ocode.engines.ote.session import SwapManager, swap_path_for
from ocode.engines.ote.state import EditorState
from ocode.engines.ote.tabs import TabState
from ocode.engines.ses import CursorPos, SessionData, SessionManager
from ocode.engines.smn.related import cycle_related, find_module_dir, key_file, related_files
from ocode.engines.smn.search import ContentHit
from ocode.ui.screens import FilterScreen, GrepScreen
from ocode.ui.screens.generate import (
    GENERATORS,
    AccessScreen,
    ControllerScreen,
    CronScreen,
    DiffScreen,
    GroupsScreen,
    InheritModelScreen,
    ModelScreen,
    NewModuleScreen,
    ReportScreen,
    TestScreen,
    ViewScreen,
    WizardScreen,
    XpathScreen,
)
from ocode.ui.screens.info import HelpScreen, HoverScreen
from ocode.ui.screens.server import ConfirmScreen, ServerSetupScreen, UpdateChooserScreen
from ocode.ui.widgets.complete import CompletionPopup
from ocode.ui.widgets.editor import EditorSaved, OcodeEditor
from ocode.ui.widgets.findbar import FindBar
from ocode.ui.widgets.logpanel import LogLinkClicked, LogPanel, level_badge
from ocode.ui.widgets.problems import ProblemChosen, ProblemsPanel
from ocode.ui.widgets.proj_tree import FilePicked, OdooTree
from ocode.ui.widgets.shell import ShellExited, ShellPanel


def build_default_commands() -> CommandRegistry:
    reg = CommandRegistry()
    reg.register("ocode.file.save", "File: Save", keybinding="ctrl+s")
    reg.register("ocode.file.saveAs", "File: Save As...")
    reg.register("ocode.edit.undo", "Undo", keybinding="ctrl+z")
    reg.register("ocode.edit.redo", "Redo", keybinding="ctrl+y")
    reg.register("ocode.edit.find", "Find in File", keybinding="ctrl+f")
    reg.register("ocode.edit.findNext", "Find Next", keybinding="f3")
    reg.register("ocode.edit.findPrev", "Find Previous", keybinding="shift+f3")
    reg.register("ocode.edit.replaceAll", "Replace All...", keybinding="ctrl+h")
    reg.register("ocode.edit.gotoLine", "Go to Line", keybinding="ctrl+g")
    reg.register("ocode.quickopen.open", "Go to File...", keybinding="ctrl+p")
    reg.register("ocode.module.jump", "Switch Module...", keybinding="ctrl+shift+m")
    reg.register("ocode.related.cycle", "Jump to Related File", keybinding="alt+m")
    reg.register("ocode.related.popup", "Related Files...", keybinding="alt+r")
    reg.register("ocode.search.workspace", "Search in Files...", keybinding="ctrl+shift+f")
    reg.register("ocode.palette.open", "Show Command Palette", keybinding="ctrl+shift+p")
    reg.register("ocode.sidebar.toggle", "Toggle Sidebar", keybinding="ctrl+b")
    reg.register("ocode.view.focusTree", "Focus File Tree", keybinding="ctrl+0")
    reg.register("ocode.view.focusEditor", "Focus Editor", keybinding="ctrl+1")
    reg.register("ocode.keyfile.manifest", "Open __manifest__.py")
    reg.register("ocode.keyfile.access", "Open access CSV")
    reg.register("ocode.keyfile.views", "Open main views XML")
    reg.register("ocode.oss.restart", "Odoo: Restart Server", keybinding="f5")
    reg.register("ocode.oss.toggle", "Odoo: Start/Stop Server", keybinding="f6")
    reg.register("ocode.oss.updateCurrent", "Odoo: Restart + Update Current", keybinding="ctrl+f5")
    reg.register("ocode.oss.updateChoose", "Odoo: Update Modules...", keybinding="ctrl+shift+f5")
    reg.register("ocode.oss.setup", "Odoo: Server Profiles & Flags...")
    reg.register("ocode.view.toggleLogs", "Toggle Log Panel", keybinding="ctrl+j")
    reg.register("ocode.log.clear", "Clear Logs")
    reg.register("ocode.complete.force", "Trigger Completion", keybinding="ctrl+space")
    reg.register("ocode.fix.quick", "Quick Fix...", keybinding="ctrl+.")
    reg.register("ocode.lint.file", "Lint Current File", keybinding="f8")
    reg.register("ocode.lint.module", "Lint Current Module", keybinding="ctrl+f8")
    reg.register("ocode.goto.definition", "Go to Definition", keybinding="f12")
    reg.register("ocode.goto.references", "Find References", keybinding="shift+f12")
    reg.register("ocode.hover.show", "Hover Info")
    reg.register("ocode.outline.show", "Outline/Symbols...", keybinding="ctrl+shift+o")
    reg.register("ocode.problem.next", "Next Problem", keybinding="f4")
    reg.register("ocode.problem.prev", "Previous Problem", keybinding="shift+f4")
    reg.register("ocode.generate.menu", "Generate...", keybinding="ctrl+shift+n")
    reg.register("ocode.shell.toggle", "Toggle Odoo Shell", keybinding="ctrl+`")
    reg.register("ocode.shell.stop", "Stop Odoo Shell")
    reg.register("ocode.shell.send", "Send to Shell", keybinding="ctrl+enter")
    reg.register("ocode.shell.injectSelf", "Shell: self = env[current model]")
    reg.register("ocode.snippet.insert", "Insert Snippet...")
    reg.register("ocode.app.quit", "Quit", keybinding="ctrl+q")
    return reg


class OcodeApp(App[None]):
    CSS_PATH = "ui/default.tcss"
    TITLE = "ocode"
    SUB_TITLE = f"Odoo-aware terminal editor v{__version__}"

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+b", "toggle_sidebar", "Sidebar"),
        ("ctrl+f", "toggle_find", "Find"),
        ("ctrl+h", "replace_all", "Replace"),
        ("ctrl+g", "goto_line", "Go to line"),
        ("ctrl+p", "quick_open", "Open"),
        ("ctrl+shift+m", "module_jump", "Module"),
        ("ctrl+shift+f", "grep", "Grep"),
        ("alt+m", "related_cycle", "Related"),
        ("alt+r", "related_popup", "Rel..."),
        ("ctrl+0", "focus_tree", "Tree"),
        ("ctrl+1", "focus_editor", "Edit"),
        ("ctrl+k", "chord", "Chord"),
        ("ctrl+j", "toggle_logs", "Logs"),
        ("f5", "server_restart", "Restart"),
        ("f6", "server_toggle", "Start/Stop"),
        ("ctrl+f5", "server_update_current", "UpdCur"),
        ("ctrl+shift+f5", "server_update_choose", "Update"),
        ("f8", "lint_file", "Lint"),
        ("ctrl+f8", "lint_module", "LintMod"),
        ("ctrl+.", "quick_fix", "Fix"),
        ("f12", "goto_definition", "Def"),
        ("shift+f12", "goto_references", "Refs"),
        ("f4", "problem_next", "NextErr"),
        ("shift+f4", "problem_prev", "PrevErr"),
        ("ctrl+shift+o", "show_outline", "Outline"),
        ("ctrl+shift+n", "generate_menu", "Generate"),
        ("ctrl+`", "shell_toggle", "Shell"),
        ("f7", "shell_toggle", "Shell"),
        ("ctrl+enter", "shell_send", "Send"),
        ("ctrl+shift+p", "show_palette", "Palette"),
        ("f3", "find_next", "Next"),
        ("shift+f3", "find_prev", "Prev"),
        ("f1", "show_help", "Help"),
    ]

    def __init__(
        self,
        start_path: Path | None = None,
        config: OcodeConfig | None = None,
        conf_override: str | Path | None = None,
        bin_override: str | Path | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.start_path = start_path or Path.cwd()
        self.ocode_config = config
        self.conf_override = conf_override
        self.bin_override = bin_override
        self.bus = EventBus()
        self.commands = build_default_commands()
        self.scheduler = TaskScheduler()
        self.tabs = TabState()
        self.docs: list[EditorState] = []
        self._swap: SwapManager | None = None
        self.project: OdooProject | None = None
        self._chord = False
        self._session: SessionManager | None = None
        self._recent: list[str] = []
        self.server: ServerManager | None = None
        self.server_profiles: dict[str, ServerProfile] = {}
        self.server_profile_name = "dev"
        self._last_error_badge = ""
        self.oki_db: OkiDb | None = None
        self.oki: OkiQuery | None = None
        self._index_progress: tuple[int, int] | None = None
        self.problems: list[Diagnostic] = []
        self._bottom_mode = "logs"  # hidden | logs | shell | problems
        self.shell: ShellSession | None = None
        self._ref_targets: dict[str, tuple[str, int]] = {}
        self._fix_map: dict[str, tuple[Diagnostic, str]] = {}
        self._outline_map: dict[str, int] = {}
        self._pending_changes: list[PlannedChange] = []
        self._log_refresh_pending = False

    # -- compose -------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield OdooTree(id="tree")
            with Vertical(id="editor-area"):
                yield Static("", id="breadcrumb")
                yield Static("", id="tabbar")
                yield OcodeEditor(EditorState(), id="editor")
                yield CompletionPopup(id="complete")
                yield Static("", id="bottomtabs")
                yield LogPanel(id="logs")
                yield ShellPanel(id="shell")
                yield ProblemsPanel(id="problems")
                yield FindBar(id="findbar")
        yield Static("", id="statusbar")
        yield Footer()

    def on_mount(self) -> None:
        target = self.start_path
        base = target if target.is_dir() else target.parent
        self.project = detect_project(base, self.conf_override, self.bin_override)
        if self.project.version:
            self.sub_title = f"odoo {self.project.version} · {base.name}"
        try:
            self.query_one("#tree", OdooTree).set_project(self.project)
        except Exception:
            pass
        ws = self.project.root or base
        self._session = SessionManager(ws)
        restored = self._restore_session()
        if not restored:
            if target.is_file():
                self.open_path(target)
            else:
                self.new_untitled()
        pending = SwapManager.pending()
        if pending:
            self.notify(f"{len(pending)} swap file(s) found — recovery available", timeout=5)
        self._init_server(ws)
        self._apply_bottom_mode()
        self._init_oki(ws)
        self.update_chrome()
        self.set_interval(5.0, self._autoswap)
        self.set_interval(1.0, self._poll_tailer)
        self.set_interval(0.15, self._poll_shell)
        self.query_one("#editor", OcodeEditor).focus()

    def on_unmount(self) -> None:
        self._save_session()
        if self.shell is not None:
            try:
                self.shell.stop()
            except OSError:
                pass
            self.shell = None
        if self.oki_db is not None:
            try:
                self.oki_db.close()
            except OSError:
                pass
            self.oki_db = None
        srv = self.server
        if srv is not None and srv.proc.running:
            try:
                import asyncio as _aio

                loop = _aio.get_event_loop()
                if loop.is_running():
                    loop.create_task(srv.stop())
            except (OSError, RuntimeError):
                pass

    # -- OKI index (FR-OKI-001..004, background, incremental) ------------
    def _init_oki(self, ws: Path) -> None:
        proj = self.project
        if not proj or not proj.modules:
            return
        try:
            db_path = index_path_for(ws)
        except OSError:
            return
        mods = list(proj.modules)
        self._index_progress = (0, len(mods))

        def _build() -> tuple[str, dict[str, int]]:
            db = OkiDb(db_path)
            try:
                stats = Indexer(db, mods).build(
                    progress=lambda i, n: self.call_from_thread(self._on_index_progress, i, n)
                )
                return (str(db_path), {"files": stats.files, "models": stats.models,
                                       "fields": stats.fields, "xmlids": stats.xmlids})
            finally:
                db.close()

        handle = self.scheduler.run_in_thread("oki-index", _build)
        # done-callbacks run in the app thread: call directly (no call_from_thread)
        handle.task.add_done_callback(lambda _t: self._on_index_done(str(db_path)))

    def _on_index_progress(self, i: int, total: int) -> None:
        self._index_progress = (i, total)
        self.update_chrome()

    def _on_index_done(self, db_path: str) -> None:
        self._index_progress = None
        try:
            self.oki_db = OkiDb(Path(db_path))
            self.oki = OkiQuery(self.oki_db)
        except OSError as exc:
            self.notify(f"Index unavailable: {exc}", severity="warning")
            return
        stats = self.oki.stats()
        self.notify(
            f"Indexed {stats.get('models', 0)} models, {stats.get('fields', 0)} fields",
            timeout=3,
        )
        self.refresh_diagnostics_for_active()
        self.update_chrome()

    def _file_ctx_for(self, path: Path) -> FileCtx:
        from ocode.engines.opd.module import read_manifest

        proj = self.project
        mod = find_module_dir(path, proj.modules) if proj else None
        manifest: dict[str, object] = {}
        files: list[str] = []
        if mod is not None:
            try:
                manifest = read_manifest(mod.manifest_path)
            except OSError:
                manifest = {}
            try:
                all_files = [p for p in mod.path.rglob("*") if p.is_file()][:2000]
                files = [str(p.relative_to(mod.path)) for p in all_files]
            except OSError:
                files = []
        version = proj.version if proj else None
        return FileCtx(path, mod, manifest, files, self.oki, version, {})

    def refresh_diagnostics_for_active(self) -> None:
        try:
            st = self.active_state()
        except Exception:
            return
        if st.doc.path is None:
            return
        try:
            text = st.doc.text
            ctx = self._file_ctx_for(st.doc.path)
            diags = analyze_file(text, ctx)
        except OSError:
            return
        # keep other files' diags, replace this file's
        self.problems = [d for d in self.problems if d.file != str(st.doc.path)] + diags
        try:
            self.query_one("#problems", ProblemsPanel).set_items(self.problems)
        except Exception:
            pass

    # -- server --------------------------------------------------------
    def _init_server(self, ws: Path) -> None:
        proj = self.project
        try:
            self.server_profiles = load_profiles(ws)
        except OSError:
            self.server_profiles = {}
        prof = self.server_profiles.get("dev")
        if prof is None:
            obin = str(proj.odoo_bin) if proj and proj.odoo_bin else ""
            conf = str(proj.conf.path) if proj and proj.conf and proj.conf.path else ""
            db = proj.conf.db_name if proj and proj.conf else ""
            python = ""
            if proj and proj.venv:
                for cand in (proj.venv / "bin" / "python", proj.venv / "bin" / "python3"):
                    if cand.exists():
                        python = str(cand)
                        break
            if self.conf_override:
                conf = str(self.conf_override)
            if self.bin_override:
                obin = str(self.bin_override)
            prof = default_profile(odoo_bin=obin, python=python, conf=conf, db=db)
            if proj and proj.version == "16.0":
                prof.flags = [f for f in prof.flags if "gevent" not in f]
        self.server_profiles.setdefault("dev", prof)
        self.server = ServerManager(prof)
        try:
            panel = self.query_one("#logs", LogPanel)
            panel.buffer = self.server.logs
        except Exception:
            pass
        self.server.on_log(lambda _rec: self._on_server_log())
        self.server.on_status(lambda _s: self.update_chrome())

    def _on_server_log(self) -> None:
        # coalesce bursts (NFR-PERF-004: sustain 5k lines/s without UI stalls)
        if self._log_refresh_pending:
            return
        self._log_refresh_pending = True
        self.set_timer(0.1, self._flush_log_refresh)

    def _flush_log_refresh(self) -> None:
        self._log_refresh_pending = False
        try:
            panel = self.query_one("#logs", LogPanel)
        except Exception:
            return
        panel.refresh(layout=True)
        badge = level_badge(panel.buffer)
        if badge != self._last_error_badge:
            self._last_error_badge = badge
            self.update_chrome()

    def _poll_tailer(self) -> None:
        srv = self.server
        if srv is None:
            return
        try:
            if srv.poll_tailer():
                self._on_server_log()
        except OSError:
            pass

    def _server_status_text(self) -> str:
        srv = self.server
        if srv is None:
            return "Stopped"
        snap = srv.snapshot()
        if snap.status == "Running" and snap.pid:
            uptime = _fmt_uptime(snap.uptime)
            return f"● Running :{snap.port} (pid {snap.pid}, up {uptime})"
        return snap.status

    def current_module_name(self) -> str | None:
        try:
            st = self.active_state()
            if st.doc.path is None or not self.project:
                return None
            mod = find_module_dir(st.doc.path, self.project.modules)
            return mod.name if mod else None
        except Exception:
            return None

    def _resolve_log_link(self, raw: str) -> Path | None:
        p = Path(raw)
        if p.is_absolute() and p.is_file():
            return p
        proj = self.project
        if proj is None:
            return None
        suffix = Path(raw)
        parts = suffix.parts[-3:]
        cands: list[Path] = []
        if proj.root:
            cands.append(proj.root.joinpath(*parts))
        for ap in proj.addons_paths:
            cands.append(ap.joinpath(*parts))
        for c in cands:
            try:
                if c.is_file():
                    return c
            except OSError:
                continue
        # fallback: match by filename under modules
        for m in proj.modules:
            try:
                for f in m.path.rglob(suffix.name):
                    if f.is_file():
                        return f
            except OSError:
                continue
        return None

    async def on_log_link_clicked(self, event: LogLinkClicked) -> None:
        target = self._resolve_log_link(event.path)
        if target is None:
            self.notify(f"File not found: {event.path}", severity="warning")
            return
        self.open_path(target, event.line)
        self.query_one("#editor", OcodeEditor).focus()

    # -- tabs / docs ---------------------------------------------------
    def new_untitled(self) -> None:
        self.tabs.open(None)
        self.docs.append(EditorState(Document()))
        self._bind_swap(None)
        self._show_active()

    def open_path(self, path: Path, line: int | None = None) -> None:
        idx = self.tabs.open(path)
        if idx < len(self.docs) and self.docs and self.tabs.tabs[idx] == path:
            if idx < len(self.docs):
                self._show_active()
                if line:
                    self.active_state().goto_line(line)
                    self.query_one("#editor", OcodeEditor).refresh()
                    self.update_chrome()
                return
        try:
            state = EditorState(Document.from_file(path))
        except OSError as exc:
            self.notify(f"Cannot open {path}: {exc}", severity="error")
            return
        if line:
            state.goto_line(line)
        if len(self.docs) == 1 and self.docs[0].doc.path is None and not self.docs[0].doc.dirty:
            self.docs[0] = state
        else:
            while len(self.docs) < len(self.tabs.tabs) - 1:
                self.docs.append(EditorState(Document()))
            if idx < len(self.docs):
                self.docs[idx] = state
            else:
                self.docs.append(state)
        self._bind_swap(path)
        editor = self.query_one("#editor", OcodeEditor)
        editor.state = self.active_state()
        editor._lang = detect_language(path)
        sp = str(path)
        if sp in self._recent:
            self._recent.remove(sp)
        self._recent.insert(0, sp)
        self._recent = self._recent[:30]
        self._show_active()

    def open_hit(self, hit: ContentHit) -> None:
        self.open_path(hit.path, hit.line)

    def active_state(self) -> EditorState:
        if not self.docs:
            self.docs.append(EditorState(Document()))
        i = max(0, min(self.tabs.active, len(self.docs) - 1))
        return self.docs[i]

    def _bind_swap(self, path: Path | None) -> None:
        self._swap = SwapManager(swap_path_for(path))

    def _show_active(self) -> None:
        try:
            editor = self.query_one("#editor", OcodeEditor)
        except Exception:
            return
        editor.state = self.active_state()
        editor.refresh()
        self.update_chrome()

    def _autoswap(self) -> None:
        try:
            st = self.active_state()
        except Exception:
            return
        if st.doc.dirty and self._swap is not None:
            try:
                self._swap.write(st.doc.text)
            except OSError:
                pass

    # -- session -------------------------------------------------------
    def _restore_session(self) -> bool:
        if self._session is None:
            return False
        data = self._session.load()
        if not data or not data.tabs:
            return False
        ok = False
        for t in data.tabs[:20]:
            if t is None:
                self.new_untitled()
                ok = True
            else:
                p = Path(t)
                if p.is_file():
                    self.open_path(p)
                    cur = data.cursors.get(t)
                    if cur is not None:
                        from ocode.engines.ote.cursor import Position

                        self.active_state().set_cursor(Position(cur.line, cur.col))
                    ok = True
        try:
            self.tabs.activate(min(data.active, len(self.tabs.tabs) - 1))
            self._show_active()
            if not data.sidebar_visible:
                self.query_one("#sidebar").display = False
        except Exception:
            pass
        return ok

    def _save_session(self) -> None:
        if self._session is None:
            return
        tabs: list[str | None] = []
        cursors: dict[str, CursorPos] = {}
        for i, t in enumerate(self.tabs.tabs):
            tabs.append(str(t) if isinstance(t, Path) else None)
            if isinstance(t, Path) and i < len(self.docs):
                c = self.docs[i].cursor if hasattr(self.docs[i], "cursor") else None
                if c is not None:
                    cursors[str(t)] = CursorPos(c.line, c.col)
        try:
            sidebar_vis = bool(self.query_one("#sidebar").display)
        except Exception:
            sidebar_vis = True
        self._session.save(
            SessionData(
                tabs=tabs, active=self.tabs.active, cursors=cursors, sidebar_visible=sidebar_vis
            )
        )

    # -- chrome --------------------------------------------------------
    def breadcrumb(self) -> str:
        st = self.active_state()
        path = st.doc.path
        if path is None or self.project is None:
            return str(path) if path else "untitled"
        mod = find_module_dir(path, self.project.modules)
        if self.project.root:
            try:
                rel = path.relative_to(self.project.root)
            except ValueError:
                rel = Path(path.name)
        else:
            rel = Path(path.name)
        parts = list(rel.parts)
        if mod is not None:
            return f"{mod.name} › {' › '.join(parts[-3:])}"
        return " › ".join(parts[-4:])

    def update_chrome(self) -> None:
        try:
            tabbar = self.query_one("#tabbar", Static)
            status = self.query_one("#statusbar", Static)
            editor = self.query_one("#editor", OcodeEditor)
            crumb = self.query_one("#breadcrumb", Static)
        except Exception:
            return
        names: list[str] = []
        for i, t in enumerate(self.tabs.tabs):
            name = t.name if isinstance(t, Path) else "untitled"
            dot = " ●" if (i < len(self.docs) and self.docs[i].doc.dirty) else ""
            marker = f"[{name}{dot}]" if i == self.tabs.active else f" {name}{dot} "
            names.append(marker)
        tabbar.update(" ".join(names) if names else " no files ")
        try:
            crumb.update(self.breadcrumb())
        except Exception:
            pass
        st = editor.state
        pos = st.cursor
        lang = detect_language(st.doc.path) if st.doc.path else "text"
        enc = st.doc.encoding.upper()
        eol = "CRLF" if st.doc.newline == "\r\n" else "LF"
        dot2 = "●" if st.doc.dirty else "○"
        fname = st.doc.path.name if st.doc.path else "untitled"
        nmatch = ""
        if st.matches:
            nmatch = f" | {st.match_index + 1}/{len(st.matches)} matches"
        loc = f"Ln {pos.line + 1}, Col {pos.col + 1}"
        odoo = ""
        if self.project is not None and self.project.found:
            conf = self.project.conf
            db = conf.db_name if conf and conf.db_name else "—"
            odoo = f" | odoo {self.project.version or '?'} | db: {db}"
        srv_txt = f" | {self._server_status_text()}"
        badge = f" | {self._last_error_badge}" if self._last_error_badge else ""
        idx_txt = ""
        if self._index_progress is not None:
            i, n = self._index_progress
            idx_txt = f" | indexing {i}/{n}"
        prob_txt = ""
        if self.problems:
            errs = sum(1 for d in self.problems if d.severity == "error")
            warns = sum(1 for d in self.problems if d.severity == "warning")
            prob_txt = f" | E:{errs} W:{warns}"
        segs = [f"{dot2} {fname}", lang, enc, eol, loc]
        if nmatch:
            segs.append(nmatch.strip(" |"))
        tail = f"{odoo}{srv_txt}{badge}{idx_txt}{prob_txt}"
        status.update(" | ".join(segs) + tail)
        self._update_bottom_tabs()

    def _apply_bottom_mode(self) -> None:
        try:
            logs = self.query_one("#logs", LogPanel)
            probs = self.query_one("#problems", ProblemsPanel)
            shell = self.query_one("#shell", ShellPanel)
        except Exception:
            return
        logs.display = self._bottom_mode == "logs"
        probs.display = self._bottom_mode == "problems"
        shell.display = self._bottom_mode == "shell"
        self._update_bottom_tabs()

    def _update_bottom_tabs(self) -> None:
        try:
            tabs = self.query_one("#bottomtabs", Static)
        except Exception:
            return
        errs = sum(1 for d in self.problems if d.severity == "error")
        logs_label = "[Logs]" if self._bottom_mode == "logs" else " Logs "
        shell_label = "[Shell]" if self._bottom_mode == "shell" else " Shell "
        if self._bottom_mode == "problems":
            probs_label = f"[Problems:{errs}]"
        else:
            probs_label = f" Problems:{errs} "
        toggle = "Ctrl+J cycles"
        tabs.update(f"{logs_label} {shell_label} {probs_label} ({toggle})")

    async def on_key(self, event: events.Key) -> None:
        if self._chord:
            self._chord = False
            if event.key in ("m", "M"):
                event.prevent_default()
                event.stop()
                self.action_related_cycle()
                return
            if event.key in ("r", "R"):
                event.prevent_default()
                event.stop()
                self.action_related_popup()
                return
            if event.key in ("i", "I"):
                event.prevent_default()
                event.stop()
                self.action_show_hover()
                return
        if event.key in ("f3", "shift+f3"):
            return
        self.set_timer(0.05, self.update_chrome)

    async def on_file_picked(self, event: FilePicked) -> None:
        self.open_path(event.path)
        self.query_one("#editor", OcodeEditor).focus()

    # -- actions -------------------------------------------------------
    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar")
        sidebar.display = not sidebar.display
        self._save_session()

    def action_show_palette(self) -> None:
        self.notify("Command palette lands post-M2 (FR-CMD-001)", timeout=3)

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen(), lambda _x: None)

    def action_focus_tree(self) -> None:
        self.query_one("#tree", OdooTree).focus()

    def action_focus_editor(self) -> None:
        self.query_one("#editor", OcodeEditor).focus()

    def action_chord(self) -> None:
        self._chord = True
        self.notify("Ctrl+K … press M (related) or R (popup)", timeout=2)

    def _file_candidates(self) -> tuple[list[str], Path]:
        proj = self.project
        base = (proj.root or self.start_path) if proj else self.start_path
        if base.is_file():
            base = base.parent

        def _rel(f: Path) -> str:
            try:
                return str(f.relative_to(base))
            except ValueError:
                return str(f)

        cands: list[str] = []
        if proj and proj.modules:
            for m in proj.modules:
                for folder in ("models", "views", "security", "data", "controllers", "tests"):
                    d = m.path / folder
                    if d.is_dir():
                        try:
                            for f in d.rglob("*"):
                                if f.is_file() and len(cands) < 5000:
                                    cands.append(_rel(f))
                        except OSError:
                            continue
                for key in ("__manifest__.py", "__init__.py"):
                    k = m.path / key
                    if k.is_file():
                        cands.append(_rel(k))
        else:
            from ocode.engines.smn.model import iter_files

            for f in iter_files(base)[:5000]:
                try:
                    cands.append(str(f.relative_to(base)))
                except ValueError:
                    cands.append(str(f))
        return (sorted(set(cands)), base)

    def action_quick_open(self) -> None:
        cands, base = self._file_candidates()
        cur_mod: str | None = None
        try:
            st = self.active_state()
            if st.doc.path and self.project:
                mod = find_module_dir(st.doc.path, self.project.modules)
                cur_mod = mod.name if mod else None
        except Exception:
            cur_mod = None
        _ = cur_mod
        title = "Quick Open (Ctrl+P) - ext:py,xml filter supported"
        self.push_screen(FilterScreen(title, cands, base), self._on_pick)

    def _on_pick(self, picked: Path | None) -> None:
        if picked is not None and picked.is_file():
            self.open_path(picked)
            self.query_one("#editor", OcodeEditor).focus()

    def action_module_jump(self) -> None:
        if not self.project or not self.project.modules:
            self.notify("No Odoo modules detected", severity="warning")
            return
        names = sorted(m.name for m in self.project.modules)
        self.push_screen(FilterScreen("Switch Module (Ctrl+Shift+M)", names), self._on_module_pick)

    def _on_module_pick(self, picked: Path | None) -> None:
        if picked is None or not self.project:
            return
        name = picked.name
        for m in self.project.modules:
            if m.name == name:
                manifest = m.path / "__manifest__.py"
                self.open_path(manifest if manifest.is_file() else m.path / "__init__.py")
                return

    def _current_module(self) -> object:
        try:
            st = self.active_state()
            if st.doc.path is None or not self.project:
                return None
            return find_module_dir(st.doc.path, self.project.modules)
        except Exception:
            return None

    def action_related_cycle(self) -> None:
        if not self.project:
            return
        st = self.active_state()
        if st.doc.path is None:
            return
        nxt = cycle_related(st.doc.path, self.project.modules)
        if nxt is None:
            self.notify("No related files", timeout=2)
            return
        self.open_path(nxt)

    def action_related_popup(self) -> None:
        if not self.project:
            return
        st = self.active_state()
        if st.doc.path is None:
            return
        rel = related_files(st.doc.path, self.project.modules)
        if not rel:
            self.notify("No related files", timeout=2)
            return
        base = self.project.root or st.doc.path.parent
        cands = [str(p.relative_to(base)) if _is_relative(p, base) else str(p) for p in rel]
        self.push_screen(FilterScreen("Related Files (Alt+R)", cands, base), self._on_pick)

    def action_grep(self) -> None:
        proj = self.project
        roots = list(proj.addons_paths) if proj and proj.addons_paths else [self.start_path]
        self.push_screen(GrepScreen(roots), lambda _p: None)

    def action_keyfile(self, kind: str) -> None:
        mod = self._current_module()
        if mod is None or self.project is None:
            self.notify("No current module", severity="warning")
            return
        from ocode.engines.opd.module import ModuleInfo as MI

        assert isinstance(mod, MI)
        conf = self.project.conf.path if self.project.conf and self.project.conf.path else None
        target = key_file(mod, kind, conf)
        if target is None or not target.is_file():
            self.notify(f"No {kind} file", timeout=2)
            return
        self.open_path(target)

    def action_toggle_find(self) -> None:
        bar = self.query_one("#findbar", FindBar)
        bar.visible = not bar.visible
        bar.set_class(bar.visible, "visible")
        if bar.visible:
            try:
                self.query_one("#find-input", Input).focus()
            except Exception:
                pass
        else:
            self.query_one("#editor", OcodeEditor).focus()

    def _current_find_options(self) -> FindOptions | None:
        try:
            opt: FindOptions = self.query_one("#findbar", FindBar).options()
            return opt
        except Exception:
            return None

    def action_find_next(self) -> None:
        opt = self._current_find_options()
        editor = self.query_one("#editor", OcodeEditor)
        if opt and opt.pattern:
            if editor.state.last_find != opt:
                editor.state.find_all(opt)
            editor.state.find_next()
            editor.refresh()
            self.update_chrome()

    def action_find_prev(self) -> None:
        opt = self._current_find_options()
        editor = self.query_one("#editor", OcodeEditor)
        if opt and opt.pattern:
            if editor.state.last_find != opt:
                editor.state.find_all(opt)
            editor.state.find_prev()
            editor.refresh()
            self.update_chrome()

    def action_replace_all(self) -> None:
        self.notify("Replace-all prompt lands with polish (use API for now)", timeout=3)

    def action_goto_line(self) -> None:
        self.notify("Ctrl+G: type line in find box as :N", timeout=3)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "find-input":
            return
        value = event.value
        editor = self.query_one("#editor", OcodeEditor)
        if value.startswith(":") and value[1:].isdigit():
            editor.state.goto_line(int(value[1:]))
            editor.refresh()
            self.update_chrome()
            return
        opt = self._current_find_options()
        if opt and opt.pattern:
            editor.state.find_all(opt)
            editor.state.find_next(wrap=False)
            editor.refresh()
            self.update_chrome()

    async def on_editor_saved(self, event: EditorSaved) -> None:
        if self._swap is not None:
            self._swap.clear()
        self.notify(f"Saved {event.path}" if event.path else "Saved", timeout=2)
        if event.path is not None:
            self._reindex_path(event.path)
            self.refresh_diagnostics_for_active()
        self.update_chrome()
        # auto-update current module on save (opt-in, FR-OSS-009)
        srv = self.server
        if srv is None or not srv.profile.auto_update_on_save or event.path is None:
            return
        mod = self.current_module_name()
        if mod is None:
            return
        if not self._lint_gate([mod]):
            return
        self.notify(f"Auto-updating {mod}…", timeout=2)
        try:
            await srv.restart_update([mod])
        except OSError as exc:
            self.notify(f"Auto-update failed: {exc}", severity="error")
        self._report_server_hint()
        self.update_chrome()

    # -- server actions (FR-OSS-001..005) --------------------------------
    async def action_server_toggle(self) -> None:
        srv = self.server
        if srv is None:
            self.notify("No server profile", severity="warning")
            return
        if srv.status in ("Running", "Updating", "Starting"):
            await srv.stop()
            self.notify("Server stopped", timeout=2)
        else:
            self.notify(f"$ {srv.preview()}", timeout=4)
            await srv.start()
            self._report_server_hint()
        self.update_chrome()

    async def action_server_restart(self) -> None:
        srv = self.server
        if srv is None:
            return
        if not self._lint_gate(self._gate_modules()):
            return
        self.notify(f"$ {srv.preview()}", timeout=4)
        await srv.restart()
        self._report_server_hint()
        self.update_chrome()

    def _gate_modules(self) -> list[str]:
        mod = self.current_module_name()
        return [mod] if mod else []

    async def action_server_update_current(self) -> None:
        srv = self.server
        if srv is None:
            return
        mod = self.current_module_name()
        if mod is None:
            self.notify("No current module to update", severity="warning")
            return
        if not self._lint_gate([mod]):
            return
        self.notify(f"Restart + update {mod}…", timeout=3)
        await srv.restart_update([mod])
        self._report_server_hint()
        self.update_chrome()

    def action_server_update_choose(self) -> None:
        srv = self.server
        if srv is None:
            return
        mods = [m.name for m in self.project.modules] if self.project else []
        self.push_screen(
            UpdateChooserScreen(mods, self.current_module_name()), self._on_update_chosen
        )

    def _on_update_chosen(self, mods: list[str] | None) -> None:
        if not mods:
            return
        if "all" in mods:
            self.push_screen(ConfirmScreen("Update ALL modules? (-u all)"), self._on_update_all)
            return
        if not self._lint_gate(mods):
            return
        srv = self.server
        if srv is None:
            return

        async def _run() -> None:
            assert srv is not None
            await srv.restart_update(mods)
            self._report_server_hint()
            self.update_chrome()

        self._spawn(_run())

    def _on_update_all(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        srv = self.server
        if srv is None:
            return

        async def _run() -> None:
            assert srv is not None
            await srv.restart_update(["all"])
            self._report_server_hint()
            self.update_chrome()

        self._spawn(_run())

    def _spawn(self, coro: Coroutine[object, object, None]) -> None:
        import asyncio as _aio

        try:
            _aio.ensure_future(coro)
        except RuntimeError as exc:
            self.notify(f"Cannot run: {exc}", severity="error")

    def _report_server_hint(self) -> None:
        srv = self.server
        if srv is None:
            return
        hint = srv.snapshot_hint
        if hint is None and srv.status == "Crashed" and srv.logs.records():
            from ocode.engines.oss.failure import detect_failure as _df

            hint = _df("\n".join(r.raw for r in srv.logs.records()[-120:]))
            srv.snapshot_hint = hint
        if hint is None:
            return
        extra = ""
        if hint.links:
            first = hint.links[0]
            extra = f" — {first[0]}:{first[1]} (click log link to open)"
        self.notify(f"{srv.status}: {hint.summary}{extra}", severity="error", timeout=8)

    def action_server_setup(self) -> None:
        srv = self.server
        if srv is None:
            return
        self.push_screen(ServerSetupScreen(srv.profile), self._on_profile_saved)

    def _on_profile_saved(self, prof: ServerProfile | None) -> None:
        if prof is None or self.server is None:
            return
        ws = (self.project.root if self.project and self.project.root else self.start_path)
        ws = ws if ws.is_dir() else ws.parent
        self.server_profiles[prof.name] = prof
        try:
            save_profiles(ws, self.server_profiles)
        except OSError as exc:
            self.notify(f"Cannot save profile: {exc}", severity="error")
            return
        running = self.server.proc.running
        self.server.profile = prof
        try:
            panel = self.query_one("#logs", LogPanel)
            panel.buffer = self.server.logs
        except Exception:
            pass
        suffix = " (restart to apply)" if running else ""
        self.notify(f"Profile '{prof.name}' saved{suffix}", timeout=3)
        self.update_chrome()

    def action_toggle_logs(self) -> None:
        order = ["hidden", "logs", "shell", "problems"]
        self._bottom_mode = order[(order.index(self._bottom_mode) + 1) % len(order)]
        self._apply_bottom_mode()
        if self._bottom_mode == "shell":
            self._poll_shell()

    def action_log_clear(self) -> None:
        try:
            self.query_one("#logs", LogPanel).clear()
        except Exception:
            pass
        self._last_error_badge = ""
        self.update_chrome()

    def _show_bottom(self, mode: str) -> None:
        self._bottom_mode = mode
        self._apply_bottom_mode()

    # -- M5: generators (FR-OSG-001..013, Ctrl+Shift+N) ---------------------
    def action_generate_menu(self) -> None:
        labels = [title for _, title in GENERATORS]
        base = self.start_path if self.start_path.is_dir() else self.start_path.parent
        self.push_screen(FilterScreen("Generate (Ctrl+Shift+N)", labels, base),
                         self._on_generate_pick)

    def _on_generate_pick(self, picked: Path | None) -> None:
        if picked is None:
            return
        label = picked.name
        key = next((k for k, title in GENERATORS if title == label or title.startswith(label)), "")
        if not key:
            key = next((k for k, title in GENERATORS if label in title), "")
        if key == "snippet":
            self.action_snippet_insert()
            return
        if not key:
            return
        self._open_generator(key)

    def _gen_ctx(self) -> tuple[str, str, str]:
        """Return (module, model, version) for generator defaults."""
        mod = self.current_module_name() or ""
        model = ""
        try:
            st = self.active_state()
            if st.doc.path is not None and st.doc.path.suffix == ".py":
                model = self._model_at_cursor(st)
        except Exception:
            pass
        version = self.project.version if self.project else "17.0"
        return (mod, model, version or "17.0")

    def _open_generator(self, key: str) -> None:
        mod, model, version = self._gen_ctx()
        from textual.screen import ModalScreen as _MS

        screens: dict[str, _MS[list[PlannedChange] | None]] = {
            "module": NewModuleScreen(version=f"{version}.1.0" if "." in version else version),
            "model": ModelScreen(module=mod, version=version),
            "inherit": InheritModelScreen(module=mod,
                                          models=self.oki.models() if self.oki else []),
            "view": ViewScreen(module=mod, model=model, version=version),
            "xpath": XpathScreen(module=mod, model=model),
            "access": AccessScreen(module=mod, model=model),
            "groups": GroupsScreen(module=mod, model=model),
            "wizard": WizardScreen(module=mod),
            "report": ReportScreen(module=mod, model=model),
            "controller": ControllerScreen(module=mod),
            "cron": CronScreen(module=mod, model=model),
            "test": TestScreen(module=mod, model=model),
        }
        screen = screens.get(key)
        if screen is None:
            return
        self.push_screen(screen, self._on_generate_plan)

    def _module_dir_for(self, key_module: str) -> Path | None:
        if self.project:
            for m in self.project.modules:
                if m.name == key_module:
                    return m.path
        return None

    def _on_generate_plan(self, changes: list[PlannedChange] | None) -> None:
        if not changes:
            return
        rebased = self._rebase_changes(changes)
        if not rebased:
            return
        diffs = "".join(preview_diff(c) for c in rebased)[:6000]
        has_overwrite = any(c.action == "overwrite" for c in rebased)
        self._pending_changes = rebased
        self.push_screen(DiffScreen(f"Apply {len(rebased)} change(s)?", diffs, has_overwrite),
                         self._on_generate_confirm)

    def _rebase_changes(self, changes: list[PlannedChange]) -> list[PlannedChange]:
        """Replace Path.cwd()/__PENDING__ placeholders with real module dirs."""
        out: list[PlannedChange] = []
        mod, _, _ = self._gen_ctx()
        module_dir = self._module_dir_for(mod)
        for c in changes:
            text = str(c.path)
            cwd = str(Path.cwd())
            if "__PENDING__" in text:
                if module_dir is None:
                    self.notify("No current module — open a module file first",
                                severity="warning")
                    return []
                text = text.replace(str(Path.cwd() / "__PENDING__"), str(module_dir))
                text = text.replace("__PENDING__", str(module_dir))
            elif text.startswith(cwd + "/") and c.detail.startswith("new module"):
                parent = self._new_module_parent()
                text = str(parent / Path(text).relative_to(cwd))
            new_path = Path(text)
            # never silently overwrite dirty open buffers
            for doc in self.docs:
                if doc.doc.path == new_path and doc.doc.dirty:
                    self.notify(f"{new_path.name} has unsaved changes — save first",
                                severity="warning")
                    return []
            out.append(PlannedChange(new_path, c.action, c.new_text, c.detail, c.old_text))
        return out

    def _new_module_parent(self) -> Path:
        proj = self.project
        if proj and proj.addons_paths:
            return proj.addons_paths[-1]
        base = self.start_path
        return base if base.is_dir() else base.parent

    def _on_generate_confirm(self, confirmed: bool | None) -> None:
        changes = getattr(self, "_pending_changes", [])
        self._pending_changes = []
        if not confirmed or not changes:
            return
        try:
            written = apply_changes(changes, allow_overwrite=True)
        except OSError as exc:
            self.notify(f"Generate failed: {exc}", severity="error")
            return
        for path in written:
            self._reindex_path(path)
        try:
            if self.project:
                self.query_one("#tree", OdooTree).set_project(self.project)
        except Exception:
            pass
        self.refresh_diagnostics_for_active()
        self.update_chrome()
        first = next((p for p in written if p.suffix in (".py", ".xml")), None)
        if first is not None:
            self.open_path(first)
            try:
                self.query_one("#editor", OcodeEditor).focus()
            except Exception:
                pass
        self.notify(f"Generated {len(written)} file(s)", timeout=3)

    def action_snippet_insert(self) -> None:
        labels = sorted(SNIPPETS)
        base = self.start_path if self.start_path.is_dir() else self.start_path.parent
        self.push_screen(FilterScreen("Insert Snippet", labels, base), self._on_snippet_pick)

    def _on_snippet_pick(self, picked: Path | None) -> None:
        if picked is None:
            return
        trigger = picked.name
        if trigger not in SNIPPETS:
            match = next((t for t in SNIPPETS if t.startswith(trigger)), None)
            if match is None:
                return
            trigger = match
        try:
            editor = self.query_one("#editor", OcodeEditor)
        except Exception:
            return
        body = expand_snippet(trigger, self.project.version if self.project else None)
        if body is None:
            return
        text, _cursor = render_snippet(body)
        editor.state.type_text(text)
        editor.refresh()
        self.update_chrome()
        editor.focus()

    # -- M5: embedded shell (FR-OSH-001..008, Ctrl+`) -----------------------
    def _shell_profile(self) -> tuple[str, str, str, str] | None:
        srv = self.server
        if srv is None:
            return None
        p = srv.profile
        return (p.odoo_bin, p.python, p.conf, p.db)

    def action_shell_toggle(self) -> None:
        if self.shell is not None and self.shell.alive:
            # survive close/reopen: just hide the panel (FR-OSH-002)
            if self._bottom_mode == "shell":
                self._show_bottom("logs")
            else:
                self._show_bottom("shell")
                try:
                    self.query_one("#shell", ShellPanel).focus()
                except Exception:
                    pass
            return
        prof = self._shell_profile()
        if prof is None:
            self.notify("No server profile", severity="warning")
            return
        odoo_bin, python, conf, db = prof
        if not odoo_bin:
            self.notify("Set odoo-bin in Server Setup first", severity="warning")
            return
        if is_production_db(db):
            self.push_screen(
                ConfirmScreen(f"⚠ '{db}' looks like PRODUCTION. Start shell anyway?"),
                lambda ok: self._start_shell_after_confirm(bool(ok)),
            )
            return
        self._start_shell_after_confirm(True)

    def _start_shell_after_confirm(self, ok: bool) -> None:
        if not ok:
            return
        prof = self._shell_profile()
        if prof is None:
            return
        odoo_bin, python, conf, db = prof
        prog, argv = shell_command(odoo_bin, python, conf, db)
        interface = ""
        for fl in (self.server.profile.flags if self.server else []):
            if fl.startswith("--shell-interface"):
                interface = fl.split("=", 1)[1] if "=" in fl else ""
        if interface:
            prog, argv = shell_command(odoo_bin, python, conf, db, interface=interface)
        session = ShellSession(db=db)
        try:
            session.start([prog, *argv])
        except OSError as exc:
            self.notify(f"Shell failed: {exc}", severity="error")
            return
        self.shell = session
        try:
            panel = self.query_one("#shell", ShellPanel)
            panel.attach(session)
        except Exception:
            pass
        self._show_bottom("shell")
        try:
            self.query_one("#shell", ShellPanel).focus()
        except Exception:
            pass
        self.notify(f"$ {prog} {' '.join(argv[1:3])}…", timeout=3)
        self.update_chrome()

    def action_shell_stop(self) -> None:
        if self.shell is not None:
            try:
                self.shell.stop()
            except OSError:
                pass
            self.shell = None
        try:
            self.query_one("#shell", ShellPanel).detach()
        except Exception:
            pass
        self._show_bottom("logs")
        self.update_chrome()

    def _poll_shell(self) -> None:
        shell = self.shell
        if shell is None or not shell.alive:
            return
        try:
            shell.poll()
        except OSError:
            return
        if self._bottom_mode != "shell":
            return
        try:
            self.query_one("#shell", ShellPanel).refresh(layout=True)
        except Exception:
            pass

    def action_shell_send(self) -> None:
        shell = self.shell
        if shell is None or not shell.alive:
            self.notify("Shell not running — Ctrl+` to start", severity="warning")
            return
        try:
            st = self.active_state()
        except Exception:
            return
        text = st.selected_text() or st.lines()[st.cursor.line]
        if not text.strip():
            return
        try:
            shell.send(text)
        except (OSError, RuntimeError) as exc:
            self.notify(f"Send failed: {exc}", severity="error")
            return
        self._show_bottom("shell")
        self.update_chrome()

    def action_shell_inject_self(self) -> None:
        shell = self.shell
        if shell is None or not shell.alive:
            self.notify("Shell not running — Ctrl+` to start", severity="warning")
            return
        model = ""
        try:
            model = self._model_at_cursor(self.active_state())
        except Exception:
            pass
        if not model:
            self.notify("No model at cursor", severity="warning")
            return
        try:
            shell.send(f"self = env['{model}']")
        except (OSError, RuntimeError) as exc:
            self.notify(f"Send failed: {exc}", severity="error")
            return
        self._show_bottom("shell")

    async def on_shell_exited(self, event: ShellExited) -> None:
        _ = event
        self.notify("Shell exited", timeout=3)
        self.shell = None
        try:
            self.query_one("#shell", ShellPanel).detach()
        except Exception:
            pass
        self._show_bottom("logs")
        self.update_chrome()

    # -- M4: completion (FR-OMLS-010..018) --------------------------------
    def _completion_ctx(self) -> tuple[EditorState, int] | None:
        try:
            editor = self.query_one("#editor", OcodeEditor)
        except Exception:
            return None
        st = editor.state
        return (st, st.pos_to_offset(st.cursor))

    def action_show_completion(self) -> None:
        if self.oki is None:
            self.notify("Index not ready yet", timeout=2)
            return
        found = self._completion_ctx()
        if found is None:
            return
        st, offset = found
        items = complete_at(st.doc.path, st.doc.text, offset, self.oki,
                            self.current_module_name(),
                            self.project.version if self.project else None)
        if not items:
            self.notify("No completions", timeout=1)
            return
        try:
            self.query_one("#complete", CompletionPopup).show(items)
        except Exception:
            pass

    def after_edit_for_completion(self, _ch: str) -> None:
        if self.oki is None:
            return
        try:
            pop = self.query_one("#complete", CompletionPopup)
            if pop.is_open:
                self.action_show_completion()
                return
        except Exception:
            return
        found = self._completion_ctx()
        if found is None:
            return
        st, offset = found
        if len(st.fragment()) < 2:
            return
        items = complete_at(st.doc.path, st.doc.text, offset, self.oki,
                            self.current_module_name(),
                            self.project.version if self.project else None)
        if items:
            try:
                self.query_one("#complete", CompletionPopup).show(items)
            except Exception:
                pass

    def accept_completion(self) -> None:
        try:
            pop = self.query_one("#complete", CompletionPopup)
            editor = self.query_one("#editor", OcodeEditor)
        except Exception:
            return
        cur = pop.current()
        if cur is None:
            pop.hide()
            return
        pop.hide()
        st = editor.state
        if cur.kind == "snippet":
            body = expand_snippet(cur.insert,
                                  self.project.version if self.project else None)
            if body is None:
                st.replace_fragment(cur.insert)
            else:
                text, _cursor = render_snippet(body)
                word = st.word_before_cursor()
                if word:
                    off = st.pos_to_offset(st.cursor)
                    st.doc.delete(off - len(word), len(word))
                    st.set_cursor(st.offset_to_pos(off - len(word)))
                st.type_text(text)
        else:
            st.replace_fragment(cur.insert)
        editor.refresh()
        self.update_chrome()

    async def on_completion_accepted(self, event: object) -> None:
        _ = event
        self.accept_completion()

    def try_expand_snippet(self) -> bool:
        try:
            editor = self.query_one("#editor", OcodeEditor)
        except Exception:
            return False
        st = editor.state
        word = st.word_before_cursor()
        if word not in SNIPPETS:
            return False
        body = expand_snippet(word, self.project.version if self.project else None)
        if body is None:
            return False
        text, _cursor = render_snippet(body)
        off = st.pos_to_offset(st.cursor)
        st.doc.delete(off - len(word), len(word))
        st.set_cursor(st.offset_to_pos(off - len(word)))
        st.type_text(text)
        editor.refresh()
        self.update_chrome()
        return True

    # -- M4: diagnostics + lint (FR-OMLS-020..025, 030..034) ---------------
    def action_lint_file(self) -> None:
        try:
            st = self.active_state()
        except Exception:
            return
        if st.doc.path is None:
            return
        try:
            ctx = self._file_ctx_for(st.doc.path)
            diags = analyze_file(st.doc.text, ctx)
        except OSError:
            return
        self.problems = [d for d in self.problems if d.file != str(st.doc.path)] + diags
        try:
            self.query_one("#problems", ProblemsPanel).set_items(self.problems)
        except Exception:
            pass
        self._show_bottom("problems")
        self.update_chrome()
        self.scheduler.run_in_thread("pylint-file", self._pylint_file_sync, st.doc.path)

    def _pylint_file_sync(self, path: Path) -> None:
        from ocode.engines.omls.pylint import pylint_available, run_pylint_odoo

        ok, hint = pylint_available()
        if not ok:
            self.call_from_thread(self.notify, hint, {"timeout": 4})
            return
        version = self.project.version if self.project else None
        res = run_pylint_odoo([path], version)
        if res.diagnostics:
            self.call_from_thread(self._merge_pylint, res.diagnostics)

    def _merge_pylint(self, diags: list[Diagnostic]) -> None:
        files = {d.file for d in diags}
        self.problems = [d for d in self.problems
                         if d.file not in files or d.code != "PYLINT"]
        self.problems += diags
        try:
            self.query_one("#problems", ProblemsPanel).set_items(self.problems)
        except Exception:
            pass
        self.update_chrome()

    def action_lint_module(self) -> None:
        mod = self._current_module()
        if mod is None:
            self.notify("No current module", severity="warning")
            return
        from ocode.engines.opd.module import ModuleInfo as MI

        assert isinstance(mod, MI)
        files: dict[str, str] = {}
        try:
            for p in mod.path.rglob("*"):
                if p.is_file() and p.suffix in (".py", ".xml") and len(files) < 300:
                    try:
                        files[str(p.relative_to(mod.path))] = p.read_text(encoding="utf-8")
                    except OSError:
                        continue
        except OSError:
            pass
        from ocode.engines.omls.diagnostics import analyze_module

        diags = analyze_module(mod, files, self.oki,
                               self.project.version if self.project else None)
        prefix = str(mod.path)
        self.problems = [d for d in self.problems if not d.file.startswith(prefix)] + diags
        try:
            self.query_one("#problems", ProblemsPanel).set_items(self.problems)
        except Exception:
            pass
        self._show_bottom("problems")
        errs = sum(1 for d in diags if d.severity == "error")
        self.notify(f"Module lint: {len(diags)} issues ({errs} errors)", timeout=3)
        self.update_chrome()

    def _lint_gate(self, modules: list[str]) -> bool:
        """Lint-before-restart gate (FR-OMLS-032). Returns True to proceed."""
        srv = self.server
        if srv is None or srv.profile.lint_before_restart == "off":
            return True
        errs: list[Diagnostic] = []
        for doc in self.docs:
            if doc.doc.path is None:
                continue
            mod_name = self._module_of(doc.doc.path)
            if mod_name is None or (modules != ["all"] and mod_name not in modules):
                continue
            try:
                ctx = self._file_ctx_for(doc.doc.path)
                errs += [d for d in analyze_file(doc.doc.text, ctx) if d.severity == "error"]
            except OSError:
                continue
        if not errs:
            return True
        self.problems = errs + [d for d in self.problems if d.severity != "error"]
        try:
            self.query_one("#problems", ProblemsPanel).set_items(self.problems)
        except Exception:
            pass
        self._show_bottom("problems")
        if srv.profile.lint_before_restart == "block":
            self.notify(f"Lint gate: {len(errs)} error(s) — restart blocked", severity="error")
            return False
        self.notify(f"Lint gate: {len(errs)} error(s) — proceeding (warn)", severity="warning")
        return True

    def _module_of(self, path: Path) -> str | None:
        if not self.project:
            return None
        mod = find_module_dir(path, self.project.modules)
        return mod.name if mod else None

    # -- M4: quick fixes (FR-OMLS-024, Ctrl+.) ------------------------------
    def action_quick_fix(self) -> None:
        try:
            st = self.active_state()
        except Exception:
            return
        if st.doc.path is None:
            return
        line = st.cursor.line + 1
        cands = [d for d in self.problems
                 if d.file == str(st.doc.path) and abs(d.line - line) <= 1]
        if not cands:
            try:
                ctx = self._file_ctx_for(st.doc.path)
                cands = [d for d in analyze_file(st.doc.text, ctx) if abs(d.line - line) <= 1]
            except OSError:
                return
        options: list[tuple[str, Diagnostic]] = []
        for d in cands:
            for _fix_id, title in available_fixes(d):
                options.append((f"{title} [{d.code}]", d))
        if not options:
            self.notify("No quick fixes here", timeout=2)
            return
        labels = [t for t, _ in options]
        self._fix_map = {}
        for (title, diag) in options:
            for fix_id, _ in available_fixes(diag):
                self._fix_map[title] = (diag, fix_id)
                break
        base = st.doc.path.parent
        self.push_screen(FilterScreen("Quick Fix (Ctrl+.)", labels, base), self._on_fix_pick)

    def _on_fix_pick(self, picked: Path | None) -> None:
        if picked is None or not self._fix_map:
            return
        label = picked.name
        match = next((t for t in self._fix_map if t == label or t.startswith(label)), None)
        if match is None:
            match = next(iter(self._fix_map))
        diag, fix_id = self._fix_map[match]
        self.apply_quickfix(diag, fix_id)

    def apply_quickfix(self, diag: Diagnostic, fix_id: str) -> None:
        kind = fix_id.split(":")[0]
        payload = fix_id.split(":", 1)[1] if ":" in fix_id else ""
        if kind in ("manifest-data", "manifest-depends"):
            target = self._manifest_for_diag()
            if target is not None:
                self._apply_fix_to_file(target, fix_id, payload)
                return
        if kind == "access-row":
            target = self._access_file_for_diag()
            if target is not None:
                self._apply_fix_to_file(target, fix_id, payload)
                return
        if kind in ("init-import", "init-import-models"):
            target = self._init_file_for_diag(diag, kind)
            if target is not None:
                self._apply_fix_to_file(target, fix_id, payload)
                return
        try:
            editor = self.query_one("#editor", OcodeEditor)
        except Exception:
            return
        st = editor.state
        st.doc.history.begin_group()
        try:
            new_text, applied = apply_fix(fix_id, st.doc.text, payload)
            if applied:
                st.doc.delete(0, len(st.doc.text))
                st.doc.insert(0, new_text)
        finally:
            st.doc.history.end_group()
        editor.refresh()
        self.refresh_diagnostics_for_active()
        self.update_chrome()

    def _manifest_for_diag(self) -> Path | None:
        mod = self._current_module()
        if mod is None:
            return None
        from ocode.engines.opd.module import ModuleInfo as MI

        assert isinstance(mod, MI)
        return mod.manifest_path

    def _access_file_for_diag(self) -> Path | None:
        mod = self._current_module()
        if mod is None:
            return None
        from ocode.engines.opd.module import ModuleInfo as MI

        assert isinstance(mod, MI)
        target = mod.path / "security" / "ir.model.access.csv"
        if not target.exists():
            header = (
                "id,name,model_id:id,group_id:id,"
                "perm_read,perm_write,perm_create,perm_unlink\n"
            )
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(header, encoding="utf-8")
            except OSError:
                return None
        return target

    def _init_file_for_diag(self, diag: Diagnostic, kind: str) -> Path | None:
        mod = self._current_module()
        if mod is None:
            return None
        from ocode.engines.opd.module import ModuleInfo as MI

        assert isinstance(mod, MI)
        if kind == "init-import-models":
            return mod.path / "__init__.py"
        cur = Path(diag.file).parent / "__init__.py"
        return cur if cur.parent.name == "models" else mod.path / "models" / "__init__.py"

    def _apply_fix_to_file(self, target: Path, fix_id: str, payload: str) -> None:
        kind = fix_id.split(":")[0]
        if kind == "init-import" and not payload:
            payload = self._guess_init_stem(target)
        opened_here = False
        state = next((d for d in self.docs if d.doc.path == target), None)
        if state is None:
            try:
                text = target.read_text(encoding="utf-8") if target.exists() else ""
            except OSError:
                return
            from ocode.engines.ote.document import Document as _Doc

            state = EditorState(_Doc(path=target, text=text))
            opened_here = True
        new_text, applied = apply_fix(fix_id, state.doc.text, payload)
        if not applied:
            self.notify("Fix not applicable", timeout=2)
            return
        if opened_here:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(new_text, encoding="utf-8")
            except OSError as exc:
                self.notify(f"Cannot write {target}: {exc}", severity="error")
                return
            self._reindex_path(target)
            self.notify(f"Fixed {target.name}", timeout=2)
        else:
            state.doc.history.begin_group()
            try:
                state.doc.delete(0, len(state.doc.text))
                state.doc.insert(0, new_text)
                state.save()
            except (OSError, ValueError, PermissionError) as exc:
                self.notify(f"Cannot save: {exc}", severity="error")
                return
            finally:
                state.doc.history.end_group()
            try:
                self.query_one("#editor", OcodeEditor).refresh()
            except Exception:
                pass
            self._reindex_path(target)
        self.refresh_diagnostics_for_active()
        self.update_chrome()

    def _guess_init_stem(self, init_path: Path) -> str:
        for d in self.problems:
            if d.code == "ODOO007" and Path(d.file).parent == init_path.parent:
                import re as _re

                m = _re.search(r"'(\w+)' not imported", d.message)
                if m:
                    return m.group(1)
        try:
            cands = sorted(init_path.parent.glob("*.py"))
            for c in reversed(cands):
                if c.name != "__init__.py":
                    return c.stem
        except OSError:
            pass
        return ""

    def _reindex_path(self, path: Path) -> None:
        if not self.project or path.suffix not in (".py", ".xml", ".csv"):
            return
        try:
            ws = self.project.root if self.project.root else path.parent
            db = OkiDb(index_path_for(ws))
            try:
                Indexer(db, list(self.project.modules)).update_file(path)
            finally:
                db.close()
        except OSError:
            pass
        if self.oki_db is not None:
            try:
                self.oki_db.close()
            except OSError:
                pass
            try:
                ws = self.project.root if self.project.root else path.parent
                self.oki_db = OkiDb(index_path_for(ws))
                self.oki = OkiQuery(self.oki_db)
            except OSError:
                self.oki = None

    # -- M4: hover / outline / goto (FR-OTE-080/082, SMN-023) ----------------
    def action_show_hover(self) -> None:
        if self.oki is None:
            self.notify("Index not ready yet", timeout=2)
            return
        try:
            st = self.active_state()
        except Exception:
            return
        frag = st.fragment() or st.word_before_cursor()
        if not frag:
            self.notify("Nothing under cursor", timeout=2)
            return
        title, body = self._hover_for(frag, st)
        self.push_screen(HoverScreen(title, body), lambda _x: None)

    def _hover_for(self, frag: str, st: EditorState) -> tuple[str, str]:
        assert self.oki is not None
        base = frag.split(".")[-1]
        if frag in self.oki.models():
            fields = self.oki.merged_fields(frag)
            mods = self.oki.model_modules(frag)
            lines = [f"Model {frag} — {len(fields)} fields ({', '.join(mods[:5])})"]
            for name, finfo in sorted(fields.items())[:15]:
                lines.append(f"  {name}: {finfo.get('type', '')} {finfo.get('string', '')}")
            if len(fields) > 15:
                lines.append(f"  … +{len(fields) - 15} more")
            return (frag, "\n".join(lines))
        model = self._model_at_cursor(st)
        if model and base in self.oki.merged_fields(model):
            finfo = self.oki.merged_fields(model)[base]
            body = (f"{model}.{base}\ntype={finfo.get('type', '')} "
                    f"comodel={finfo.get('comodel', '')} required={finfo.get('required', False)}\n"
                    f"string={finfo.get('string', '')} module={finfo.get('module', '')}")
            return (base, body)
        if "." in frag and self.oki.xmlid_exists(frag):
            return (frag, f"XML ID {frag} — defined in index.")
        return (frag, "No documentation found in index.")

    def _model_at_cursor(self, st: EditorState) -> str:
        import re as _re

        before = st.doc.text[: st.pos_to_offset(st.cursor)]
        names = _re.findall(r"_name\s*=\s*['\"]([\w.]+)['\"]", before)
        return names[-1] if names else ""

    def action_show_outline(self) -> None:
        try:
            st = self.active_state()
        except Exception:
            return
        if st.doc.path is None:
            return
        suffix = st.doc.path.suffix
        cands: list[str] = []
        mapping: dict[str, int] = {}
        if suffix == ".py":
            from ocode.engines.oki.pyparse import parse_python as _pp

            info = _pp(st.doc.text)
            for cls in info.classes:
                label = f"class {cls.name}:{cls.lineno}"
                cands.append(label)
                mapping[label] = cls.lineno
                for fld in cls.fields:
                    label2 = f"  {fld.name} ({fld.ftype}):{fld.lineno}"
                    cands.append(label2)
                    mapping[label2] = fld.lineno
                for m in cls.methods:
                    label3 = f"  {m.name}():{m.lineno}"
                    cands.append(label3)
                    mapping[label3] = m.lineno
        elif suffix == ".xml":
            from ocode.engines.oki.xmlparse import parse_xml as _px

            xinfo = _px(st.doc.text)
            for x in xinfo.xmlids:
                label = f"{x.kind} {x.xmlid}"
                cands.append(label)
                mapping[label] = 1
            for v in xinfo.views:
                label = f"view {v.xmlid} ({v.model})"
                if label not in mapping:
                    cands.append(label)
                    mapping[label] = 1
        if not cands:
            self.notify("No symbols", timeout=2)
            return
        self._outline_map = mapping
        base = st.doc.path.parent
        self.push_screen(FilterScreen("Outline/Symbols", cands, base), self._on_outline_pick)

    def _on_outline_pick(self, picked: Path | None) -> None:
        if picked is None:
            return
        lineno = self._outline_map.get(picked.name, 1)
        try:
            st = self.active_state()
            st.goto_line(lineno)
            self.query_one("#editor", OcodeEditor).refresh()
            self.update_chrome()
        except Exception:
            pass

    def action_goto_definition(self) -> None:
        if self.oki is None:
            self.notify("Index not ready yet", timeout=2)
            return
        try:
            st = self.active_state()
        except Exception:
            return
        frag = (st.fragment() or st.word_before_cursor()).strip(".,;:'\"()")
        if not frag:
            return
        target = self._goto_target(frag)
        if target is None:
            self.notify(f"No definition for '{frag}'", timeout=2)
            return
        path, line = target
        self.open_path(path, line)
        self.query_one("#editor", OcodeEditor).focus()

    def _goto_target(self, frag: str) -> tuple[Path, int] | None:
        assert self.oki is not None and self.oki_db is not None
        base = frag.split(".")[-1]
        if frag in self.oki.models():
            row = self.oki_db.query_one(
                "SELECT file, lineno FROM models WHERE name=? ORDER BY kind LIMIT 1", (frag,)
            )
            if row:
                return (Path(str(row["file"])), int(row["lineno"]))
        if "." in frag and self.oki.xmlid_exists(frag):
            mod, bare = frag.split(".", 1)
            row = self.oki_db.query_one(
                "SELECT file, lineno FROM xmlids WHERE xmlid=? AND module=?", (bare, mod)
            )
            if row:
                return (Path(str(row["file"])), int(row["lineno"]) or 1)
        try:
            st = self.active_state()
            model = self._model_at_cursor(st)
        except Exception:
            model = ""
        if model and base:
            row = self.oki_db.query_one(
                "SELECT file, lineno FROM fields WHERE model=? AND name=? LIMIT 1", (model, base)
            )
            if row:
                return (Path(str(row["file"])), int(row["lineno"]))
        return None

    def action_goto_references(self) -> None:
        try:
            st = self.active_state()
        except Exception:
            return
        word = (st.word_before_cursor() or st.fragment()).strip(".,;:'\"()")
        if not word:
            return
        proj = self.project
        roots = list(proj.addons_paths) if proj and proj.addons_paths else [self.start_path]
        from ocode.engines.smn.search import content_search as _cs

        hits = _cs(word, roots, max_hits=200)
        if not hits:
            self.notify(f"No references to '{word}'", timeout=2)
            return
        self._ref_targets = {}
        cands: list[str] = []
        base = proj.root if proj and proj.root else self.start_path
        for h in hits:
            try:
                rel: object = h.path.relative_to(base)
            except ValueError:
                rel = h.path
            label = f"{rel}:{h.line}:{h.col} {h.snippet}"
            cands.append(label)
            self._ref_targets[label] = (str(h.path), h.line)
        self.push_screen(FilterScreen(f"References: {word}", cands, base), self._on_ref_pick)

    def _on_ref_pick(self, picked: Path | None) -> None:
        if picked is None:
            return
        label = str(picked) if not picked.is_absolute() else picked.name
        for key, (path_s, line) in self._ref_targets.items():
            if key == label or key.endswith(label) or label in key:
                self.open_path(Path(path_s), line)
                try:
                    self.query_one("#editor", OcodeEditor).focus()
                except Exception:
                    pass
                return

    def action_problem_next(self) -> None:
        self._problem_step(1)

    def action_problem_prev(self) -> None:
        self._problem_step(-1)

    def _problem_step(self, delta: int) -> None:
        try:
            panel = self.query_one("#problems", ProblemsPanel)
        except Exception:
            return
        if not self.problems:
            self.notify("No problems", timeout=2)
            return
        panel.move(delta)
        cur = panel.current()
        if cur is not None:
            self.open_path(Path(cur.file), cur.line)
        self.update_chrome()

    async def on_problem_chosen(self, event: ProblemChosen) -> None:
        self.open_path(Path(event.file), event.line)
        self.query_one("#editor", OcodeEditor).focus()


def _is_relative(p: Path, base: Path) -> bool:
    try:
        p.relative_to(base)
        return True
    except ValueError:
        return False


def _fmt_uptime(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"
