"""Headless editor state: Document + cursors + search + line ops (M1).

The Textual widget (`ui/widgets/editor.py`) is a thin renderer over this,
so all editing logic is unit-testable without a TUI.
"""

from __future__ import annotations

import re
from pathlib import Path

from ocode.engines.ote.cursor import CursorSet, Position, Selection
from ocode.engines.ote.document import Document
from ocode.engines.ote.search import FindOptions, Match, SearchEngine

_WORD_RE = re.compile(r"\w+|[^\w\s]+")


class EditorState:
    def __init__(self, doc: Document | None = None, tab_width: int = 4) -> None:
        self.doc = doc or Document()
        self.cursors = CursorSet()
        self.search = SearchEngine()
        self.tab_width = tab_width
        self.matches: list[Match] = []
        self.match_index = -1
        self.last_find: FindOptions | None = None

    # -- position helpers --------------------------------------------
    def lines(self) -> list[str]:
        return self.doc.buffer.lines()

    def clamp(self, pos: Position) -> Position:
        lines = self.lines()
        line = max(0, min(pos.line, len(lines) - 1))
        col = max(0, min(pos.col, len(lines[line])))
        return Position(line, col)

    def pos_to_offset(self, pos: Position) -> int:
        pos = self.clamp(pos)
        return self.doc.buffer.offset_of(pos.line, pos.col)

    def offset_to_pos(self, offset: int) -> Position:
        line, col = self.doc.buffer.position_of(offset)
        return Position(line, col)

    @property
    def cursor(self) -> Position:
        return self.cursors.primary.pos

    def set_cursor(self, pos: Position) -> None:
        self.cursors.set_primary(self.clamp(pos))

    # -- movement ------------------------------------------------------
    def move(self, dline: int = 0, dcol: int = 0, select: bool = False) -> None:
        cur = self.cursors.primary
        base = cur.sel.active if (select and cur.sel) else cur.pos
        nxt = self.clamp(Position(base.line + dline, base.col + dcol))
        if select:
            anchor = cur.sel.anchor if cur.sel else cur.pos
            self.cursors.set_primary(nxt, Selection(anchor, nxt))
        else:
            self.cursors.set_primary(nxt)

    def move_to(self, pos: Position, select: bool = False) -> None:
        self.move(pos.line - self.cursor.line, pos.col - self.cursor.col, select)

    def home(self, select: bool = False) -> None:
        line = self.cursor.line
        text = self.lines()[line]
        first_nb = len(text) - len(text.lstrip(" \t"))
        target = 0 if self.cursor.col == first_nb else first_nb
        self.move_to(Position(line, target), select)

    def line_end(self, select: bool = False) -> None:
        line = self.cursor.line
        self.move_to(Position(line, len(self.lines()[line])), select)

    def move_word(self, direction: int = 1, select: bool = False) -> None:
        off = self.pos_to_offset(self.cursor)
        text = self.doc.text
        if direction > 0:
            m = re.search(r"\s*\S", text[off + 1 :]) if off + 1 < len(text) else None
            # simpler: next word start
            nxt = off
            while nxt < len(text) and not text[nxt].isspace():
                nxt += 1
            while nxt < len(text) and text[nxt].isspace():
                nxt += 1
            _ = m
        else:
            nxt = off - 1
            while nxt > 0 and text[nxt - 1].isspace():
                nxt -= 1
            while nxt > 0 and not text[nxt - 1].isspace():
                nxt -= 1
        self.move_to(self.offset_to_pos(nxt), select)

    def goto_line(self, lineno_1b: int) -> None:
        self.set_cursor(Position(max(0, lineno_1b - 1), 0))

    # -- selection -----------------------------------------------------
    def select_all(self) -> None:
        lines = self.lines()
        self.cursors.set_primary(
            Position(len(lines) - 1, len(lines[-1])),
            Selection(Position(0, 0), Position(len(lines) - 1, len(lines[-1]))),
        )

    def select_line(self) -> None:
        line = self.cursor.line
        text = self.lines()[line]
        end = Position(line, len(text))
        self.cursors.set_primary(end, Selection(Position(line, 0), end))

    def selected_text(self) -> str | None:
        cur = self.cursors.primary
        if not cur.has_selection or cur.sel is None:
            return None
        a, b = cur.sel.ordered()
        return self.doc.text[self.pos_to_offset(a) : self.pos_to_offset(b)]

    def _delete_selection(self) -> bool:
        cur = self.cursors.primary
        if not cur.has_selection or cur.sel is None:
            return False
        a, b = cur.sel.ordered()
        self.doc.delete(self.pos_to_offset(a), self.pos_to_offset(b) - self.pos_to_offset(a))
        self.cursors.set_primary(a)
        return True

    # -- edits ---------------------------------------------------------
    def type_text(self, text: str) -> None:
        if self._delete_selection():
            pass
        # multi-cursor: apply last→first
        for c in self.cursors.sort_for_edit():
            base = c.sel.active if c.has_selection and c.sel else c.pos
            self.doc.insert(self.pos_to_offset(self.clamp(base)), text)
        # move primary after inserted text (single-line fast path)
        if "\n" not in text:
            self.move(dcol=len(text))
        else:
            self.set_cursor(self.offset_to_pos(self.pos_to_offset(self.cursor) + len(text)))

    def newline(self) -> None:
        cur = self.cursor
        line_text = self.lines()[cur.line][: cur.col]
        indent = line_text[: len(line_text) - len(line_text.lstrip(" \t"))]
        stripped = line_text.strip()
        extra = ""
        if stripped.endswith(":"):
            extra = " " * self.tab_width
        self.type_text("\n" + indent + extra)

    def backspace(self) -> None:
        if self._delete_selection():
            return
        off = self.pos_to_offset(self.cursor)
        if off == 0:
            return
        self.doc.delete(off - 1, 1)
        self.set_cursor(self.offset_to_pos(off - 1))

    def delete_forward(self) -> None:
        if self._delete_selection():
            return
        off = self.pos_to_offset(self.cursor)
        if off >= len(self.doc.buffer):
            return
        self.doc.delete(off, 1)

    def undo(self) -> bool:
        ok = self.doc.undo()
        if ok:
            self.cursors.collapse_all()
        return ok

    def redo(self) -> bool:
        return self.doc.redo()

    # -- line ops ------------------------------------------------------
    def _line_range(self, line: int) -> tuple[int, int]:
        lines = self.lines()
        start = sum(len(lines[i]) + 1 for i in range(line))
        end = start + len(lines[line]) + (1 if line < len(lines) - 1 else 0)
        return (start, min(end, len(self.doc.buffer)))

    def duplicate_line(self) -> None:
        line = self.cursor.line
        text = self.lines()[line]
        s, _ = self._line_range(line)
        insert_at = s + len(text)
        self.doc.insert(insert_at, "\n" + text if line < len(self.lines()) - 1 else "\n" + text)
        self.set_cursor(Position(line + 1, self.cursor.col))

    def delete_line(self) -> None:
        line = self.cursor.line
        s, e = self._line_range(line)
        if e > s:
            self.doc.delete(s, e - s)
        self.set_cursor(Position(min(line, len(self.lines()) - 1), 0))

    def move_line(self, direction: int) -> None:
        lines = self.lines()
        line = self.cursor.line
        other = line + direction
        if not 0 <= other < len(lines):
            return
        a = lines[line]
        lines[line], lines[other] = lines[other], a
        # rewrite whole buffer segment simply
        full = "\n".join(lines)
        cur_text = self.doc.text
        if full != cur_text:
            self.doc.delete(0, len(cur_text))
            self.doc.insert(0, full)
        self.set_cursor(Position(other, min(self.cursor.col, len(lines[other]))))

    def toggle_comment(self) -> None:
        line = self.cursor.line
        text = self.lines()[line]
        stripped = text.lstrip(" \t")
        indent = text[: len(text) - len(stripped)]
        path = str(self.doc.path or "")
        xmlish = path.endswith((".xml", ".html"))
        if xmlish:
            if stripped.startswith("<!--") and stripped.endswith("-->"):
                inner = stripped[4:-3].strip()
                new = indent + inner
            else:
                new = f"{indent}<!-- {stripped} -->" if stripped else indent
        else:
            if stripped.startswith("# "):
                new = indent + stripped[2:]
            elif stripped.startswith("#"):
                new = indent + stripped[1:]
            else:
                new = f"{indent}# {stripped}" if stripped else indent
        s, _ = self._line_range(line)
        self.doc.delete(s, len(text))
        self.doc.insert(s, new)
        self.set_cursor(Position(line, min(len(new), self.cursor.col)))

    def indent(self, forward: bool = True) -> None:
        line = self.cursor.line
        text = self.lines()[line]
        s, _ = self._line_range(line)
        pad = " " * self.tab_width
        if forward:
            self.doc.insert(s, pad)
            self.set_cursor(Position(line, self.cursor.col + self.tab_width))
        else:
            if text.startswith(pad):
                self.doc.delete(s, self.tab_width)
            elif text.startswith("\t"):
                self.doc.delete(s, 1)
            self.set_cursor(Position(line, max(0, self.cursor.col - self.tab_width)))

    # -- search --------------------------------------------------------
    def find_all(self, opt: FindOptions) -> list[Match]:
        self.last_find = opt
        self.matches = self.search.find_all(opt, self.doc.text)
        self.match_index = 0 if self.matches else -1
        return list(self.matches)

    def find_next(self, wrap: bool = True) -> Match | None:
        if self.last_find is None or not self.matches:
            return None
        if wrap:
            self.match_index = (self.match_index + 1) % len(self.matches)
        else:
            self.match_index = min(self.match_index + 1, len(self.matches) - 1)
        m = self.matches[self.match_index]
        self.set_cursor(Position(m.line, m.col))
        return m

    def find_prev(self) -> Match | None:
        if self.last_find is None or not self.matches:
            return None
        self.match_index = (self.match_index - 1) % len(self.matches)
        m = self.matches[self.match_index]
        self.set_cursor(Position(m.line, m.col))
        return m

    def replace_all(self, opt: FindOptions, repl: str) -> int:
        new_text, n = SearchEngine.replace_all_text(self.doc.text, opt, repl)
        if n:
            self.doc.delete(0, len(self.doc.text))
            self.doc.insert(0, new_text)
            self.set_cursor(Position(0, 0))
        return n

    def add_next_occurrence(self) -> bool:
        """Ctrl+D: select next occurrence of word/selection (multi-cursor lite)."""
        sel = self.selected_text()
        if not sel:
            pos = self.cursor
            line = self.lines()[pos.line]
            word_match = None
            for wm in _WORD_RE.finditer(line):
                if wm.start() <= pos.col < wm.end():
                    word_match = wm
                    break
            if not word_match:
                return False
            word = word_match.group(0)
            start = Position(pos.line, word_match.start())
            end = Position(pos.line, word_match.end())
            self.cursors.set_primary(end, Selection(start, end))
            sel = word
        assert sel
        opt = FindOptions(pattern=sel, case_sensitive=True)
        allm = self.search.find_all(opt, self.doc.text)
        cur_off = self.pos_to_offset(self.cursor)
        for hit in allm:
            if hit.start >= cur_off:
                p = self.offset_to_pos(hit.end)
                self.cursors.add(p)
                self.set_cursor(p)
                return True
        return False

    # -- file ----------------------------------------------------------
    def open_file(self, path: Path) -> None:
        self.doc = Document.from_file(path)
        self.cursors = CursorSet()
        self.matches = []
        self.match_index = -1

    def save(self, path: Path | None = None) -> Path:
        return self.doc.save(path)
