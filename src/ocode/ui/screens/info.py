"""Info screens: hover popup + help cheat-sheet (FR-OTE-080, UI-008)."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static


class HoverScreen(ModalScreen[None]):
    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        yield Static(f"? {self._title}", id="hover-title")
        yield Static(self._body, id="hover-body")
        yield Static("Esc to close", id="hover-hint")

    async def on_key(self, event: events.Key) -> None:
        self.dismiss(None)


HELP_SECTIONS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("Files & navigation", (
        ("Ctrl+P", "Quick open"),
        ("Ctrl+Shift+M", "Switch module"),
        ("Alt+M / Ctrl+K M", "Related file cycle"),
        ("Alt+R / Ctrl+K R", "Related files popup"),
        ("F12", "Go to definition"),
        ("Shift+F12", "Find references"),
        ("Ctrl+Shift+F", "Search in files"),
        ("Ctrl+B / Ctrl+0 / Ctrl+1", "Sidebar / tree / editor"),
    )),
    ("Editing", (
        ("Ctrl+S", "Save"),
        ("Ctrl+Z / Ctrl+Y", "Undo / redo"),
        ("Ctrl+D", "Next occurrence (multi-cursor)"),
        ("Ctrl+/", "Toggle comment"),
        ("Alt+Up/Down", "Move line"),
        ("Ctrl+F / F3", "Find / next match"),
        ("Ctrl+G", "Go to line (:N in find box)"),
        ("Vim modal (toggle)", "h j k l w b e 0 $ G, d/y/c + motion, dd yy p, x, u, v, /, :w :q"),
    )),
    ("Odoo intelligence", (
        ("Ctrl+Space", "Completion"),
        ("Tab", "Accept completion / expand snippet"),
        ("F8 / Ctrl+F8", "Lint file / module"),
        ("Ctrl+.", "Quick fix"),
        ("Ctrl+K I", "Hover info"),
        ("Ctrl+Shift+O", "Outline/symbols"),
        ("F4 / Shift+F4", "Next / previous problem"),
    )),
    ("Server & shell", (
        ("F6", "Start / stop server"),
        ("F5", "Restart server"),
        ("Ctrl+F5", "Restart + update current module"),
        ("Ctrl+Shift+F5", "Update modules..."),
        ("F9", "Databases (list/select/backup/duplicate/drop)"),
        ("Ctrl+` / F7", "Odoo shell (Ctrl+` may not reach app in some terminals)"),
        ("Ctrl+Enter", "Send line/selection to shell"),
        ("Ctrl+J", "Cycle bottom panel (Logs/Shell/Problems)"),
    )),
    ("Generate", (
        ("Ctrl+Shift+N", "Generators (module/model/view/...)"),
        ("F1", "This help"),
        ("Ctrl+Q", "Quit"),
    )),
)


class HelpScreen(ModalScreen[None]):
    """Built-in help + keybinding cheat-sheet (UI-008)."""

    def compose(self) -> ComposeResult:
        yield Static("ocode — keys (Esc closes)", id="help-title")
        lines: list[str] = []
        for section, rows in HELP_SECTIONS:
            lines.append(f"== {section} ==")
            for key, action in rows:
                lines.append(f"  {key:28} {action}")
        yield Static("\n".join(lines), id="help-body")

    async def on_key(self, event: events.Key) -> None:
        self.dismiss(None)


__all__ = ["HELP_SECTIONS", "HelpScreen", "HoverScreen"]
