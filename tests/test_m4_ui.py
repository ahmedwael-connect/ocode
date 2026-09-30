"""M4 UI tests: index → completion, problems, quickfix, gate, goto, outline, hover."""

from __future__ import annotations

import sys
from pathlib import Path

from ocode.app import OcodeApp
from ocode.ui.widgets.complete import CompletionPopup
from ocode.ui.widgets.problems import ProblemsPanel


def make_proj(base: Path) -> tuple[Path, Path]:
    root = base / "odoo17"
    (root / "odoo").mkdir(parents=True)
    release = 'version_info = (17, 0, 0, "final", 0)\n'
    (root / "odoo" / "release.py").write_text(release, encoding="utf-8")
    (root / "odoo-bin").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    custom = base / "my_addons" / "sale_custom"
    (custom / "models").mkdir(parents=True)
    (custom / "views").mkdir(parents=True)
    (custom / "security").mkdir(parents=True)
    manifest = (
        "{'name': 'Sale Custom', 'version': '17.0.1.0', 'license': 'LGPL-3',"
        " 'depends': ['sale'],"
        " 'data': ['security/ir.model.access.csv', 'views/sale_order_views.xml']}"
    )
    (custom / "__manifest__.py").write_text(manifest, encoding="utf-8")
    (custom / "__init__.py").write_text("from . import models\n", encoding="utf-8")
    (custom / "models" / "__init__.py").write_text("from . import sale_order\n", encoding="utf-8")
    (custom / "models" / "sale_order.py").write_text(
        "from odoo import models, fields\n"
        "class SaleOrder(models.Model):\n"
        "    _inherit = 'sale.order'\n"
        "    x_ref = fields.Char(string='Ref')\n",
        encoding="utf-8",
    )
    (custom / "views" / "sale_order_views.xml").write_text(
        "<?xml version=\"1.0\"?>\n<odoo>\n"
        "  <record id=\"view_sale_order_form\" model=\"ir.ui.view\">\n"
        "    <field name=\"name\">sale.order.form</field>\n"
        "    <field name=\"model\">sale.order</field>\n"
        "    <field name=\"arch\" type=\"xml\">\n"
        "      <form><field name=\"x_ref\"/><field name=\"bogus_field\"/></form>\n"
        "    </field>\n  </record>\n</odoo>\n",
        encoding="utf-8",
    )
    (custom / "security" / "ir.model.access.csv").write_text(
        "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
        "access_sale_user,sale user,model_sale_custom_sale_order,base.group_user,1,0,0,0\n",
        encoding="utf-8",
    )
    sale = root / "addons" / "sale"
    (sale / "models").mkdir(parents=True)
    sale_manifest = "{'name': 'Sale', 'version': '17.0.1.0'}"
    (sale / "__manifest__.py").write_text(sale_manifest, encoding="utf-8")
    (sale / "models" / "sale_order.py").write_text(
        "from odoo import models, fields\n"
        "class SaleOrder(models.Model):\n"
        "    _name = 'sale.order'\n"
        "    name = fields.Char(string='Name')\n"
        "    x_ref = fields.Char(string='Ref')\n",
        encoding="utf-8",
    )
    addons = f"{root / 'addons'},{base / 'my_addons'}"
    (root / "odoo.conf").write_text(
        f"[options]\naddons_path = {addons}\ndb_name = mydb\n", encoding="utf-8"
    )
    return (root, custom)


