"""Command palette: fuzzy search over registered commands (FR-CMD-001/002)."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from ocode.engines.smn.search import quick_open


class CommandPalette(ModalScreen[str | None]):
    """Dismisses with the chosen command id (or None on cancel)."""

    def __init__(self, items: list[tuple[str, str, str]]) -> None:
        """Items: (id, title, keybinding-or-empty)."""
        super().__init__()
        self._all = items
        self._labels = [f"{title}  [{key}]" if key else title for _, title, key in items]
        self._filtered: list[str] = list(self._labels)
        self._ids: list[str] = [cid for cid, _, _ in items]

    def compose(self) -> ComposeResult:
        yield Static("Command palette (Enter=run, Esc=cancel)")
        yield Input(placeholder="type a command...", id="pal-input")
        yield OptionList(id="pal-list")

    def on_mount(self) -> None:
        self._refresh(self._labels)
        self.query_one("#pal-input", Input).focus()

    def _refresh(self, labels: list[str]) -> None:
        self._filtered = labels
        lst = self.query_one("#pal-list", OptionList)
        lst.clear_options()
        for label in labels[:40]:
            lst.add_option(Option(label, id=label))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "pal-input":
            return
        hits = quick_open(self._labels, event.value, limit=40)
        self._refresh(hits if event.value.strip() else self._labels[:40])

    def _pick_id(self, label: str) -> str | None:
        try:
            return self._ids[self._labels.index(label)]
        except ValueError:
            return None

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        prompt = event.option.prompt
        label = prompt if isinstance(prompt, str) else str(prompt)
        self.dismiss(self._pick_id(label))

    async def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            lst = self.query_one("#pal-list", OptionList)
            idx = lst.highlighted or 0
            if self._filtered:
                self.dismiss(self._pick_id(self._filtered[max(0, idx)]))
            else:
                self.dismiss(None)


__all__ = ["CommandPalette"]
