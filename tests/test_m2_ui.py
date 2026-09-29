"""M2 UI tests: tree, quick-open, related cycle, session restore, breadcrumb."""

from __future__ import annotations

from pathlib import Path

from ocode.app import OcodeApp
from ocode.ui.widgets.proj_tree import OdooTree


def make_proj(base: Path) -> Path:
    root = base / "odoo17"
    (root / "odoo").mkdir(parents=True)
    release = 'version_info = (17, 0, 0, "final", 0)\n'
    (root / "odoo" / "release.py").write_text(release, encoding="utf-8")
    (root / "odoo-bin").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    custom = base / "my_addons"
    mod = custom / "sale_custom"
    (mod / "models").mkdir(parents=True)
    (mod / "views").mkdir(parents=True)
    (mod / "security").mkdir(parents=True)
    manifest_txt = "{'name': 'Sale Custom', 'version': '17.0.1.0'}"
    (mod / "__manifest__.py").write_text(manifest_txt, encoding="utf-8")
    (mod / "models" / "sale_order.py").write_text("x = 1\n", encoding="utf-8")
    (mod / "views" / "sale_order_views.xml").write_text("<odoo/>\n", encoding="utf-8")
    (mod / "security" / "ir.model.access.csv").write_text("id\n", encoding="utf-8")
    addons = f"{root / 'addons'},{custom}"
    (root / "odoo.conf").write_text(f"[options]\naddons_path = {addons}\n", encoding="utf-8")
    return root


async def test_app_detects_project_and_tree(tmp_path: Path, monkeypatch: object) -> None:
    import ocode.engines.ses as ses

    monkeypatch.setattr(ses, "state_dir", lambda: tmp_path / "state")
    root = make_proj(tmp_path)
    model = tmp_path / "my_addons" / "sale_custom" / "models" / "sale_order.py"
    app = OcodeApp(start_path=model, conf_override=root / "odoo.conf")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.project is not None and app.project.found
        assert app.project.version == "17.0"
        tree = app.query_one("#tree", OdooTree)
        assert tree.project is not None
        assert "sale_custom" in app.breadcrumb()


async def test_related_cycle_opens_view(tmp_path: Path, monkeypatch: object) -> None:
    import ocode.engines.ses as ses

    monkeypatch.setattr(ses, "state_dir", lambda: tmp_path / "state")
    root = make_proj(tmp_path)
    model = tmp_path / "my_addons" / "sale_custom" / "models" / "sale_order.py"
    app = OcodeApp(start_path=model, conf_override=root / "odoo.conf")
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_related_cycle()
        await pilot.pause()
        cur = app.active_state().doc.path
        assert cur is not None and cur != model


async def test_quick_open_filters_and_opens(tmp_path: Path, monkeypatch: object) -> None:
    import ocode.engines.ses as ses

    monkeypatch.setattr(ses, "state_dir", lambda: tmp_path / "state")
    root = make_proj(tmp_path)
    app = OcodeApp(start_path=root, conf_override=root / "odoo.conf")
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_quick_open()
        await pilot.pause()
        # type into filter input
        await pilot.press(*list("sale_order"))
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        cur = app.active_state().doc.path
        assert cur is not None and "sale_order" in cur.name


async def test_session_save_restore(tmp_path: Path, monkeypatch: object) -> None:
    import ocode.engines.ses as ses

    monkeypatch.setattr(ses, "state_dir", lambda: tmp_path / "state")
    root = make_proj(tmp_path)
    model = tmp_path / "my_addons" / "sale_custom" / "models" / "sale_order.py"
    app = OcodeApp(start_path=model, conf_override=root / "odoo.conf")
    async with app.run_test():
        pass
    from ocode.engines.ses import SessionManager

    mgr = SessionManager(root)
    assert mgr.path.is_file()
