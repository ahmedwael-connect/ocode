"""Tab state model (FR-SMN-012 subset for M1): open files, dirty, MRU."""

from __future__ import annotations

from pathlib import Path


class TabState:
    def __init__(self) -> None:
        self.tabs: list[Path | None] = []
        self.active = -1
        self._mru: list[int] = []

    def __len__(self) -> int:
        return len(self.tabs)

    def open(self, path: Path | None) -> int:
        for i, t in enumerate(self.tabs):
            if t == path and path is not None:
                self.activate(i)
                return i
        self.tabs.append(path)
        self.activate(len(self.tabs) - 1)
        return self.active

    def close(self, index: int) -> Path | None:
        if not 0 <= index < len(self.tabs):
            return None
        removed = self.tabs.pop(index)
        self._mru = [i for i in self._mru if i != index]
        self._mru = [i - 1 if i > index else i for i in self._mru]
        if not self.tabs:
            self.active = -1
        else:
            self.active = min(index, len(self.tabs) - 1)
        return removed

    def activate(self, index: int) -> None:
        if 0 <= index < len(self.tabs):
            self.active = index
            if index in self._mru:
                self._mru.remove(index)
            self._mru.append(index)

    def mru_order(self) -> list[int]:
        return list(reversed(self._mru))

    def move(self, frm: int, to: int) -> None:
        if 0 <= frm < len(self.tabs) and 0 <= to < len(self.tabs):
            tab = self.tabs.pop(frm)
            self.tabs.insert(to, tab)
            self.active = to
