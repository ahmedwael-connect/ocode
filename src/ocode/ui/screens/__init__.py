"""Filter/Quick-open/Grep screens (FR-SMN-013/030..035, M2)."""

from __future__ import annotations

from pathlib import Path

from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from ocode.engines.smn.search import ContentHit, content_search, quick_open


class FilterScreen(ModalScreen[Path | None]):
    """Generic fuzzy-pick screen over string candidates → Path."""

    def __init__(self, title: str, candidates: list[str], base: Path | None = None) -> None:
        super().__init__()
        self._title = title
        self._candidates = candidates
        self._base = base
        self._filtered: list[str] = candidates[:40]

    def compose(self) -> ComposeResult:
        yield Static(self._title)
        yield Input(placeholder="type to filter, Enter=open, Esc=cancel", id="filter-input")
        yield OptionList(id="filter-list")

    def on_mount(self) -> None:
        self._refresh_list(self._candidates[:40])
        self.query_one("#filter-input", Input).focus()

    def _refresh_list(self, items: list[str]) -> None:
        self._filtered = items
        lst = self.query_one("#filter-list", OptionList)
        lst.clear_options()
        for item in items[:40]:
            lst.add_option(Option(item, id=item))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "filter-input":
            return
        self._refresh_list(quick_open(self._candidates, event.value, limit=40))

    def _resolve(self, text: str) -> Path:
        p = Path(text)
        if p.is_absolute():
            return p
        if self._base is not None:
            return self._base / text
        return Path(text)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        opt = event.option
        prompt = opt.prompt if isinstance(opt.prompt, str) else str(opt.prompt)
        self.dismiss(self._resolve(prompt))

    async def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            # pick highlighted or first filtered
            lst = self.query_one("#filter-list", OptionList)
            idx = lst.highlighted or 0
            if self._filtered:
                self.dismiss(self._resolve(self._filtered[max(0, idx)]))
            else:
                self.dismiss(None)


class GrepScreen(ModalScreen[Path | None]):
    """Content search: pattern → rg/fallback hits → pick to open."""

    def __init__(self, roots: list[Path]) -> None:
        super().__init__()
        self._roots = roots
        self._hits: list[ContentHit] = []

    def compose(self) -> ComposeResult:
        yield Static("Search in files (rg if available, else built-in)")
        yield Input(placeholder="pattern, Enter=search", id="grep-input")
        yield OptionList(id="grep-list")

    def on_mount(self) -> None:
        self.query_one("#grep-input", Input).focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "grep-input":
            return
        pattern = event.value.strip()
        if not pattern:
            return
        lst = self.query_one("#grep-list", OptionList)
        lst.clear_options()
        lst.add_option(Option("searching…", id="busy"))
        hits = content_search(pattern, self._roots, max_hits=200)
        self._hits = hits
        lst.clear_options()
        if not hits:
            lst.add_option(Option("no matches", id="none"))
            return
        for i, h in enumerate(hits[:200]):
            label = f"{h.path}:{h.line}:{h.col} {h.snippet}"
            lst.add_option(Option(label, id=str(i)))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        opt_id = event.option.id
        if opt_id in (None, "busy", "none"):
            return
        try:
            hit = self._hits[int(str(opt_id))]
        except (ValueError, IndexError):
            return
        self.app.pop_screen()
        cb = getattr(self.app, "open_hit", None)
        if callable(cb):
            cb(hit)

    async def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
