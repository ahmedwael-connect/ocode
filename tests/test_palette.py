"""Publish-sprint tests: command palette filter + dispatch, save-as."""

from __future__ import annotations

from pathlib import Path

from ocode.app import OcodeApp
from ocode.ui.screens.palette import CommandPalette


async def _boot(tmp_path: Path, monkeypatch: object) -> OcodeApp:
    import ocode.engines.ses as ses

    monkeypatch.setattr(ses, "state_dir", lambda: tmp_path / "state")
    target = tmp_path / "f.txt"
    target.write_text("hi\n", encoding="utf-8")
    return OcodeApp(start_path=target)


async def test_palette_toggle_sidebar(tmp_path: Path, monkeypatch: object) -> None:
    app = await _boot(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_show_palette()
        await pilot.pause()
        assert isinstance(app.screen, CommandPalette)
        await pilot.press(*list("sidebar"))
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one("#sidebar").display is False


async def test_palette_runs_unbound_command(tmp_path: Path, monkeypatch: object) -> None:
    from ocode.ui.widgets.editor import OcodeEditor

    app = await _boot(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_show_palette()
        await pilot.pause()
        await pilot.press(*list("vim toggle"))
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one("#editor", OcodeEditor).vim_enabled
        # escape cancels cleanly
        app.action_show_palette()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, CommandPalette)


async def test_save_as_flow(tmp_path: Path, monkeypatch: object) -> None:
    app = await _boot(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.pause()
        dest = tmp_path / "copy.txt"
        app._on_save_as(str(dest))
        await pilot.pause()
        assert dest.is_file()
        assert app.active_state().doc.path == dest
