"""M7 AI tests: offline explain/docstring, provider entry point, app commands."""

from __future__ import annotations

import sys
from pathlib import Path

from ocode.engines.ai import OfflineProvider, draft_docstring, explain_symbol, get_provider
from ocode.engines.oki.db import OkiDb
from ocode.engines.oki.indexer import Indexer
from ocode.engines.oki.query import OkiQuery

sys.path.insert(0, str(Path(__file__).parent))
from test_m4_oki import make_modules  # noqa: E402


def make_query(tmp_path: Path) -> tuple[OkiQuery, OkiDb]:
    mods = make_modules(tmp_path)
    db = OkiDb(tmp_path / "idx.sqlite")
    Indexer(db, mods).build()
    return (OkiQuery(db), db)


def test_explain_model_field_unknown(tmp_path: Path) -> None:
    q, db = make_query(tmp_path)
    try:
        res = explain_symbol("sale.order", q)
        assert "fields" in res.body and "partner_id" in res.body
        field = explain_symbol("partner_id", q)
        assert "Many2one" in field.body
        missing = explain_symbol("nope.nothing", q)
        assert "No local information" in missing.body
    finally:
        db.close()


def test_draft_docstring_shapes() -> None:
    src = "def f(a, b=1, *args, **kw):\n    return a\n"
    at, doc = draft_docstring(src, 2)
    assert at == 2 and "Args:" in doc and "Returns:" in doc and "b=1" not in doc
    assert "a:" in doc and "**kw" in doc
    nodoc, empty = draft_docstring('def g():\n    """Done."""\n    pass\n', 2)
    assert empty == "" and nodoc == 3
    assert draft_docstring("def broken(:\n", 1)[1].strip().startswith('"""')


def test_provider_registry(monkeypatch: object) -> None:
    import ocode.engines.ai as aimod
    from ocode.engines.ai import Provider

    class Custom(Provider):
        name = "custom"

        def generate(self, prompt: str, context: dict[str, object]) -> str:
            return "custom!"

    class FakeEP:
        name = "custom"

        def load(self) -> object:
            return Custom

    monkeypatch.setattr(aimod, "entry_points", lambda: [FakeEP()])
    assert isinstance(get_provider("offline"), OfflineProvider)
    assert get_provider("custom").generate("x", {}) == "custom!"
    try:
        get_provider("nope-missing")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")


async def test_app_ai_commands(tmp_path: Path, monkeypatch: object) -> None:
    import ocode.engines.ses as ses

    monkeypatch.setattr(ses, "state_dir", lambda: tmp_path / "state")
    mods = make_modules(tmp_path)
    db = OkiDb(tmp_path / "idx.sqlite")
    Indexer(db, mods).build()
    from ocode.app import OcodeApp
    from ocode.engines.oki.query import OkiQuery as _Q
    from ocode.ui.screens.info import HoverScreen

    target = next(m for m in mods if m.name == "sale_custom").path / "models" / "sale_order.py"
    app = OcodeApp(start_path=target)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.oki_db, app.oki = db, _Q(db)
        st = app.active_state()
        idx = st.doc.text.index("sale.order")
        st.set_cursor(st.offset_to_pos(idx + 2))
        app.action_ai_explain()
        await pilot.pause()
        assert isinstance(app.screen, HoverScreen)
        await pilot.press("escape")
        await pilot.pause()
        # docstring in a python function
        app.open_path(target)
        st = app.active_state()
        st.doc.delete(0, len(st.doc.text))
        st.doc.insert(0, "def my_fn(a, b):\n    return a\n")
        st.set_cursor(st.offset_to_pos(4))
        app.action_ai_docstring()
        await pilot.pause()
        assert '"""' in app.active_state().doc.text
        assert "Args:" in app.active_state().doc.text
    db.close()
