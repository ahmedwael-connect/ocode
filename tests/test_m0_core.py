"""M0 core tests."""

from __future__ import annotations

from pathlib import Path

from ocode.__main__ import parse_position
from ocode.app import build_default_commands
from ocode.core.commands import CommandRegistry
from ocode.core.config import load_config
from ocode.core.events import EventBus


async def test_eventbus_emit_calls_sync_and_async() -> None:
    bus = EventBus()
    calls: list[str] = []

    def _sync() -> None:
        calls.append("sync")

    async def _async() -> None:
        calls.append("async")

    bus.subscribe("t", _sync)
    bus.subscribe("t", _async)
    n = await bus.emit("t")
    assert n == 2
    assert calls == ["sync", "async"]


async def test_eventbus_unsubscribe() -> None:
    bus = EventBus()
    calls: list[int] = []
    sub = bus.subscribe("t", lambda: calls.append(1))
    bus.unsubscribe(sub)
    assert await bus.emit("t") == 0


def test_commands_search_fuzzy() -> None:
    reg = build_default_commands()
    assert reg.get("ocode.file.save") is not None
    hits = reg.search("palett")
    assert hits and hits[0].id == "ocode.palette.open"
    assert len(CommandRegistry().search("x")) == 0


def test_config_hierarchy(tmp_path: Path, monkeypatch: object) -> None:
    user = tmp_path / "user"
    ws = tmp_path / "ws"
    (user).mkdir()
    (ws / ".ocode").mkdir(parents=True)
    (user / "config.toml").write_text('[ui]\ntheme = "light"\n', encoding="utf-8")
    (ws / ".ocode" / "config.toml").write_text('[ui]\ntheme = "odoo"\n', encoding="utf-8")
    cfg = load_config(workspace=ws, config_dir=user)
    assert cfg.get("ui.theme") == "odoo"
    assert cfg.get("editor.tab_width") == 4
    assert cfg.get("missing.key", "d") == "d"


def test_parse_position(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("x", encoding="utf-8")
    p, line, col = parse_position(f"{f}:10:3")
    assert p == f and line == 10 and col == 3


async def test_app_pilot_smoke() -> None:
    from ocode.app import OcodeApp

    app = OcodeApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#editor-placeholder") is not None
