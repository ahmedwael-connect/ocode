"""Shell panel: PTY screen renderer + line input with history (FR-OSH-001/002)."""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.message import Message
from textual.widget import Widget

from ocode.engines.osh.shell import ShellSession, is_production_db


class ShellExited(Message):
    pass


class ShellPanel(Widget, can_focus=True):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.session: ShellSession | None = None
        self.input = ""

    @property
    def running(self) -> bool:
        return self.session is not None and self.session.alive

    def attach(self, session: ShellSession) -> None:
        self.session = session
        self.input = ""
        self.refresh(layout=True)

    def detach(self) -> None:
        self.session = None
        self.input = ""
        self.refresh(layout=True)

    def render(self) -> Text:
        out = Text(no_wrap=True)
        height = max(3, self.size.height)
        if self.session is None:
            out.append("Shell not running — Ctrl+` to start (odoo shell -d <db>)",
                       style="dim")
            return out
        db = self.session.db or "?"
        prod = is_production_db(self.session.db)
        out.append(f"— shell · db: {db}", style="bold red" if prod else "bold green")
        if prod:
            out.append("  ⚠ PRODUCTION", style="bold white on red")
        out.append("\n")
        lines = self.session.screen_lines()
        for ln in lines[-(height - 2) :]:
            out.append(ln[: max(20, self.size.width)] + "\n")
        out.append(f"› {self.input}", style="bold cyan")
        return out

    def submit_input(self) -> None:
        sess = self.session
        if sess is None or not sess.alive:
            self.post_message(ShellExited())
            return
        try:
            sess.send(self.input)
        except (OSError, RuntimeError):
            self.post_message(ShellExited())
            return
        self.input = ""
        self.refresh(layout=True)

    async def on_key(self, event: events.Key) -> None:
        sess = self.session
        if sess is None or not sess.alive:
            return
        key = event.key
        if key == "enter":
            self.submit_input()
        elif key == "backspace":
            self.input = self.input[:-1]
            self.refresh(layout=True)
        elif key == "up":
            self.input = sess.history_prev()
            self.refresh(layout=True)
        elif key == "down":
            self.input = sess.history_next()
            self.refresh(layout=True)
        elif key == "ctrl+c":
            sess.send_bytes(b"\x03")
        elif key == "ctrl+d":
            sess.send_bytes(b"\x04")
        elif event.is_printable:
            ch = event.character or ""
            if not ch and len(key) == 1:
                ch = key
            if ch:
                self.input += ch
                self.refresh(layout=True)
            else:
                return
        else:
            # arrows etc. go straight to the pty
            if key in ("left", "right", "tab", "escape"):
                sess.send_key(key)
            else:
                return
        event.prevent_default()
        event.stop()
