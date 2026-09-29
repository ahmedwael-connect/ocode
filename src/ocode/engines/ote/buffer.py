"""Piece-table text buffer (FR-OTE-001).

Classic design: immutable `original` + append-only `added` buffers,
sequence of pieces (source, start, length). Offsets indexed with a
cumulative-length table + bisect → O(log p) lookup, O(p) splice.
Snapshots are cheap (pieces tuple copy).
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass


@dataclass
class _Piece:
    source: int  # 0 = original, 1 = added
    start: int
    length: int


ORIGINAL = 0
ADDED = 1


class PieceTable:
    def __init__(self, text: str = "") -> None:
        self._original = text
        self._added = ""
        self._pieces: list[_Piece] = []
        if text:
            self._pieces.append(_Piece(ORIGINAL, 0, len(text)))
        self._cum: list[int] = []
        self._rebuild()

    def _rebuild(self) -> None:
        cum: list[int] = []
        total = 0
        for p in self._pieces:
            total += p.length
            cum.append(total)
        self._cum = cum

    def __len__(self) -> int:
        return self._cum[-1] if self._cum else 0

    @property
    def text(self) -> str:
        out: list[str] = []
        for p in self._pieces:
            buf = self._original if p.source == ORIGINAL else self._added
            out.append(buf[p.start : p.start + p.length])
        return "".join(out)

    def _locate(self, offset: int) -> tuple[int, int]:
        """Return (piece_index, inner_offset). offset may equal len (EOF)."""
        if offset < 0 or offset > len(self):
            raise IndexError(f"offset {offset} out of range 0..{len(self)}")
        if not self._pieces:
            return (0, 0)
        idx = bisect.bisect_right(self._cum, offset)
        if idx >= len(self._pieces):
            return (len(self._pieces), 0)
        prev = self._cum[idx - 1] if idx > 0 else 0
        return (idx, offset - prev)

    def _source_text(self, piece: _Piece) -> str:
        buf = self._original if piece.source == ORIGINAL else self._added
        return buf[piece.start : piece.start + piece.length]

    def insert(self, offset: int, text: str) -> None:
        if not text:
            return
        if not self._pieces:
            astart = len(self._added)
            self._added += text
            self._pieces.append(_Piece(ADDED, astart, len(text)))
            self._rebuild()
            return
        idx, inner = self._locate(offset)
        astart = len(self._added)
        self._added += text
        new = _Piece(ADDED, astart, len(text))
        if idx >= len(self._pieces):
            # append at EOF (merge with previous added piece if contiguous)
            prev = self._pieces[-1]
            if prev.source == ADDED and prev.start + prev.length == astart:
                prev.length += len(text)
            else:
                self._pieces.append(new)
            self._rebuild()
            return
        cur = self._pieces[idx]
        if inner == 0:
            self._pieces.insert(idx, new)
        elif inner == cur.length:
            self._pieces.insert(idx + 1, new)
        else:
            left = _Piece(cur.source, cur.start, inner)
            right = _Piece(cur.source, cur.start + inner, cur.length - inner)
            self._pieces[idx : idx + 1] = [left, new, right]
        self._rebuild()

    def delete(self, offset: int, length: int) -> str:
        """Delete [offset, offset+length), return removed text."""
        if length <= 0:
            return ""
        if offset < 0 or offset + length > len(self):
            raise IndexError("delete range out of bounds")
        removed: list[str] = []
        end = offset + length
        new_pieces: list[_Piece] = []
        pos = 0
        for p in self._pieces:
            p_end = pos + p.length
            if p_end <= offset or pos >= end:
                new_pieces.append(p)
            else:
                cut_l = max(0, offset - pos)
                cut_r = max(0, p_end - end)
                if cut_l == 0 and cut_r == 0:
                    removed.append(self._source_text(p))
                else:
                    full = self._source_text(p)
                    removed.append(full[cut_l : len(full) - cut_r if cut_r else len(full)])
                    if cut_l:
                        new_pieces.append(_Piece(p.source, p.start, cut_l))
                    if cut_r:
                        new_pieces.append(
                            _Piece(p.source, p.start + p.length - cut_r, cut_r)
                        )
            pos = p_end
        self._pieces = [p for p in new_pieces if p.length > 0]
        self._rebuild()
        return "".join(removed)

    def snapshot(self) -> tuple[_Piece, ...]:
        return tuple(_Piece(p.source, p.start, p.length) for p in self._pieces)

    def restore(self, snap: tuple[_Piece, ...]) -> None:
        self._pieces = [_Piece(p.source, p.start, p.length) for p in snap]
        self._rebuild()

    # -- line helpers ----------------------------------------------------
    def lines(self) -> list[str]:
        return self.text.split("\n")

    def line_count(self) -> int:
        if len(self) == 0:
            return 1
        return self.text.count("\n") + 1

    def offset_of(self, line: int, col: int) -> int:
        """0-based line/col → offset (clamped)."""
        lines = self.lines()
        line = max(0, min(line, len(lines) - 1))
        col = max(0, min(col, len(lines[line])))
        return sum(len(lines[i]) + 1 for i in range(line)) + col

    def position_of(self, offset: int) -> tuple[int, int]:
        offset = max(0, min(offset, len(self)))
        text = self.text[:offset]
        line = text.count("\n")
        col = offset - (text.rfind("\n") + 1)
        return (line, col)
