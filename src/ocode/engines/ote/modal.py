"""Vim modal editing over EditorState (M7). NORMAL/INSERT/VISUAL/LINE modes."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ocode.engines.ote.cursor import Position
from ocode.engines.ote.state import EditorState

NORMAL, INSERT, VISUAL, VISUAL_LINE = "NORMAL", "INSERT", "VISUAL", "V-LINE"

_WORD = re.compile(r"\w+|[^\w\s]")
_PAIRS = {"(": ")", "[": "]", "{": "}", "<": ">"}


@dataclass
class VimState:
    mode: str = NORMAL
    count: str = ""
    pending_op: str = ""  # d | c | y (dd/yy awaited via same key)
    pending_find: str = ""  # f | t | F | T awaiting char
    message: str = ""


class VimController:
    """Pure-logic modal handler. Returns True when the key was consumed."""

    def __init__(self, state: EditorState) -> None:
        self.state = state
        self.vim = VimState()
        self.clipboard = ""

    # -- public --------------------------------------------------------
    def status(self) -> str:
        return f"-- {self.vim.mode} --"

    def handle(self, key: str, char: str) -> bool:
        """Route one key. `key` is the Textual key name, `char` printable text."""
        v = self.vim
        if v.mode == INSERT:
            if key == "escape":
                v.mode, v.count, v.pending_op, v.pending_find = NORMAL, "", "", ""
                # step back one like vim
                cur = self.state.cursor
                if cur.col > 0:
                    self.state.set_cursor(Position(cur.line, cur.col - 1))
                return True
            return False  # let editor insert
        # NORMAL / VISUAL
        if key == "escape":
            v.mode, v.count, v.pending_op, v.pending_find = NORMAL, "", "", ""
            self.state.cursors.collapse_all()
            self.state.cursors.clear_selections()
            return True
        if v.pending_find:
            return self._do_find(v.pending_find, char or key)
        if char.isdigit() and (v.count or char != "0" or v.pending_op):
            if not (char == "0" and not v.count and not v.pending_op):
                v.count += char
                return True
        count = int(v.count) if v.count else 1
        explicit = v.count != ""
        if char in "dcy" and not v.pending_op and v.mode != INSERT:
            if v.mode in (VISUAL, VISUAL_LINE):
                v.count = ""
                return self._op_motion(char, "", 1)
            # dd/yy/cc handled when repeated; else await motion (keep count)
            v.pending_op = char
            return True
        if v.pending_op and char == v.pending_op:
            op = v.pending_op
            v.pending_op = ""
            v.count = ""
            self._line_op(op, count)
            return True
        if v.pending_op and char:
            op = v.pending_op
            v.pending_op = ""
            v.count = ""
            return self._op_motion(op, char, count)
        v.count = ""
        return self._normal(char, key, count, explicit)

    # -- normal-mode commands ------------------------------------------
    def _normal(self, char: str, key: str, count: int, explicit: bool = False) -> bool:
        st = self.state
        v = self.vim
        if char in "hjkl ":
            for _ in range(count):
                if char in ("h",):
                    st.move(dcol=-1, select=self._sel())
                elif char in ("l", " "):
                    st.move(dcol=1, select=self._sel())
                elif char == "j":
                    st.move(dline=1, select=self._sel())
                else:
                    st.move(dline=-1, select=self._sel())
            return True
        if char in "wWbBeE":
            for _ in range(count):
                self._word_move(char)
            return True
        if char == "0":
            st.move_to(Position(st.cursor.line, 0), self._sel())
            return True
        if char == "^":
            st.home(select=self._sel())
            return True
        if char == "$":
            for _ in range(count - 1):
                st.move(dline=1)
            st.line_end(select=self._sel())
            return True
        if char == "g" and key == "g":
            # gg needs two-key; approximate: single g goes top (documented)
            st.set_cursor(Position(0, 0))
            return True
        if char == "G":
            lines = st.lines()
            last = len(lines) - 1
            if not explicit and last > 0 and lines[last] == "":
                last -= 1  # skip phantom line from trailing newline
            target = count - 1 if explicit else last
            st.set_cursor(Position(max(0, min(target, len(lines) - 1)), 0))
            return True
        if char == "f" or char == "t" or char in "FT":
            v.pending_find = char
            return True
        if char == "%":
            self._match_paren()
            return True
        if char == "i":
            v.mode = INSERT
            return True
        if char == "I":
            st.home()
            v.mode = INSERT
            return True
        if char == "a":
            st.move(dcol=1)
            v.mode = INSERT
            return True
        if char == "A":
            st.line_end()
            v.mode = INSERT
            return True
        if char == "o":
            st.line_end()
            st.newline()
            v.mode = INSERT
            return True
        if char == "O":
            cur = st.cursor.line
            st.doc.insert(st.pos_to_offset(Position(cur, 0)), "\n")
            st.set_cursor(Position(cur, 0))
            v.mode = INSERT
            return True
        if char == "v":
            v.mode = VISUAL if v.mode != VISUAL else NORMAL
            self._sync_visual()
            return True
        if char == "V":
            v.mode = VISUAL_LINE if v.mode != VISUAL_LINE else NORMAL
            self._sync_visual(line=True)
            return True
        if char == "x":
            if self.vim.mode in (VISUAL, VISUAL_LINE):
                self._delete_selection_to_clip()
                self.vim.mode = NORMAL
                return True
            for _ in range(count):
                off = st.pos_to_offset(st.cursor)
                if off < len(st.doc.buffer):
                    removed = st.doc.text[off : off + 1]
                    st.doc.delete(off, 1)
                    self.clipboard = removed
            return True
        if char == "X":
            for _ in range(count):
                st.backspace()
            return True
        if char == "D":
            return self._op_motion("d", "$", 1)
        if char == "C":
            return self._op_motion("c", "$", 1)
        if char == "s":
            self._op_motion("d", "l", 1)
            v.mode = INSERT
            return True
        if char == "S":
            st.select_line()
            self._delete_selection_to_clip()
            v.mode = INSERT
            return True
        if char == "p":
            if self.clipboard:
                st.move(dcol=1)
                st.type_text(self.clipboard)
            return True
        if char == "P":
            if self.clipboard:
                st.type_text(self.clipboard)
            return True
        if char == "u":
            st.undo()
            return True
        if char == "r":
            v.pending_find = "r"
            return True
        if char == "J":
            # join lines
            line = st.cursor.line
            lines = st.lines()
            if line < len(lines) - 1:
                s = st.pos_to_offset(Position(line, len(lines[line])))
                st.doc.delete(s, 1)
                st.set_cursor(st.offset_to_pos(s))
                st.type_text(" ")
            return True
        return False

    def _sel(self) -> bool:
        return self.vim.mode in (VISUAL, VISUAL_LINE)

    def _sync_visual(self, line: bool = False) -> None:
        from ocode.engines.ote.cursor import Selection

        st = self.state
        cur = st.cursor
        if self.vim.mode in (VISUAL, VISUAL_LINE):
            anchor = Position(cur.line, 0) if line else cur
            active = Position(cur.line, len(st.lines()[cur.line])) if line else cur
            st.cursors.set_primary(active, Selection(anchor, active))
        else:
            st.cursors.clear_selections()

    # -- motions ---------------------------------------------------------
    def _word_move(self, cmd: str) -> None:
        st = self.state
        text = st.doc.text
        off = st.pos_to_offset(st.cursor)
        big = cmd.isupper()
        if cmd.lower() == "w":
            nxt = self._next_word_start(text, off, big)
        elif cmd.lower() == "b":
            nxt = off
            for _ in range(1):
                nxt = self._prev_word_start(text, off, big)
                off = nxt
        else:  # e
            nxt = self._word_end(text, off, big)
        st.move_to(st.offset_to_pos(nxt), self._sel())

    @staticmethod
    def _is_word(ch: str, big: bool) -> bool:
        return not ch.isspace() if big else (ch.isalnum() or ch == "_")

    def _next_word_start(self, text: str, off: int, big: bool) -> int:
        n = len(text)
        i = off
        if i < n and self._is_word(text[i], big):
            while i < n and self._is_word(text[i], big):
                i += 1
        while i < n and not self._is_word(text[i], big):
            i += 1
        return min(i, n)

    def _prev_word_start(self, text: str, off: int, big: bool) -> int:
        i = max(0, off - 1)
        while i > 0 and not self._is_word(text[i], big):
            i -= 1
        while i > 0 and self._is_word(text[i - 1], big):
            i -= 1
        return i

    def _word_end(self, text: str, off: int, big: bool) -> int:
        n = len(text)
        i = min(off + 1, n - 1 if n else 0)
        while i < n and not self._is_word(text[i], big):
            i += 1
        while i + 1 < n and self._is_word(text[i + 1], big):
            i += 1
        return min(i, n)

    def _do_find(self, kind: str, char: str) -> bool:
        v = self.vim
        v.pending_find = ""
        if not char or len(char) != 1:
            return True
        if kind == "r":
            st = self.state
            off = st.pos_to_offset(st.cursor)
            if off < len(st.doc.buffer):
                st.doc.delete(off, 1)
                # insert without moving (single undo step approx)
                st.doc.history.begin_group()
                try:
                    st.doc.insert(off, char)
                finally:
                    st.doc.history.end_group()
            return True
        st = self.state
        line = st.lines()[st.cursor.line]
        col = st.cursor.col
        if kind == "f":
            idx = line.find(char, col + 1)
            if idx != -1:
                st.set_cursor(Position(st.cursor.line, idx))
        elif kind == "t":
            idx = line.find(char, col + 1)
            if idx > 0:
                st.set_cursor(Position(st.cursor.line, idx - 1))
        elif kind == "F":
            idx = line.rfind(char, 0, col)
            if idx != -1:
                st.set_cursor(Position(st.cursor.line, idx))
        elif kind == "T":
            idx = line.rfind(char, 0, col)
            if idx != -1 and idx + 1 < len(line):
                st.set_cursor(Position(st.cursor.line, idx + 1))
        return True

    def _match_paren(self) -> None:
        st = self.state
        text = st.doc.text
        off = st.pos_to_offset(st.cursor)
        if off >= len(text) or text[off] not in _PAIRS and text[off] not in _PAIRS.values():
            return
        ch = text[off]
        depth, target = 0, _PAIRS.get(ch, ch)
        fwd = ch in _PAIRS
        step = 1 if fwd else -1
        i = off
        while 0 <= i < len(text):
            c = text[i]
            if c == ch:
                depth += 1
            elif c == target:
                depth -= 1
                if depth == 0:
                    st.set_cursor(st.offset_to_pos(i))
                    return
            i += step

    # -- operators ---------------------------------------------------------
    def _range_for_motion(self, motion: str, count: int) -> tuple[int, int] | None:
        st = self.state
        start = st.pos_to_offset(st.cursor)
        if motion in "hjkl":
            cur = st.cursor
            if motion == "h":
                identifier = max(0, cur.col - count)
                return (st.pos_to_offset(Position(cur.line, identifier)), start)
            if motion == "l":
                width = len(st.lines()[cur.line])
                end = min(width, cur.col + count)
                extra = 1 if end < width else 0
                return (start, st.pos_to_offset(Position(cur.line, end)) + extra)
            if motion == "j":
                last = min(len(st.lines()) - 1, cur.line + count)
                return (start, st.pos_to_offset(Position(last, 0)))
            last = max(0, cur.line - count)
            return (st.pos_to_offset(Position(last, 0)), start)
        if motion in "wW":
            end = start
            for _ in range(count):
                end = self._next_word_start(st.doc.text, end, motion == "W")
            return (start, end)
        if motion in "bB":
            end = start
            for _ in range(count):
                end = self._prev_word_start(st.doc.text, end, motion == "B")
            return (min(start, end), max(start, end))
        if motion in "eE":
            end = start
            for _ in range(count):
                end = self._word_end(st.doc.text, end, motion == "E")
            return (start, min(end + 1, len(st.doc.buffer)))
        if motion == "0":
            line_start = st.pos_to_offset(Position(st.cursor.line, 0))
            return (line_start, start)
        if motion == "$":
            line = st.lines()[st.cursor.line]
            return (start, st.pos_to_offset(Position(st.cursor.line, len(line))))
        if motion == "G":
            return (0, len(st.doc.buffer)) if count else None
        return None

    def _op_motion(self, op: str, motion: str, count: int) -> bool:
        st = self.state
        if self.vim.mode in (VISUAL, VISUAL_LINE):
            if op in ("d", "c"):
                self._delete_selection_to_clip()
                if op == "c":
                    self.vim.mode = INSERT
                else:
                    self.vim.mode = NORMAL
            elif op == "y":
                sel = st.selected_text()
                if sel is not None:
                    self.clipboard = sel
                st.cursors.clear_selections()
                self.vim.mode = NORMAL
            return True
        rng = self._range_for_motion(motion, count)
        if rng is None:
            if motion == "G":
                lines = st.lines()
                target = count - 1 if count > 1 else len(lines) - 1
                st.set_cursor(Position(max(0, min(target, len(lines) - 1)), 0))
                return True
            return True
        a, b = rng
        if op == "y":
            self.clipboard = st.doc.text[a:b]
            st.set_cursor(st.offset_to_pos(a))
        else:
            self.clipboard = st.doc.text[a:b]
            st.doc.delete(a, b - a)
            st.set_cursor(st.offset_to_pos(a))
            if op == "c":
                self.vim.mode = INSERT
        return True

    def _line_op(self, op: str, count: int) -> None:
        st = self.state
        yanked: list[str] = []
        st.doc.history.begin_group()
        try:
            for _ in range(count):
                line = st.cursor.line
                lines = st.lines()
                if line >= len(lines):
                    break
                text = lines[line]
                s = st.pos_to_offset(Position(line, 0))
                if op == "y":
                    yanked.append(text)
                else:
                    self.clipboard = text + "\n"
                    st.doc.delete(s, len(text) + (1 if line < len(lines) - 1 else 0))
                    st.set_cursor(Position(min(line, len(st.lines()) - 1), 0))
            if op == "y" and yanked:
                self.clipboard = "\n".join(yanked) + "\n"
            elif op == "c":
                self.vim.mode = INSERT
        finally:
            st.doc.history.end_group()

    def _delete_selection_to_clip(self) -> None:
        st = self.state
        sel = st.selected_text()
        if sel is None:
            # visual-line without selection object: delete whole line
            line = st.cursor.line
            lines = st.lines()
            s = st.pos_to_offset(Position(line, 0))
            self.clipboard = lines[line] + "\n"
            st.doc.delete(s, len(lines[line]) + (1 if line < len(lines) - 1 else 0))
            st.set_cursor(Position(min(line, len(st.lines()) - 1), 0))
            st.cursors.clear_selections()
            return
        cur = st.cursors.primary
        assert cur.sel is not None
        a, b = cur.sel.ordered()
        self.clipboard = sel
        st.doc.delete(st.pos_to_offset(a), st.pos_to_offset(b) - st.pos_to_offset(a))
        st.set_cursor(a)
        st.cursors.clear_selections()
