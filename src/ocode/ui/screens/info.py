"""Info screens: hover documentation popup (FR-OTE-080 subset, M4)."""

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
        yield Static(f"❓ {self._title}", id="hover-title")
        yield Static(self._body, id="hover-body")
        yield Static("Esc to close", id="hover-hint")

    async def on_key(self, event: events.Key) -> None:
        self.dismiss(None)


__all__ = ["HoverScreen"]
