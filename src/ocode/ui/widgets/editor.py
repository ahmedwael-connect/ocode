"""Custom editor widget over EditorState (FR-OTE-040..045, M1 core).

Renders line numbers, current-line highlight, selection, search matches,
highlight spans. Handles keyboard editing directly (no stock TextArea).
"""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual import events
from textual.message import Message
from textual.widget import Widget

from ocode.engines.ote.highlight import detect_language, highlight_lines
from ocode.engines.ote.state import EditorState
from ocode.ui.widgets.complete import CompletionPopup


class EditorSaved(Message):
    def __init__(self, path: Path | None) -> None:
        super().__init__()
        self.path = path


_SCOPE_STYLE: dict[str, str] = {
    "keyword": "bold magenta",
    "string": "green",
    "comment": "dim italic",
    "number": "cyan",
    "decorator": "yellow",
    "builtin": "bold cyan",
    "tag": "bold blue",
    "attr": "cyan",
    "entity": "yellow",
}


class OcodeEditor(Widget, can_focus=True):
    def __init__(self, state: EditorState | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.state = state or EditorState()
        self.top = 0
        self.left = 0
        self.show_line_numbers = True
        self._lang = "text"

    @property
    def cursor(self) -> tuple[int, int]:
        c = self.state.cursor
        return (c.line, c.col)

    def open_file(self, path: Path) -> None:
        self.state.open_file(path)
        self._lang = detect_language(path)
        self.top = 0
        self.left = 0
        self.refresh()

    def set_search_matches(self, line: int, col: int, length: int) -> None:
        _ = (line, col, length)

    # -- rendering -----------------------------------------------------
    def render(self) -> Text:
        lines = self.state.lines()
        total = len(lines)
        height = max(1, self.size.height)
        width = max(10, self.size.width)
        # keep cursor visible
        cline, ccol = self.cursor
        if cline < self.top:
            self.top = cline
        elif cline >= self.top + height:
            self.top = cline - height + 1
        if ccol < self.left:
            self.left = ccol
        elif ccol >= self.left + width - 10:
            self.left = ccol - width + 10

        lang = self._lang
        spans = highlight_lines(lang, lines[self.top : self.top + height])
        cur = self.state.cursors.primary
        sel_range: tuple[int, int, int, int] | None = None
        if cur.has_selection and cur.sel is not None:
            a, b = cur.sel.ordered()
            sel_range = (a.line, a.col, b.line, b.col)

        match_lines: dict[int, list[tuple[int, int]]] = {}
        for m in self.state.matches[:500]:
            match_lines.setdefault(m.line, []).append((m.col, m.end - m.start))

        out = Text(no_wrap=True)
        gutter_w = len(str(total)) + 1
        for vi in range(height):
            li = self.top + vi
            if li >= total:
                out.append("\n")
                continue
            raw = lines[li].expandtabs(self.state.tab_width)
            vis = raw[self.left : self.left + width - gutter_w - 2]
            is_cur = li == cline
            # gutter
            gutter = f"{li + 1:>{gutter_w}} "
            out.append(gutter, style="dim bold" if not is_cur else "bold yellow")
            base = len(out.plain)
            out.append(vis if vis else " ")
            # highlight spans
            if vi < len(spans):
                for coff, clen, scope in spans[vi]:
                    style = _SCOPE_STYLE.get(scope)
                    if style and coff >= self.left:
                        out.stylize(style, base + coff - self.left, base + coff - self.left + clen)
            # search matches
            for mcol, mlen in match_lines.get(li, []):
                if mcol + mlen > self.left:
                    s = base + max(0, mcol - self.left)
                    e = base + mcol - self.left + mlen
                    out.stylize("reverse underline", s, e)
            # selection
            if sel_range is not None:
                a_line, a_col, b_line, b_col = sel_range
                if a_line <= li <= b_line:
                    s = a_col - self.left if li == a_line else 0
                    e = b_col - self.left if li == b_line else len(vis)
                    s, e = max(0, s), min(len(vis), e)
                    if e > s:
                        out.stylize("on blue", base + s, base + e)
            # cursor
            if is_cur:
                cpos = ccol - self.left
                if 0 <= cpos <= len(vis):
                    out.stylize("reverse bold", base + cpos, base + cpos + 1)
                out.stylize("on grey15", base, base + len(vis if vis else " "))
            if vi < height - 1:
                out.append("\n")
        return out

    # -- key handling --------------------------------------------------
    def _popup(self) -> object | None:
        try:
            pop = self.app.query_one("#complete", CompletionPopup)
            return pop
        except Exception:
            return None

    def _app_hook(self, name: str) -> object | None:
        return getattr(self.app, name, None)

    async def on_key(self, event: events.Key) -> None:
        key = event.key
        st = self.state
        handled = True

        # completion popup steals navigation/accept keys while open (M4)
        pop = self._popup()
        popup_open = bool(pop and getattr(pop, "is_open", False))
        if popup_open and key in ("up", "down"):
            move = getattr(pop, "move", None)
            if callable(move):
                move(-1 if key == "up" else 1)
            event.prevent_default()
            event.stop()
            return
        if popup_open and key in ("tab", "enter"):
            accept = self._app_hook("accept_completion")
            if callable(accept):
                accept()
            event.prevent_default()
            event.stop()
            return
        if popup_open and key == "escape":
            hide = getattr(pop, "hide", None)
            if callable(hide):
                hide()
            event.prevent_default()
            event.stop()
            return

        if key == "ctrl+space":
            hook = self._app_hook("action_show_completion")
            if callable(hook):
                hook()
        elif key == "ctrl+s":
            try:
                path = st.save()
                self.app.post_message(EditorSaved(path))
            except (ValueError, PermissionError, OSError):
                self.notify("Save failed (no path or read-only)", severity="error")
        elif key == "ctrl+z":
            st.undo()
        elif key == "ctrl+y":
            st.redo()
        elif key == "ctrl+a":
            st.select_all()
        elif key == "ctrl+l":
            st.select_line()
        elif key == "ctrl+d":
            st.add_next_occurrence()
        elif key == "ctrl+g":
            pass  # app-level go-to-line dialog owns this
        elif key == "ctrl+slash":
            st.toggle_comment()
        elif key in ("up", "shift+up", "alt+up"):
            if key == "alt+up":
                st.move_line(-1)
            else:
                st.move(dline=-1, select=key.startswith("shift"))
        elif key in ("down", "shift+down", "alt+down"):
            if key == "alt+down":
                st.move_line(1)
            else:
                st.move(dline=1, select=key.startswith("shift"))
        elif key in ("left", "shift+left", "ctrl+left", "ctrl+shift+left"):
            if "ctrl" in key:
                st.move_word(-1, select="shift" in key)
            else:
                st.move(dcol=-1, select=key.startswith("shift"))
        elif key in ("right", "shift+right", "ctrl+right", "ctrl+shift+right"):
            if "ctrl" in key:
                st.move_word(1, select="shift" in key)
            else:
                st.move(dcol=1, select=key.startswith("shift"))
        elif key in ("home", "shift+home"):
            st.home(select=key.startswith("shift"))
        elif key in ("end", "shift+end"):
            st.line_end(select=key.startswith("shift"))
        elif key == "pageup":
            st.move(dline=-max(1, self.size.height - 1))
        elif key == "pagedown":
            st.move(dline=max(1, self.size.height - 1))
        elif key == "enter":
            st.newline()
        elif key == "backspace":
            st.backspace()
        elif key == "delete":
            st.delete_forward()
        elif key == "tab":
            expand = self._app_hook("try_expand_snippet")
            if callable(expand) and expand():
                pass
            else:
                st.indent(True)
        elif key == "shift+tab":
            st.indent(False)
        elif key == "space":
            st.type_text(" ")
            self._after_printable(" ")
        elif event.is_printable:
            ch = event.character or ""
            if not ch and len(key) == 1:
                ch = key
            if ch:
                st.type_text(ch)
                self._after_printable(ch)
            else:
                handled = False
        else:
            handled = False

        if handled:
            event.prevent_default()
            event.stop()
            self.refresh()

    def _after_printable(self, ch: str) -> None:
        hook = self._app_hook("after_edit_for_completion")
        if callable(hook) and ch in ".[/\"'=<>_":
            hook(ch)
