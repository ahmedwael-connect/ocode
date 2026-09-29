"""Textual app shell with M1 editor (tabs, find, status, swap recovery)."""

from __future__ import annotations

from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Label, Static

from ocode import __version__
from ocode.core.commands import CommandRegistry
from ocode.core.config import OcodeConfig
from ocode.core.events import EventBus
from ocode.core.tasks import TaskScheduler
from ocode.engines.ote.document import Document
from ocode.engines.ote.highlight import detect_language
from ocode.engines.ote.search import FindOptions
from ocode.engines.ote.session import SwapManager, swap_path_for
from ocode.engines.ote.state import EditorState
from ocode.engines.ote.tabs import TabState
from ocode.ui.widgets.editor import EditorSaved, OcodeEditor
from ocode.ui.widgets.findbar import FindBar


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
    reg.register("ocode.palette.open", "Show Command Palette", keybinding="ctrl+shift+p")
    reg.register("ocode.quickopen.open", "Go to File...", keybinding="ctrl+p")
    reg.register("ocode.sidebar.toggle", "Toggle Sidebar", keybinding="ctrl+b")
    reg.register("ocode.oss.restart", "Odoo: Restart Server", keybinding="f5")
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
        ("ctrl+shift+p", "show_palette", "Palette"),
        ("f3", "find_next", "Next"),
        ("shift+f3", "find_prev", "Prev"),
        ("f1", "show_help", "Help"),
    ]

    def __init__(
        self,
        start_path: Path | None = None,
        config: OcodeConfig | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.start_path = start_path or Path.cwd()
        self.ocode_config = config
        self.bus = EventBus()
        self.commands = build_default_commands()
        self.scheduler = TaskScheduler()
        self.tabs = TabState()
        self.docs: list[EditorState] = []
        self._swap: SwapManager | None = None

    # -- compose -------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Static("EXPLORER", id="sidebar-title")
                yield Label(str(self.start_path))
            with Vertical(id="editor-area"):
                yield Static("", id="tabbar")
                yield OcodeEditor(EditorState(), id="editor")
                yield FindBar(id="findbar")
        yield Static("", id="statusbar")
        yield Footer()

    def on_mount(self) -> None:
        target = self.start_path
        if target.is_file():
            self.open_path(target)
        else:
            self.new_untitled()
        pending = SwapManager.pending()
        if pending:
            self.notify(f"{len(pending)} swap file(s) found — recovery available", timeout=5)
        self.update_chrome()
        self.set_interval(5.0, self._autoswap)
        self.query_one("#editor", OcodeEditor).focus()

    # -- tabs / docs ---------------------------------------------------
    def new_untitled(self) -> None:
        self.tabs.open(None)
        self.docs.append(EditorState(Document()))
        self._bind_swap(None)
        self._show_active()

    def open_path(self, path: Path) -> None:
        idx = self.tabs.open(path)
        if idx < len(self.docs) and self.docs and self.tabs.tabs[idx] == path:
            # already open → just activate
            if idx < len(self.docs):
                self._show_active()
                return
        try:
            state = EditorState(Document.from_file(path))
        except OSError as exc:
            self.notify(f"Cannot open {path}: {exc}", severity="error")
            return
        if len(self.docs) == 1 and self.docs[0].doc.path is None and not self.docs[0].doc.dirty:
            self.docs[0] = state
        else:
            # align docs list with tabs list
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
        self._show_active()

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

    # -- chrome --------------------------------------------------------
    def update_chrome(self) -> None:
        try:
            tabbar = self.query_one("#tabbar", Static)
            status = self.query_one("#statusbar", Static)
            editor = self.query_one("#editor", OcodeEditor)
        except Exception:
            return
        names: list[str] = []
        for i, t in enumerate(self.tabs.tabs):
            name = t.name if isinstance(t, Path) else "untitled"
            dirty = ""
            if i < len(self.docs) and self.docs[i].doc.dirty:
                dirty = " ●"
            marker = f"[{name}{dirty}]" if i == self.tabs.active else f" {name}{dirty} "
            names.append(marker)
        tabbar.update(" ".join(names) if names else " no files ")
        st = editor.state
        pos = st.cursor
        lang = detect_language(st.doc.path) if st.doc.path else "text"
        enc = st.doc.encoding.upper()
        eol = "CRLF" if st.doc.newline == "\r\n" else "LF"
        dot = "●" if st.doc.dirty else "○"
        fname = st.doc.path.name if st.doc.path else "untitled"
        nmatch = ""
        if st.matches:
            nmatch = f" | {st.match_index + 1}/{len(st.matches)} matches"
        loc = f"Ln {pos.line + 1}, Col {pos.col + 1}"
        info = f"{dot} {fname} | {lang} | {enc} | {eol} | {loc}{nmatch}"
        status.update(info)

    async def on_key(self, event: events.Key) -> None:
        # keep statusbar live after any key the editor handled
        if event.key in ("f3", "shift+f3"):
            return
        self.set_timer(0.05, self.update_chrome)

    # -- actions -------------------------------------------------------
    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar")
        sidebar.display = not sidebar.display

    def action_show_palette(self) -> None:
        self.notify("Command palette lands post-M1 (FR-CMD-001)", timeout=3)

    def action_show_help(self) -> None:
        self.notify("F1 help screen lands post-M1 (UI-008)", timeout=3)

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
        self.notify("Replace-all prompt lands with M1 polish (use API for now)", timeout=3)

    def action_goto_line(self) -> None:
        self.notify("Ctrl+G: type line in find box as :N (full dialog post-M1)", timeout=3)

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
