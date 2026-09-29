"""M3 UI tests: server toggle/restart, log links, panel toggle, profiles."""

from __future__ import annotations

import sys
from pathlib import Path

from ocode.app import OcodeApp
from ocode.engines.oss.profiles import ServerProfile
from ocode.ui.widgets.logpanel import LogLinkClicked, LogPanel


def stub_profile(script: Path) -> ServerProfile:
    return ServerProfile(name="dev", odoo_bin=str(script), python=sys.executable, db="mydb")


async def _boot_app(tmp_path: Path, monkeypatch: object, script_body: str) -> tuple[OcodeApp, Path]:
    import ocode.engines.ses as ses

    monkeypatch.setattr(ses, "state_dir", lambda: tmp_path / "state")
    script = tmp_path / "fake_odoo.py"
    script.write_text(script_body, encoding="utf-8")
    marvel = tmp_path / "ws"
    marvel.mkdir(exist_ok=True)
    target = marvel / "note.txt"
    target.write_text("hi\n", encoding="utf-8")
    app = OcodeApp(start_path=target)
    return app, script


async def test_server_toggle_start_stop(tmp_path: Path, monkeypatch: object) -> None:
    body = "import time, sys; print('odoo fake boot'); sys.stdout.flush(); time.sleep(30)\n"
    app, script = await _boot_app(tmp_path, monkeypatch, body)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.server is not None
        app.server.profile = stub_profile(script)
        await app.action_server_toggle()
        await pilot.pause(0.5)
        assert app.server.status == "Running"
        assert any("fake boot" in r.raw for r in app.server.logs.records())
        assert "Running" in app._server_status_text()
        await app.action_server_toggle()
        await pilot.pause(0.5)
        assert app.server.status == "Stopped"


async def test_server_restart_and_update_current(tmp_path: Path, monkeypatch: object) -> None:
    body = "import time, sys; print('boot2'); sys.stdout.flush(); time.sleep(30)\n"
    app, script = await _boot_app(tmp_path, monkeypatch, body)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.server is not None
        app.server.profile = stub_profile(script)
        await app.action_server_restart()
        await pilot.pause(0.5)
        assert app.server.status == "Running"
        # no current module in plain workspace → warning path, stays running
        await app.action_server_update_current()
        await pilot.pause()
        await app.server.stop()


async def test_log_link_opens_file(tmp_path: Path, monkeypatch: object) -> None:
    app, _ = await _boot_app(tmp_path, monkeypatch, "print('x')\n")
    async with app.run_test() as pilot:
        await pilot.pause()
        target = tmp_path / "ws" / "note.txt"
        panel = app.query_one("#logs", LogPanel)
        panel.feed_text(f"Traceback (most recent call last):\n  File \"{target}\", line 1, in f\n")
        assert panel.visible_links() == [(str(target), 1)]
        await app.on_log_link_clicked(LogLinkClicked(str(target), 1))
        await pilot.pause()
        assert app.active_state().doc.path == target


async def test_toggle_logs_and_clear(tmp_path: Path, monkeypatch: object) -> None:
    app, _ = await _boot_app(tmp_path, monkeypatch, "print('x')\n")
    async with app.run_test() as pilot:
        await pilot.pause()
        panel = app.query_one("#logs", LogPanel)
        assert panel.display is not False
        app.action_toggle_logs()
        await pilot.pause()
        assert panel.display is False
        app.action_toggle_logs()
        panel.feed_text("2026-01-01 00:00:01 ERROR db log: boom\n")
        assert len(panel.buffer) >= 1
        app.action_log_clear()
        assert len(panel.buffer) == 0


async def test_profile_saved_to_servers_toml(tmp_path: Path, monkeypatch: object) -> None:
    app, script = await _boot_app(tmp_path, monkeypatch, "print('x')\n")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.server is not None
        prof = stub_profile(script)
        app._on_profile_saved(prof)
        await pilot.pause()
        ws = app.project.root if app.project and app.project.root else app.start_path.parent
        assert (ws / ".ocode" / "servers.toml").is_file()
