"""Problems panel: diagnostics list with jump-to-line (FR-OMLS-020, M4)."""

from __future__ import annotations

from rich.text import Text
from textual.message import Message
from textual.widget import Widget

from ocode.engines.omls.diagnostics import Diagnostic

SEV_STYLE = {"error": "bold red", "warning": "yellow", "info": "cyan", "hint": "dim"}


class ProblemChosen(Message):
    def __init__(self, file: str, line: int) -> None:
        super().__init__()
        self.file = file
        self.line = line


class ProblemsPanel(Widget, can_focus=True):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.items: list[Diagnostic] = []
        self.selected = 0

    def set_items(self, items: list[Diagnostic]) -> None:
        order = {"error": 0, "warning": 1, "info": 2, "hint": 3}
        self.items = sorted(items, key=lambda d: (order.get(d.severity, 4), d.file, d.line))
        self.selected = 0
        self.refresh(layout=True)

    def counts(self) -> tuple[int, int]:
        errors = sum(1 for d in self.items if d.severity == "error")
        warns = sum(1 for d in self.items if d.severity == "warning")
        return (errors, warns)

    def move(self, delta: int) -> None:
        if self.items:
            self.selected = (self.selected + delta) % len(self.items)
            self.refresh(layout=True)

    def current(self) -> Diagnostic | None:
        if not self.items:
            return None
        return self.items[self.selected % len(self.items)]

    def render(self) -> Text:
        out = Text(no_wrap=True)
        if not self.items:
            out.append("No problems ✓", style="green")
            return out
        errors, warns = self.counts()
        out.append(f"{errors} errors, {warns} warnings\n", style="bold")
        height = max(1, self.size.height - 1)
        start = max(0, self.selected - height + 1)
        for i, d in enumerate(self.items[start : start + height]):
            idx = start + i
            marker = "▸ " if idx == self.selected else "  "
            style = "reverse" if idx == self.selected else ""
            short = d.file.split("/")[-1]
            out.append(f"{marker}{d.severity.upper()} ", style=SEV_STYLE.get(d.severity, ""))
            out.append(f"{short}:{d.line} [{d.code}] {d.message}\n", style=style)
        return out

    async def on_click(self, event: object) -> None:
        _ = event

    def open_selected(self) -> None:
        cur = self.current()
        if cur is not None:
            self.post_message(ProblemChosen(cur.file, cur.line))
