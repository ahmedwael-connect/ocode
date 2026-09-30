"""M4 OKI tests: parsers, indexer, merged resolution, incremental updates."""

from __future__ import annotations

from pathlib import Path

from ocode.engines.oki.csvparse import parse_access_csv
from ocode.engines.oki.db import OkiDb
from ocode.engines.oki.indexer import Indexer
from ocode.engines.oki.pyparse import parse_python
from ocode.engines.oki.query import OkiQuery
from ocode.engines.oki.xmlparse import parse_xml
from ocode.engines.opd.module import ModuleInfo


def make_modules(base: Path) -> list[ModuleInfo]:
    sale = base / "sale"
    (sale / "models").mkdir(parents=True)
    manifest = "{'name': 'Sale', 'version': '17.0.1.0'}"
    (sale / "__manifest__.py").write_text(manifest, encoding="utf-8")
    (sale / "models" / "sale_order.py").write_text(
        "from odoo import models, fields, api\n"
        "class SaleOrder(models.Model):\n"
        "    _name = 'sale.order'\n"
        "    _description = 'Sale'\n"
        "    name = fields.Char(string='Name', required=True)\n"
        "    partner_id = fields.Many2one('res.partner', string='Partner')\n"
        "    @api.depends('name')\n"
        "    def _compute_x(self):\n"
        "        pass\n",
        encoding="utf-8",
    )
    custom = base / "sale_custom"
    (custom / "models").mkdir(parents=True)
    (custom / "views").mkdir(parents=True)
    (custom / "security").mkdir(parents=True)
    (custom / "__manifest__.py").write_text(
        "{'name': 'C', 'version': '17.0.1.0', 'depends': ['sale'],"
        " 'data': ['security/ir.model.access.csv', 'views/sale_order_views.xml']}",
        encoding="utf-8",
    )
    (custom / "models" / "sale_order.py").write_text(
        "from odoo import models, fields\n"
        "class SaleOrder(models.Model):\n"
        "    _inherit = 'sale.order'\n"
        "    x_ref = fields.Char(string='Ref')\n"
        "    partner_id = fields.Many2one('res.partner', string='Customer')\n",
        encoding="utf-8",
    )
    (custom / "views" / "sale_order_views.xml").write_text(
        '<?xml version="1.0"?>\n<odoo>\n'
        '  <record id="view_sale_order_form" model="ir.ui.view">\n'
        '    <field name="name">sale.order.form</field>\n'
        '    <field name="model">sale.order</field>\n'
        '    <field name="arch" type="xml">\n'
        '      <form><field name="name"/><field name="partner_id"/><field name="nope"/></form>\n'
        "    </field>\n  </record>\n"
        '  <record id="action_sale" model="ir.actions.act_window">\n'
        '    <field name="res_model">sale.order</field>\n'
        "  </record>\n</odoo>\n",
        encoding="utf-8",
    )
    (custom / "security" / "ir.model.access.csv").write_text(
        "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
        "access_sale_user,sale user,model_sale_order,base.group_user,1,1,1,0\n",
        encoding="utf-8",
    )
    sale_info = ModuleInfo("sale", sale, sale / "__manifest__.py")
    custom_info = ModuleInfo("sale_custom", custom, custom / "__manifest__.py")
    return [sale_info, custom_info]


def test_pyparse_models_fields_methods() -> None:
    info = parse_python(
        "from odoo import models, fields, api\n"
        "class A(models.Model):\n"
        "    _name = 'a.b'\n"
        "    _inherit = ['a.c']\n"
        "    x = fields.Many2one('res.partner', string='P', required=True)\n"
        "    @api.depends('x')\n"
        "    def f(self): pass\n"
    )
    assert len(info.classes) == 1
    cls = info.classes[0]
    assert (cls.model_name, cls.inherit) == ("a.b", ["a.c"])
    assert cls.fields[0].comodel == "res.partner" and cls.fields[0].required
    assert cls.methods[0].decorators == ["api.depends"]
    assert parse_python("def broken(:").classes == []


def test_xmlparse_views_refs() -> None:
    info = parse_xml(
        "<odoo><record id='v' model='ir.ui.view'>"
        "<field name='model'>sale.order</field>"
        "<field name='inherit_id' ref='sale.view'/>"
        "<field name='arch' type='xml'><form><field name='name'/></form></field>"
        "</record></odoo>"
    )
    assert info.wellformed
    assert info.views[0].model == "sale.order"
    assert info.views[0].inherit_id == "sale.view"
    assert info.views[0].fields == ["name"]
    bad = parse_xml("<odoo><unclosed>")
    assert not bad.wellformed and bad.error


def test_access_csv() -> None:
    header, rows = parse_access_csv(
        "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
        "a,b,model_sale_order,g,1,1,0,0\n"
    )
    assert header[:4] == ["id", "name", "model_id:id", "group_id:id"]
    assert rows[0].model_xmlid == "model_sale_order"


def test_indexer_build_and_query(tmp_path: Path) -> None:
    mods = make_modules(tmp_path)
    db = OkiDb(tmp_path / "idx.sqlite")
    stats = Indexer(db, mods).build()
    try:
        assert stats.models >= 2 and stats.fields >= 4 and stats.xmlids >= 2
        q = OkiQuery(db)
        assert "sale.order" in q.models()
        merged = q.merged_fields("sale.order")
        # extension overrides partner string, adds x_ref, keeps name
        assert merged["partner_id"]["string"] == "Customer"
        assert merged["x_ref"]["type"] == "Char"
        assert merged["name"]["required"] is True
        assert "_compute_x" in q.methods_of("sale.order")
        assert q.xmlid_exists("sale_custom.view_sale_order_form")
        assert not q.xmlid_exists("nope.missing")
        assert q.depends_closure("sale_custom") == {"sale_custom", "sale"}
        views = q.views_for_model("sale.order")
        assert views and views[0]["fields"] == ["name", "partner_id", "nope"]
        assert q.stats()["modules"] == 2
    finally:
        db.close()


def test_indexer_incremental_and_prune(tmp_path: Path) -> None:
    mods = make_modules(tmp_path)
    db = OkiDb(tmp_path / "idx.sqlite")
    idx = Indexer(db, mods)
    try:
        idx.build()
        target = tmp_path / "sale_custom" / "models" / "sale_order.py"
        assert idx.update_file(target) is False  # unchanged
        target.write_text(target.read_text(encoding="utf-8") + "    y = 1\n", encoding="utf-8")
        assert idx.update_file(target) is True
        assert idx.update_file(target) is False
        target.unlink()
        assert idx.prune_missing() >= 1
    finally:
        db.close()
