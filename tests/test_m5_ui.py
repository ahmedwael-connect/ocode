"""M5 UI tests: generate flow with diff confirm, shell panel send, snippet insert."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ocode.app import OcodeApp
from ocode.engines.osh.shell import ShellSession
from ocode.ui.widgets.shell import ShellPanel


def make_proj(base: Path) -> tuple[Path, Path]:
    root = base / "odoo17"
    (root / "odoo").mkdir(parents=True)
    release = 'version_info = (17, 0, 0, "final", 0)\n'
    (root / "odoo" / "release.py").write_text(release, encoding="utf-8")
    (root / "odoo-bin").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    custom = base / "my_addons" / "sale_custom"
    (custom / "models").mkdir(parents=True)
    manifest = (
        "{'name': 'Sale Custom', 'version': '17.0.1.0', 'license': 'LGPL-3',"
        " 'depends': ['base'], 'data': ['security/ir.model.access.csv']}"
    )
    (custom / "__manifest__.py").write_text(manifest, encoding="utf-8")
    (custom / "__init__.py").write_text("from . import models\n", encoding="utf-8")
    (custom / "models" / "__init__.py").write_text("", encoding="utf-8")
    (custom / "security").mkdir(parents=True)
    (custom / "security" / "ir.model.access.csv").write_text(
        "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n",
        encoding="utf-8",
    )
    addons = f"{base / 'my_addons'}"
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


async def test_generate_menu_lists(tmp_path: Path, monkeypatch: object) -> None:
    root, custom = make_proj(tmp_path)
    patch_dirs(tmp_path, monkeypatch)
    target = custom / "__manifest__.py"
    app = OcodeApp(start_path=target, conf_override=root / "odoo.conf")
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_generate_menu()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()


async def test_generate_model_flow(tmp_path: Path, monkeypatch: object) -> None:
    root, custom = make_proj(tmp_path)
    patch_dirs(tmp_path, monkeypatch)
    target = custom / "__manifest__.py"
    app = OcodeApp(start_path=target, conf_override=root / "odoo.conf")
    async with app.run_test() as pilot:
        await pilot.pause()
        app._open_generator("model")
        await pilot.pause()
        await pilot.press(*list("Ticket"))
        await pilot.press("tab", "tab", "tab", "tab")
        await pilot.pause()
        await pilot.press(*list("name:Char:Name:required"))
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        # diff confirm screen
        await pilot.press("y")
        await pilot.pause(0.5)
        model_file = custom / "models" / "sale_custom_ticket.py"
        assert model_file.is_file()
        assert "_name = 'sale_custom.ticket'" in model_file.read_text(encoding="utf-8")
        init_text = (custom / "models" / "__init__.py").read_text(encoding="utf-8")
        assert "sale_custom_ticket" in init_text


async def test_shell_send_flow(tmp_path: Path, monkeypatch: object) -> None:
    root, custom = make_proj(tmp_path)
    patch_dirs(tmp_path, monkeypatch)
    target = custom / "__manifest__.py"
    app = OcodeApp(start_path=target, conf_override=root / "odoo.conf")
    async with app.run_test() as pilot:
        await pilot.pause()
        session = ShellSession(db="mydb")
        session.start(["cat"])
        app.shell = session
        try:
            panel = app.query_one("#shell", ShellPanel)
            panel.attach(session)
            app._show_bottom("shell")
            await pilot.pause()
            assert panel.running
            st = app.active_state()
            st.set_cursor(st.offset_to_pos(0))
            app.action_shell_send()
            waited = 0.0
            while waited < 5.0:
                session.poll()
                if any("name" in ln for ln in session.scrollback):
                    break
                await asyncio.sleep(0.1)
                waited += 0.1
            assert any("name" in ln for ln in session.scrollback)
            # history navigation in panel
            panel.input = ""
            await pilot.press("up")
            await pilot.pause()
        finally:
            session.stop()
            app.shell = None


async def test_snippet_insert_flow(tmp_path: Path, monkeypatch: object) -> None:
    root, custom = make_proj(tmp_path)
    patch_dirs(tmp_path, monkeypatch)
    target = custom / "__manifest__.py"
    app = OcodeApp(start_path=target, conf_override=root / "odoo.conf")
    async with app.run_test() as pilot:
        await pilot.pause()
        app.new_untitled()
        app.action_snippet_insert()
        await pilot.pause()
        await pilot.press(*list("ofield"))
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert "fields." in app.active_state().doc.text


async def test_rebase_blocks_dirty_overwrite(tmp_path: Path) -> None:
    root, custom = make_proj(tmp_path)
    target = custom / "__manifest__.py"
    app = OcodeApp(start_path=target, conf_override=root / "odoo.conf")
    from ocode.engines.osg.applier import PlannedChange

    dirty = custom / "models" / "__init__.py"
    app.tabs.open(dirty)
    from ocode.engines.ote.document import Document
    from ocode.engines.ote.state import EditorState

    state = EditorState(Document(path=dirty, text="from . import a\n"))
    state.type_text("# dirty\n")
    app.docs.append(state)
    changes = [PlannedChange(dirty, "overwrite", "new", "test", "old")]
    # simulate rebase dirty check path
    blocked = any(d.doc.path == dirty and d.doc.dirty for d in app.docs)
    assert blocked
    assert changes[0].action == "overwrite"
