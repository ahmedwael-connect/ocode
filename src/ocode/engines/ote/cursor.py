"""Cursor, selection, multi-cursor models (FR-OTE-010..012)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Position:
    line: int = 0
    col: int = 0


@dataclass
class Selection:
    anchor: Position
    active: Position

    @property
    def is_caret(self) -> bool:
        return self.anchor == self.active

    def ordered(self) -> tuple[Position, Position]:
        if self.anchor <= self.active:
            return (self.anchor, self.active)
        return (self.active, self.anchor)


@dataclass
class Cursor:
    pos: Position
    sel: Selection | None = None  # None = plain caret

    @property
    def has_selection(self) -> bool:
        return self.sel is not None and not self.sel.is_caret


class CursorSet:
    """Primary cursor at index 0; others sorted/deduped."""

    def __init__(self, cursors: list[Cursor] | None = None) -> None:
        self._cursors: list[Cursor] = cursors or [Cursor(Position(0, 0))]

    @property
    def primary(self) -> Cursor:
        return self._cursors[0]

    def all(self) -> list[Cursor]:
        return list(self._cursors)

    def __len__(self) -> int:
        return len(self._cursors)

    def set_primary(self, pos: Position, sel: Selection | None = None) -> None:
        self._cursors[0] = Cursor(pos, sel)

    def add(self, pos: Position) -> bool:
        if any(c.pos == pos for c in self._cursors):
            return False
        self._cursors.append(Cursor(pos))
        return True

    def collapse_all(self) -> None:
        self._cursors = [self._cursors[0]]

    def clear_selections(self) -> None:
        self._cursors = [Cursor(c.pos) for c in self._cursors]

    def sort_for_edit(self) -> list[Cursor]:
        """Cursors ordered last→first so offsets stay valid during edits."""
        return sorted(self._cursors, key=lambda c: c.pos, reverse=True)
