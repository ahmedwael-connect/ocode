"""M1 OTE engine tests (buffer, doc, search, state, tabs, session)."""

from __future__ import annotations

from pathlib import Path

from ocode.engines.ote.buffer import PieceTable
from ocode.engines.ote.cursor import CursorSet
from ocode.engines.ote.document import Document
from ocode.engines.ote.highlight import detect_language, highlight_lines
from ocode.engines.ote.history import EditOp, UndoStack
from ocode.engines.ote.search import FindOptions, SearchEngine
from ocode.engines.ote.session import SwapManager, swap_path_for
from ocode.engines.ote.state import EditorState
from ocode.engines.ote.tabs import TabState


def test_piece_table_insert_delete_roundtrip() -> None:
    pt = PieceTable("hello world")
    pt.insert(5, ", brave")
    assert pt.text == "hello, brave world"
    removed = pt.delete(5, 7)
    assert removed == ", brave"
    assert pt.text == "hello world"
    assert len(pt) == len("hello world")


def test_piece_table_snapshot_restore() -> None:
    pt = PieceTable("abc")
    snap = pt.snapshot()
    pt.insert(3, "def")
    pt.delete(0, 1)
    assert pt.text == "bcdef"
    pt.restore(snap)
    assert pt.text == "abc"


def test_piece_table_offsets() -> None:
    pt = PieceTable("a\nbb\nccc")
    assert pt.offset_of(1, 1) == 3
    assert pt.position_of(3) == (1, 1)
    assert pt.line_count() == 3


def test_undo_group_atomic() -> None:
    st = UndoStack()
    st.begin_group()
    st.push(EditOp("insert", 0, "a"))
    st.push(EditOp("insert", 1, "b"))
    st.end_group()
    group = st.pop_undo()
    assert group is not None and len(group) == 2
    assert st.pop_undo() is None


def test_document_save_atomic_and_dirty(tmp_path: Path) -> None:
    f = tmp_path / "m.py"
    f.write_text("x = 1\n", encoding="utf-8")
    doc = Document.from_file(f)
    assert not doc.dirty
    doc.insert(len(doc.text), "y = 2\n")
    assert doc.dirty
    doc.save()
    assert not doc.dirty
    assert f.read_text(encoding="utf-8").endswith("\n")


def test_document_crlf_and_encoding(tmp_path: Path) -> None:
    f = tmp_path / "w.xml"
    f.write_bytes(b"<a/>\r\n<b/>\r\n")
    doc = Document.from_file(f)
    assert doc.newline == "\r\n"
    doc.save()
    assert b"\r\n" in f.read_bytes()


def test_search_find_replace() -> None:
    eng = SearchEngine()
    text = "foo bar foo"
    assert eng.count(FindOptions("foo"), text) == 2
    assert eng.count(FindOptions("FOO"), text) == 2  # case-insensitive default
    assert eng.count(FindOptions("FOO", case_sensitive=True), text) == 0
    assert eng.count(FindOptions(r"f.o", regex=True), text) == 2
    out, n = SearchEngine.replace_all_text(text, FindOptions("foo"), "baz")
    assert (out, n) == ("baz bar baz", 2)


def test_highlight_detect_and_spans() -> None:
    assert detect_language(Path("a.py")) == "python"
    assert detect_language(Path("v.xml")) == "xml"
    spans = highlight_lines("python", ["def f():  # hi"])
    assert any(scope in ("keyword", "comment") for _, _, scope in spans[0])


def test_tabs_mru() -> None:
    t = TabState()
    t.open(Path("/a.py"))
    t.open(Path("/b.py"))
    t.activate(0)
    assert t.active == 0
    assert t.mru_order()[0] == 0
    t.close(0)
    assert len(t) == 1


def test_editor_state_typing_undo() -> None:
    st = EditorState(Document(text="hi"))
    st.set_cursor(st.offset_to_pos(2))
    st.type_text("!")
    assert st.doc.text == "hi!"
    assert st.doc.dirty
    assert st.undo()
    assert st.doc.text == "hi"


def test_editor_state_line_ops_and_comment(tmp_path: Path) -> None:
    st = EditorState(Document(path=tmp_path / "a.py", text="a = 1"))
    st.toggle_comment()
    assert st.doc.text.startswith("#")
    st.toggle_comment()
    assert st.doc.text == "a = 1"
    st.duplicate_line()
    assert st.doc.text.count("a = 1") == 2
    st.goto_line(1)
    st.delete_line()
    assert "a = 1" in st.doc.text


def test_editor_state_find_nav() -> None:
    st = EditorState(Document(text="foo\nbar foo\n"))
    st.find_all(FindOptions("foo"))
    assert len(st.matches) == 2
    st.find_next()
    assert st.cursor.line == 1


def test_swap_write_clear(tmp_path: Path, monkeypatch: object) -> None:
    import ocode.engines.ote.session as sess

    monkeypatch.setattr(sess, "state_dir", lambda: tmp_path)
    sp = swap_path_for(Path("/x/a.py"))
    sm = SwapManager(sp)
    sm.write("dirty")
    assert sm.exists()
    assert sm.read() == "dirty"
    sm.clear()
    assert not sm.exists()


def test_cursor_set_dedupe() -> None:
    from ocode.engines.ote.cursor import Cursor, Position

    cs = CursorSet([Cursor(Position(0, 0))])
    assert cs.add(Position(0, 0)) is False
    assert cs.add(Position(1, 0)) is True
    assert len(cs) == 2
