"""Git screens: stage/commit panel (FR-GIT-003 basics, M7)."""

from __future__ import annotations

from pathlib import Path

from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from ocode.engines.git.repo import commit, porcelain, stage_all_tracked


class GitCommitScreen(ModalScreen[bool | None]):
    """Show status, stage tracked changes, commit with message."""

    def __init__(self, root: Path) -> None:
        super().__init__()
        self._root = root

    def compose(self) -> ComposeResult:
        lines = porcelain(self._root)
        yield Static(f"git: {self._root}  (Enter=stage all + commit, Esc=cancel)")
        yield Static("\n".join(lines) if lines else "(clean)", id="git-status")
        yield Input(placeholder="commit message", id="git-msg")

    def on_mount(self) -> None:
        try:
            self.query_one("#git-msg", Input).focus()
        except Exception:
            pass

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "git-msg":
            return
        msg = event.value.strip()
        if not msg:
            self.dismiss(None)
            return
        ok = stage_all_tracked(self._root) and commit(self._root, msg)
        self.dismiss(ok)

    async def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)


__all__ = ["GitCommitScreen"]
