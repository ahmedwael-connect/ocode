"""Find bar: incremental in-file search (FR-OTE-060, M1)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Checkbox, Input

from ocode.engines.ote.search import FindOptions


class FindBar(Widget):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.visible = False

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Input(placeholder="Find (Enter=next, Esc=close)", id="find-input")
            yield Checkbox("Regex", id="find-regex")
            yield Checkbox("Case", id="find-case")
            yield Checkbox("Word", id="find-word")

    def options(self) -> FindOptions:
        try:
            pattern = self.query_one("#find-input", Input).value
            regex = self.query_one("#find-regex", Checkbox).value
            case = self.query_one("#find-case", Checkbox).value
            word = self.query_one("#find-word", Checkbox).value
        except Exception:
            pattern, regex, case, word = "", False, False, False
        return FindOptions(pattern=pattern, regex=regex, case_sensitive=case, whole_word=word)
