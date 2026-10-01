"""DB screens: manager list + name prompt (FR-OSS-026, M7)."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option


class DbScreen(ModalScreen[tuple[str, str] | None]):
    """List databases. Enter=use, b=backup, c=duplicate, x=drop, Esc=cancel."""

    def __init__(self, dbs: list[tuple[str, str]], current: str) -> None:
        super().__init__()
        self._dbs = dbs
        self._current = current

    def compose(self) -> ComposeResult:
        yield Static("Databases (Enter=use · b=backup · c=duplicate · x=drop · Esc)", id="db-title")
        yield OptionList(id="db-list")

    def on_mount(self) -> None:
        lst = self.query_one("#db-list", OptionList)
        for name, size in self._dbs:
            mark = "● " if name == self._current else "  "
            lst.add_option(Option(f"{mark}{name}  ({size})", id=name))
        lst.focus()

    def _highlighted(self) -> str:
        lst = self.query_one("#db-list", OptionList)
        idx = lst.highlighted or 0
        if 0 <= idx < len(self._dbs):
            return self._dbs[idx][0]
        return ""

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        opt_id = str(event.option.id or "")
        if opt_id:
            self.dismiss(("select", opt_id))

    async def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key in ("b", "c", "x"):
            name = self._highlighted()
            if name:
                action = {"b": "backup", "c": "duplicate", "x": "drop"}[event.key]
                self.dismiss((action, name))


class NameScreen(ModalScreen[str | None]):
    """Single-line prompt (duplicate target, backup destination)."""

    def __init__(self, prompt: str, initial: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._initial = initial

    def compose(self) -> ComposeResult:
        yield Static(self._prompt, id="name-prompt")
        yield Input(value=self._initial, id="name-input")

    def on_mount(self) -> None:
        try:
            self.query_one("#name-input", Input).focus()
        except Exception:
            pass

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "name-input":
            value = event.value.strip()
            self.dismiss(value or None)

    async def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)


__all__ = ["DbScreen", "NameScreen"]
