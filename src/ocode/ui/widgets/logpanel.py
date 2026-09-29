"""Log panel widget: level colors, filters, traceback expand + click-to-open (FR-OSS-030..036)."""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.message import Message
from textual.widget import Widget

from ocode.engines.oss.logs import (
    LEVELS,
    LogBuffer,
    LogFilter,
    LogRecord,
    extract_file_links,
    group_tracebacks,
)


class LogLinkClicked(Message):
    def __init__(self, path: str, line: int) -> None:
        super().__init__()
        self.path = path
        self.line = line


LEVEL_STYLE: dict[str, str] = {
    "DEBUG": "dim",
    "INFO": "",
    "WARNING": "yellow",
    "ERROR": "bold red",
    "CRITICAL": "bold white on red",
}


class LogPanel(Widget, can_focus=True):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.buffer = LogBuffer()
        self.filter = LogFilter()
        self.paused = False
        self.wrap = False
        self._expanded: set[int] = set()
        self._stick_bottom = True
        self._pending: list[str] = []

    # -- feed ----------------------------------------------------------
    def feed_record(self, rec: LogRecord) -> None:
        if self.paused:
            self._pending.append(rec.raw)
        self.refresh(layout=True)

    def feed_text(self, text: str) -> None:
        for ln in text.splitlines():
            self.buffer.append_raw(ln)
        if not self.paused:
            self.refresh(layout=True)

    def flush_paused(self) -> None:
        self._pending.clear()
        self.refresh(layout=True)

    def set_levels(self, levels: set[str]) -> None:
        self.filter.levels = set(levels)
        self.refresh(layout=True)

    def set_text_filter(self, text: str, regex: bool = False) -> None:
        self.filter.text = text
        self.filter.use_regex = regex
        self.refresh(layout=True)

    def toggle_pause(self) -> bool:
        self.paused = not self.paused
        if not self.paused:
            self.flush_paused()
        return self.paused

    def clear(self) -> None:
        self.buffer.clear()
        self._expanded.clear()
        self._pending.clear()
        self.refresh(layout=True)

    def visible_links(self) -> list[tuple[str, int]]:
        out: list[tuple[str, int]] = []
        for rec in self.buffer.filtered(self.filter)[-500:]:
            out.extend(extract_file_links(rec.raw))
        return out

    # -- render --------------------------------------------------------
    def render(self) -> Text:
        recs = self.buffer.filtered(self.filter)
        height = max(1, self.size.height)
        width = max(20, self.size.width)
        blocks = {b.start: b for b in group_tracebacks(recs)}
        # map record index → collapsed hidden set
        hidden: set[int] = set()
        for start, block in blocks.items():
            if start not in self._expanded and block.end - start > 3:
                hidden.update(range(start + 2, block.end + 1))
        lines: list[tuple[LogRecord, bool]] = []
        for i, rec in enumerate(recs):
            if i in hidden:
                continue
            lines.append((rec, i in blocks))
        if self._stick_bottom and not self.paused:
            lines = lines[-height:]
        else:
            lines = lines[-height:]
        out = Text(no_wrap=not self.wrap)
        for idx, (rec, is_tb) in enumerate(lines):
            style = LEVEL_STYLE.get(rec.level, "")
            line = rec.raw if self.wrap else rec.raw[:width]
            if is_tb:
                line = f"▸ {line}"
            out.append(line, style=style)
            links = extract_file_links(rec.raw)
            for path, lineno in links:
                out.append(f"  ↪ {path}:{lineno}", style="bold cyan underline")
            if idx < len(lines) - 1:
                out.append("\n")
        if self.paused:
            out.append(f"\n⏸ paused ({len(self._pending)} buffered)", style="yellow")
        return out

    def toggle_traceback_at(self, visible_index: int) -> None:
        recs = self.buffer.filtered(self.filter)
        blocks = group_tracebacks(recs)
        tail = recs[-max(1, self.size.height) :]
        if 0 <= visible_index < len(tail):
            # find block containing this record
            rec = tail[visible_index]
            try:
                idx = recs.index(rec)
            except ValueError:
                return
            for b in blocks:
                if b.start <= idx <= b.end:
                    if b.start in self._expanded:
                        self._expanded.discard(b.start)
                    else:
                        self._expanded.add(b.start)
                    self.refresh(layout=True)
                    return

    async def on_click(self, event: events.Click) -> None:
        y = event.y
        recs = self.buffer.filtered(self.filter)
        tail = recs[-max(1, self.size.height) :]
        if 0 <= y < len(tail):
            links = extract_file_links(tail[y].raw)
            if links:
                path, lineno = links[0]
                self.post_message(LogLinkClicked(path, lineno))
                event.prevent_default()
                event.stop()

    async def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            # expand most recent traceback
            recs = self.buffer.filtered(self.filter)
            blocks = group_tracebacks(recs)
            if blocks:
                start = blocks[-1].start
                if start in self._expanded:
                    self._expanded.discard(start)
                else:
                    self._expanded.add(start)
                self.refresh(layout=True)
                event.prevent_default()
                event.stop()


def level_badge(buffer: LogBuffer) -> str:
    if buffer.error_count:
        return f"E:{buffer.error_count}"
    if buffer.warn_count:
        return f"W:{buffer.warn_count}"
    return ""


__all__ = ["LEVELS", "LogLinkClicked", "LogPanel", "level_badge"]