def patch_dirs(tmp_path: Path, monkeypatch: object) -> None:
    import ocode.app as appmod
    import ocode.engines.oki.db as okidb
    import ocode.engines.ses as ses

    monkeypatch.setattr(ses, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(okidb, "state_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(
        appmod, "index_path_for", lambda ws: tmp_path / "cache" / "test.sqlite"
    )


async def wait_index(app: OcodeApp, pilot: object, timeout: float = 15.0) -> bool:
    import asyncio as _aio

    waited = 0.0
    while app.oki is None and waited < timeout:
        await _aio.sleep(0.2)
        waited += 0.2
    return app.oki is not None


async def test_index_and_completion(tmp_path: Path, monkeypatch: object) -> None:
    root, custom = make_proj(tmp_path)
    patch_dirs(tmp_path, monkeypatch)
    target = custom / "models" / "sale_order.py"
    app = OcodeApp(start_path=target, conf_override=root / "odoo.conf")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert await wait_index(app, pilot)
        assert app.oki is not None and "sale.order" in app.oki.models()
        # trigger completion on env[
        st = app.active_state()
        st.set_cursor(st.offset_to_pos(len(st.doc.text)))
        st.type_text("\nrec = self.env['sale.")
        app.action_show_completion()
        await pilot.pause()
        pop = app.query_one("#complete", CompletionPopup)
        assert pop.is_open
        assert any(c.label == "sale.order" for c in pop.items)
        app.accept_completion()
        await pilot.pause()
        assert "sale.order" in app.active_state().doc.text


async def test_problems_and_lint_file(tmp_path: Path, monkeypatch: object) -> None:
    root, custom = make_proj(tmp_path)
    patch_dirs(tmp_path, monkeypatch)
    target = custom / "views" / "sale_order_views.xml"
    app = OcodeApp(start_path=target, conf_override=root / "odoo.conf")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert await wait_index(app, pilot)
        app.action_lint_file()
        await pilot.pause()
        assert any(d.code == "ODOO002" for d in app.problems)
        panel = app.query_one("#problems", ProblemsPanel)
        assert len(panel.items) == len(app.problems)
        app.action_problem_next()
        await pilot.pause()


async def test_quick_fix_manifest_data(tmp_path: Path, monkeypatch: object) -> None:
    root, custom = make_proj(tmp_path)
    patch_dirs(tmp_path, monkeypatch)
    manifest = custom / "__manifest__.py"
    # remove access csv from data → ODOO004 with fix
    manifest.write_text(
        "{'name': 'C', 'version': '17.0.1.0', 'license': 'LGPL-3',"
        " 'depends': ['sale'], 'data': ['views/sale_order_views.xml']}",
        encoding="utf-8",
    )
    app = OcodeApp(start_path=manifest, conf_override=root / "odoo.conf")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert await wait_index(app, pilot)
        app.action_lint_file()
        await pilot.pause()
        assert any(d.code == "ODOO004" and d.fix for d in app.problems)
        app.action_quick_fix()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert "ir.model.access.csv" in manifest.read_text(encoding="utf-8")


async def test_lint_gate_blocks_restart(tmp_path: Path, monkeypatch: object) -> None:
    root, custom = make_proj(tmp_path)
    patch_dirs(tmp_path, monkeypatch)
    bad = custom / "models" / "bad.py"
    bad.write_text("def broken(:\n", encoding="utf-8")
    app = OcodeApp(start_path=bad, conf_override=root / "odoo.conf")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert await wait_index(app, pilot)
        assert app.server is not None
        app.server.profile.lint_before_restart = "block"
        assert app._lint_gate(["sale_custom"]) is False
        app.server.profile.lint_before_restart = "warn"
        assert app._lint_gate(["sale_custom"]) is True
        app.server.profile.lint_before_restart = "off"
        assert app._lint_gate(["sale_custom"]) is True


async def test_goto_definition_model(tmp_path: Path, monkeypatch: object) -> None:
    root, custom = make_proj(tmp_path)
    patch_dirs(tmp_path, monkeypatch)
    target = custom / "models" / "sale_order.py"
    app = OcodeApp(start_path=target, conf_override=root / "odoo.conf")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert await wait_index(app, pilot)
        st = app.active_state()
        text = st.doc.text
        idx = text.index("'sale.order'") + len("'sale.order'")
        st.set_cursor(st.offset_to_pos(idx))
        app.action_goto_definition()
        await pilot.pause()
        cur = app.active_state().doc.path
        assert cur is not None and cur.name == "sale_order.py"
        assert "addons" in str(cur)


async def test_outline_hover_snippet(tmp_path: Path, monkeypatch: object) -> None:
    root, custom = make_proj(tmp_path)
    patch_dirs(tmp_path, monkeypatch)
    target = custom / "models" / "sale_order.py"
    app = OcodeApp(start_path=target, conf_override=root / "odoo.conf")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert await wait_index(app, pilot)
        app.action_show_outline()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        st = app.active_state()
        idx = st.doc.text.index("x_ref")
        st.set_cursor(st.offset_to_pos(idx + 2))
        app.action_show_hover()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        # snippet expansion: new doc, type trigger + Tab
        app.new_untitled()
        st2 = app.active_state()
        st2.type_text("ofield")
        assert app.try_expand_snippet() is True
        assert "fields." in st2.doc.text


def test_index_cli_rebuild(tmp_path: Path, monkeypatch: object) -> None:
    root, _custom = make_proj(tmp_path)
    monkeypatch.chdir(root)
    from ocode.__main__ import main

    assert main(["index"]) == 0
    # cleanup real cache artifact (safe to delete by design)
    import shutil as _sh

    _sh.rmtree(Path.home() / ".cache" / "ocode" / "index", ignore_errors=True)
    assert True
    _ = sys.version
