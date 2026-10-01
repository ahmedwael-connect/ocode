"""M7 vim tests: headless motions/operators + Pilot integration."""

from __future__ import annotations

from pathlib import Path

from ocode.engines.ote.cursor import Position
from ocode.engines.ote.document import Document
from ocode.engines.ote.modal import VimController
from ocode.engines.ote.state import EditorState


def vc(text: str, line: int = 0, col: int = 0) -> tuple[EditorState, VimController]:
    st = EditorState(Document(text=text))
    st.set_cursor(Position(line, col))
    return (st, VimController(st))


def press(ctl: VimController, *keys: str) -> None:
    for k in keys:
        ctl.handle(k if len(k) > 1 else k, k if len(k) == 1 else "")


def test_motions_hjkl_word() -> None:
    st, ctl = vc("hello world\nsecond line\n")
    press(ctl, "l", "l")
    assert st.cursor == Position(0, 2)
    press(ctl, "w")
    assert st.cursor == Position(0, 6)
    press(ctl, "b")
    assert st.cursor == Position(0, 0)
    press(ctl, "j")
    assert st.cursor == Position(1, 0)
    press(ctl, "$")
    assert st.cursor == Position(1, len("second line"))
    press(ctl, "0")
    assert st.cursor == Position(1, 0)
    press(ctl, "G")
    assert st.cursor.line == 1
    press(ctl, "g")
    assert st.cursor.line == 0
    press(ctl, "e")
    assert st.cursor == Position(0, 4)


def test_counts() -> None:
    st, ctl = vc("a\nb\nc\nd\n")
    press(ctl, "2", "j")
    assert st.cursor == Position(2, 0)
    press(ctl, "2", "d", "d")
    assert st.doc.text == "a\nb\n"


def test_delete_word_and_undo() -> None:
    st, ctl = vc("hello world\n")
    press(ctl, "d", "w")
    assert st.doc.text == "world\n"
    press(ctl, "u")
    assert st.doc.text == "hello world\n"


def test_dd_yy_paste() -> None:
    st, ctl = vc("one\ntwo\nthree\n")
    press(ctl, "d", "d")
    assert st.doc.text == "two\nthree\n"
    press(ctl, "p")
    assert "one" in st.doc.text
    press(ctl, "y", "y")
    assert ctl.clipboard.strip() == st.lines()[st.cursor.line]


def test_x_and_replace() -> None:
    st, ctl = vc("abc\n")
    press(ctl, "x")
    assert st.doc.text == "bc\n"
    press(ctl, "r", "Z")
    assert st.doc.text == "Zc\n"


def test_insert_transitions() -> None:
    st, ctl = vc("hi\n")
    press(ctl, "i")
    assert ctl.vim.mode == "INSERT"
    press(ctl, "escape")
    assert ctl.vim.mode == "NORMAL"
    press(ctl, "A")
    assert ctl.vim.mode == "INSERT" and st.cursor == Position(0, 2)
    press(ctl, "escape")
    press(ctl, "o")
    assert ctl.vim.mode == "INSERT" and st.cursor.line == 1


def test_visual_yank_delete() -> None:
    st, ctl = vc("hello world\n")
    press(ctl, "v", "w", "y")
    assert ctl.clipboard == "hello " and ctl.vim.mode == "NORMAL"
    st.set_cursor(Position(0, 0))
    press(ctl, "v", "w", "d")
    assert st.doc.text == "world\n"


def test_find_and_match() -> None:
    st, ctl = vc("abca (x)\n")
    press(ctl, "f", "c")
    assert st.cursor == Position(0, 2)
    press(ctl, "f", "(")
    assert st.cursor == Position(0, 5)
    press(ctl, "%")
    assert st.cursor == Position(0, 7)


def test_join_and_D() -> None:
    st, ctl = vc("aaa\nbbb\n")
    press(ctl, "J")
    assert st.doc.text == "aaa bbb\n"
    press(ctl, "D")
    assert st.doc.text == "aaa \n"


async def test_pilot_vim_flow(tmp_path: Path, monkeypatch: object) -> None:
    import ocode.engines.ses as ses

    monkeypatch.setattr(ses, "state_dir", lambda: tmp_path / "state")
    from ocode.app import OcodeApp
    from ocode.ui.widgets.editor import OcodeEditor

    target = tmp_path / "v.txt"
    target.write_text("hello world\n", encoding="utf-8")
    app = OcodeApp(start_path=target)
    async with app.run_test() as pilot:
        await pilot.pause()
        editor = app.query_one("#editor", OcodeEditor)
        app.action_toggle_vim()
        assert editor.vim_enabled
        await pilot.press("l", "l", "x")  # delete third char
        await pilot.pause()
        assert "helo world" in app.active_state().doc.text
        await pilot.press("i", "X", "escape")
        await pilot.pause()
        assert "X" in app.active_state().doc.text
        # :w saves
        await pilot.press(":")
        await pilot.pause()
        await pilot.press("w", "enter")
        await pilot.pause(0.5)
        assert "heXlo" in target.read_text(encoding="utf-8")
        app.action_toggle_vim()
        assert not editor.vim_enabled
