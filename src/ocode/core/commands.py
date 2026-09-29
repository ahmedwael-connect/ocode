"""Command registry: everything is a command (PRD §3.3, FR-CMD-001/002)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class Command:
    id: str  # e.g. ocode.file.save
    title: str
    handler: Callable[..., object] | None = None
    keybinding: str | None = None
    when: str | None = None


def _fuzzy_score(query: str, text: str) -> int | None:
    """Subsequence match score (lower is better). None = no match."""
    q, t = query.lower(), text.lower()
    pos, score = 0, 0
    for ch in q:
        idx = t.find(ch, pos)
        if idx == -1:
            return None
        score += idx - pos
        pos = idx + 1
    return score


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def register(
        self,
        id: str,
        title: str,
        handler: Callable[..., object] | None = None,
        keybinding: str | None = None,
        when: str | None = None,
    ) -> Command:
        cmd = Command(id=id, title=title, handler=handler, keybinding=keybinding, when=when)
        self._commands[id] = cmd
        return cmd

    def command(
        self, id: str, title: str, keybinding: str | None = None
    ) -> Callable[[Callable[..., object]], Callable[..., object]]:
        def deco(fn: Callable[..., object]) -> Callable[..., object]:
            self.register(id, title, fn, keybinding)
            return fn

        return deco

    def get(self, id: str) -> Command | None:
        return self._commands.get(id)

    def all(self) -> list[Command]:
        return sorted(self._commands.values(), key=lambda c: c.id)

    def search(self, query: str, limit: int = 20) -> list[Command]:
        query = query.strip()
        if not query:
            return self.all()[:limit]
        scored: list[tuple[int, Command]] = []
        for cmd in self._commands.values():
            s = _fuzzy_score(query, f"{cmd.title} {cmd.id}")
            if s is not None:
                scored.append((s, cmd))
        scored.sort(key=lambda item: (item[0], item[1].id))
        return [cmd for _, cmd in scored[:limit]]

    def __len__(self) -> int:
        return len(self._commands)
