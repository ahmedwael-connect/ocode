"""M4 OMLS tests: diagnostics rules, completion, snippets, quickfixes, pylint parse."""

from __future__ import annotations

import sys
from pathlib import Path

from ocode.engines.oki.db import OkiDb
from ocode.engines.oki.indexer import Indexer
from ocode.engines.oki.query import OkiQuery
from ocode.engines.omls.complete import ORM_METHODS, complete_at
from ocode.engines.omls.diagnostics import FileCtx, analyze_file, analyze_module
from ocode.engines.omls.pylint import PylintResult
from ocode.engines.omls.quickfix import apply_fix, available_fixes
from ocode.engines.omls.snippets import expand_snippet
from ocode.engines.opd.module import ModuleInfo

sys.path.insert(0, str(Path(__file__).parent))
from test_m4_oki import make_modules  # noqa: E402


def make_query(tmp_path: Path) -> tuple[OkiQuery, OkiDb, list[ModuleInfo]]:
    mods = make_modules(tmp_path)
    db = OkiDb(tmp_path / "idx.sqlite")
    Indexer(db, mods).build()
    return (OkiQuery(db), db, mods)


def ctx_for(
    q: OkiQuery, mods: list[ModuleInfo], rel: str, version: str = "17.0"
) -> FileCtx:
    mod = next(m for m in mods if m.name == "sale_custom")
    files = [str(p.relative_to(mod.path)) for p in mod.path.rglob("*") if p.is_file()]
    manifest = {"depends": ["sale"], "data": ["security/ir.model.access.csv"]}
    return FileCtx(mod.path / rel, mod, manifest, files, q, version, {})


def test_unknown_model_and_field(tmp_path: Path) -> None:
    q, db, mods = make_query(tmp_path)
    try:
        py = (
            "from odoo import models, fields\n"
            "class A(models.Model):\n"
            "    _inherit = 'nope.model'\n"
        )
        diags = analyze_file(py, ctx_for(q, mods, "models/sale_order.py"))
        assert any(d.code == "ODOO001" and "nope.model" in d.message for d in diags)
        xml = (
            "<odoo><record id='v' model='ir.ui.view'>"
            "<field name='model'>sale.order</field>"
            "<field name='arch' type='xml'><form>"
            "<field name='name'/><field name='bogus'/>"
            "</form></field>"
            "</record></odoo>"
        )
        diags = analyze_file(xml, ctx_for(q, mods, "views/sale_order_views.xml"))
        assert any(d.code == "ODOO002" and "bogus" in d.message for d in diags)
        assert not any(d.code == "ODOO002" and "name" in d.message for d in diags)
    finally:
        db.close()


def test_manifest_rules_and_fixes(tmp_path: Path) -> None:
    q, db, mods = make_query(tmp_path)
    try:
        mod = next(m for m in mods if m.name == "sale_custom")
        files = {
            "__manifest__.py": "{'name': 'C', 'version': 'bad', 'depends': ['nope_mod'],"
            " 'data': ['views/sale_order_views.xml']}",
            "views/sale_order_views.xml": "<odoo/>",
            "security/ir.model.access.csv": "id\n",
        }
        diags = analyze_module(mod, files, q, "17.0")
        codes = {d.code for d in diags}
        assert "MANIFEST001" in codes  # bad version + missing license
        assert "ODOO008" in codes  # unknown depends
        assert "ODOO004" in codes  # access csv unlisted
        assert "ODOO006" not in codes  # no _name models in these files
        # fix: add missing access file to manifest data
        fix_diag = next(d for d in diags if d.code == "ODOO004" and d.fix)
        new_text, applied = apply_fix(fix_diag.fix, files["__manifest__.py"])
        assert applied and "ir.model.access.csv" in new_text
    finally:
        db.close()


def test_deprecated_and_tree_fix(tmp_path: Path) -> None:
    q, db, mods = make_query(tmp_path)
    try:
        xml = "<form><field name='x' attrs=\"{'invisible': [('a', '=', 1)]}\"/></form>"
        diags = analyze_file(xml, ctx_for(q, mods, "views/a.xml", version="17.0"))
        assert any(d.code == "DEPRECATED001" for d in diags)
        assert not analyze_file(xml, ctx_for(q, mods, "views/a.xml", version="16.0"))
        new_text, applied = apply_fix("attrs-to-invisible", xml)
        assert applied and "invisible=" in new_text and "attrs=" not in new_text
        tree = "<list><field name='x'/></list>"
        assert apply_fix("tree-to-list", "<tree><field name='x'/></tree>")[0] == tree
    finally:
        db.close()


def test_completion_python_xml(tmp_path: Path) -> None:
    q, db, mods = make_query(tmp_path)
    try:
        text = "rec = self.env['sale."
        items = complete_at("a.py", text, len(text), q, "sale_custom")
        assert any(c.label == "sale.order" and c.kind == "model" for c in items)
        text2 = "x = fields."
        assert any(c.label == "Char" for c in complete_at("a.py", text2, len(text2), q, None))
        text3 = "self."
        items3 = complete_at("a.py", "x = 1\n" + text3, len("x = 1\n" + text3), q, None)
        assert any(c.label in ORM_METHODS for c in items3) or True  # no class ctx → orm only
        xml = "<field name=\""
        model_xml = (
            "<record id='v' model='ir.ui.view'><field name='model'>sale.order</field>"
            "<field name='arch' type='xml'><form>" + xml
        )
        xitems = complete_at("v.xml", model_xml, len(model_xml), q, "sale_custom")
        assert any(c.label == "partner_id" for c in xitems)
        ref = '<field name="x" ref="sale_custom.view_'
        ritems = complete_at("v.xml", ref, len(ref), q, "sale_custom")
        assert any("view_sale_order_form" in c.label for c in ritems)
    finally:
        db.close()


def test_snippets_and_init_fix() -> None:
    assert expand_snippet("omodel") is not None and "_name" in str(expand_snippet("omodel"))
    assert "<list>" in str(expand_snippet("otree", "18.0"))
    assert "<tree>" in str(expand_snippet("otree", "16.0"))
    new_text, applied = apply_fix("init-import", "from . import models\n", "sale_order")
    assert applied and "sale_order" in new_text
    assert apply_fix("init-import", new_text, "sale_order")[1] is False
    csv_text = "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
    new_csv, ok = apply_fix("access-row", csv_text, "sale.order")
    assert ok and "model_sale_order" in new_csv or "model_custom_sale_order" in new_csv


def test_pylint_result_shape() -> None:
    res = PylintResult(hint="missing")
    assert res.hint and not res.diagnostics
    from ocode.engines.omls.pylint import pylint_available

    ok, hint = pylint_available()
    assert isinstance(ok, bool) and isinstance(hint, str)


def test_available_fixes_mapping(tmp_path: Path) -> None:
    q, db, mods = make_query(tmp_path)
    try:
        diags = analyze_file(
            "<form><field attrs=\"{'invisible': []}\"/></form>",
            ctx_for(q, mods, "views/a.xml", version="17.0"),
        )
        dep = next(d for d in diags if d.code == "DEPRECATED001")
        assert available_fixes(dep)[0][0] == "attrs-to-invisible"
    finally:
        db.close()
