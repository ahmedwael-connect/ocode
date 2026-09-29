"""Undo/redo with grouping (FR-OTE-030: bursts/commands undo atomically)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EditOp:
    kind: str  # "insert" | "delete"
    offset: int
    text: str  # inserted text, or deleted text


class UndoStack:
    def __init__(self, limit: int = 1000) -> None:
        self._undo: list[list[EditOp]] = []
        self._redo: list[list[EditOp]] = []
        self._open_group: list[EditOp] | None = None
        self._limit = limit

    def begin_group(self) -> None:
        if self._open_group is None:
            self._open_group = []

    def end_group(self) -> None:
        if self._open_group:
            self._undo.append(self._open_group)
            self._trim()
            self._redo.clear()
        self._open_group = None

    def _trim(self) -> None:
        while len(self._undo) > self._limit:
            self._undo.pop(0)

    def push(self, op: EditOp) -> None:
        if self._open_group is not None:
            self._open_group.append(op)
        else:
            self._undo.append([op])
            self._trim()
            self._redo.clear()

    def can_undo(self) -> bool:
        return bool(self._undo) or bool(self._open_group and self._open_group)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def pop_undo(self) -> list[EditOp] | None:
        if self._open_group:
            group = self._open_group
            self._open_group = None
            if group:
                self._redo.append(group)
                return group
        if not self._undo:
            return None
        group = self._undo.pop()
        self._redo.append(group)
        return group

    def pop_redo(self) -> list[EditOp] | None:
        if not self._redo:
            return None
        group = self._redo.pop()
        self._undo.append(group)
        return group

    def clear_redo(self) -> None:
        self._redo.clear()

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self._open_group = None

    def depth(self) -> tuple[int, int]:
        extra = 1 if self._open_group else 0
        return (len(self._undo) + extra, len(self._redo))
