"""Textual app shell (M0). Full layout/panels land in M1-M3 (PRD §5)."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Label, Static

from ocode import __version__
from ocode.core.commands import CommandRegistry
from ocode.core.config import OcodeConfig
from ocode.core.events import EventBus
from ocode.core.tasks import TaskScheduler


def build_default_commands() -> CommandRegistry:
    reg = CommandRegistry()
    reg.register("ocode.file.save", "File: Save", keybinding="ctrl+s")
    reg.register("ocode.palette.open", "Show Command Palette", keybinding="ctrl+shift+p")
    reg.register("ocode.quickopen.open", "Go to File...", keybinding="ctrl+p")
    reg.register("ocode.sidebar.toggle", "Toggle Sidebar", keybinding="ctrl+b")
    reg.register("ocode.oss.restart", "Odoo: Restart Server", keybinding="f5")
    reg.register("ocode.app.quit", "Quit", keybinding="ctrl+q")
    return reg


class OcodeApp(App[None]):
    """M0 shell: explorer + editor placeholder + status bar."""

    CSS_PATH = "ui/default.tcss"
    TITLE = "ocode"
    SUB_TITLE = "Odoo-aware terminal editor (M0 shell)"

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+b", "toggle_sidebar", "Sidebar"),
        ("ctrl+shift+p", "show_palette", "Palette"),
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

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Static("EXPLORER (M0)", id="sidebar-title")
                yield Label(str(self.start_path))
            with Vertical(id="editor-area"):
                yield Static(
                    f"ocode v{__version__}\n\nEmpty shell (M0).\n"
                    f"Opened: {self.start_path}\n\n"
                    "Press F1 for help, Ctrl+Q to quit.",
                    id="editor-placeholder",
                )
        yield Static(
            f"● Stopped | db: — | odoo: — | {self.start_path.name} | UTF-8 | LF",
            id="statusbar",
        )
        yield Footer()

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar")
        sidebar.display = not sidebar.display

    def action_show_palette(self) -> None:
        self.notify("Command palette lands in M1 (FR-CMD-001)", timeout=3)

    def action_show_help(self) -> None:
        self.notify("F1 help screen lands in M1 (UI-008)", timeout=3)
