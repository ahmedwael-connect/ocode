"""Completion popup: Tab/Enter accept, Esc dismiss, Ctrl+Space force (FR-OMLS-010)."""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.message import Message
from textual.widget import Widget

from ocode.engines.omls.complete import Completion


class CompletionAccepted(Message):
    def __init__(self, insert: str, kind: str) -> None:
        super().__init__()
        self.insert = insert
        self.kind = kind


class CompletionPopup(Widget, can_focus=False):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.items: list[Completion] = []
        self.selected = 0
        self.visible = False

    @property
    def is_open(self) -> bool:
        return self.visible and bool(self.items)

    def show(self, items: list[Completion]) -> None:
        self.items = items[:20]
        self.selected = 0
        self.visible = bool(self.items)
        self.set_class(self.visible, "visible")
        self.refresh(layout=True)

    def hide(self) -> None:
        self.visible = False
        self.items = []
        self.set_class(False, "visible")
        self.refresh(layout=True)

    def move(self, delta: int) -> None:
        if self.items:
            self.selected = (self.selected + delta) % len(self.items)
            self.refresh(layout=True)

    def current(self) -> Completion | None:
        if not self.items:
            return None
        return self.items[self.selected % len(self.items)]

    def render(self) -> Text:
        out = Text(no_wrap=True)
        if not self.is_open:
            return out
        for i, c in enumerate(self.items):
            marker = "▸ " if i == self.selected else "  "
            style = "reverse bold" if i == self.selected else ""
            detail = f"  {c.detail}" if c.detail else ""
            out.append(f"{marker}{c.label} [{c.kind}]{detail}\n", style=style)
        return out

    async def on_key(self, event: events.Key) -> None:
        if not self.is_open:
            return
        if event.key in ("up", "down"):
            self.move(-1 if event.key == "up" else 1)
            event.prevent_default()
            event.stop()
        elif event.key in ("tab", "enter"):
            cur = self.current()
            if cur is not None:
                self.post_message(CompletionAccepted(cur.insert, cur.kind))
            event.prevent_default()
            event.stop()
        elif event.key == "escape":
            self.hide()
            event.prevent_default()
            event.stop()
