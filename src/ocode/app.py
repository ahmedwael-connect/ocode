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
from ocode.engines.opd.detector import OdooProject, detect_project
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
from ocode.ui.screens.server import ConfirmScreen, ServerSetupScreen, UpdateChooserScreen
from ocode.ui.widgets.editor import EditorSaved, OcodeEditor
from ocode.ui.widgets.findbar import FindBar
from ocode.ui.widgets.logpanel import LogLinkClicked, LogPanel, level_badge
from ocode.ui.widgets.proj_tree import FilePicked, OdooTree


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
                yield LogPanel(id="logs")
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
        self.update_chrome()
        self.set_interval(5.0, self._autoswap)
        self.set_interval(1.0, self._poll_tailer)
        self.query_one("#editor", OcodeEditor).focus()

    def on_unmount(self) -> None:
        self._save_session()
        srv = self.server
        if srv is not None and srv.proc.running:
            try:
                import asyncio as _aio

                loop = _aio.get_event_loop()
                if loop.is_running():
                    loop.create_task(srv.stop())
            except (OSError, RuntimeError):
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
        info = f"{dot2} {fname} | {lang} | {enc} | {eol} | {loc}{nmatch}{odoo}{srv_txt}{badge}"
        status.update(info)

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
        self.notify("F1 help screen lands post-M2 (UI-008)", timeout=3)

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
        self.update_chrome()
        # auto-update current module on save (opt-in, FR-OSS-009)
        srv = self.server
        if srv is None or not srv.profile.auto_update_on_save or event.path is None:
            return
        mod = self.current_module_name()
        if mod is None:
            return
        if srv.profile.lint_before_restart == "block":
            self.notify("lint gate: no linter yet (M4) — update skipped", severity="warning")
            return
        if srv.profile.lint_before_restart == "warn":
            self.notify("lint gate: warn (no linter yet, M4)", timeout=2)
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
        self.notify(f"$ {srv.preview()}", timeout=4)
        await srv.restart()
        self._report_server_hint()
        self.update_chrome()

    async def action_server_update_current(self) -> None:
        srv = self.server
        if srv is None:
            return
        mod = self.current_module_name()
        if mod is None:
            self.notify("No current module to update", severity="warning")
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
        try:
            panel = self.query_one("#logs", LogPanel)
        except Exception:
            return
        panel.display = not panel.display
        if panel.display:
            panel.refresh(layout=True)

    def action_log_clear(self) -> None:
        try:
            self.query_one("#logs", LogPanel).clear()
        except Exception:
            pass
        self._last_error_badge = ""
        self.update_chrome()


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
