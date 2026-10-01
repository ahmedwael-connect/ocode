"""M7 plugin tests: discovery, command/bus API, failure isolation, doctor line."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ocode.core.commands import CommandRegistry
from ocode.core.events import EventBus
from ocode.core.plugins import PluginAPI, PluginRegistry


class FakeEP:
    def __init__(self, name: str, target: Any = None, error: Exception | None = None) -> None:
        self.name = name
        self._target = target
        self._error = error

    def load(self) -> Any:
        if self._error is not None:
            raise self._error
        return self._target


def make_api() -> tuple[PluginAPI, list[str], list[str]]:
    seen_commands: list[str] = []
    seen_bus: list[str] = []

    def _notify(msg: str) -> None:
        seen_commands.append(msg)

    api = PluginAPI(CommandRegistry(), EventBus(), _notify)
    return (api, seen_commands, seen_bus)


def test_good_plugin_registers_command_and_bus(monkeypatch: object) -> None:
    import ocode.core.plugins as plugmod

    fired: list[str] = []

    def _register(api: PluginAPI) -> None:
        api.commands.register("plug.hello", "Say Hello", lambda: "hi")
        api.bus.subscribe("test.topic", lambda: fired.append("x"))

    monkeypatch.setattr(plugmod, "entry_points", lambda: [FakeEP("good", _register)])
    api, _, _ = make_api()
    registry = PluginRegistry(api)
    assert [p.name for p in registry.load_all()] == ["good"]
    assert api.commands.get("plug.hello") is not None

    import asyncio as _aio

    _aio.run(api.bus.emit("test.topic"))
    assert fired == ["x"]


def test_bad_plugin_isolated(monkeypatch: object) -> None:
    import ocode.core.plugins as plugmod

    def _boom(api: PluginAPI) -> None:
        raise RuntimeError("kaput")

    eps = [FakeEP("bad-load", error=ImportError("nope")),
           FakeEP("bad-reg", _boom),
           FakeEP("no-register", object()),
           FakeEP("good", lambda api: api.commands.register("plug.ok", "OK"))]
    monkeypatch.setattr(plugmod, "entry_points", lambda: eps)
    api, _, _ = make_api()
    registry = PluginRegistry(api)
    assert [p.name for p in registry.load_all()] == ["good"]
    assert len(registry.errors) == 3
    assert api.commands.get("plug.ok") is not None


def test_discover_tolerant(monkeypatch: object) -> None:
    import ocode.core.plugins as plugmod

    def _raise() -> None:
        raise OSError("damaged metadata")

    monkeypatch.setattr(plugmod, "entry_points", _raise)
    api, _, _ = make_api()
    assert PluginRegistry(api).discover() == []
    assert PluginRegistry(api).load_all() == []


async def test_app_mount_loads_plugin(tmp_path: Path, monkeypatch: object) -> None:
    import ocode.core.plugins as plugmod
    import ocode.engines.ses as ses

    monkeypatch.setattr(ses, "state_dir", lambda: tmp_path / "state")

    def _register(api: PluginAPI) -> None:
        api.commands.register("plug.from-app", "From App")

    monkeypatch.setattr(plugmod, "entry_points", lambda: [FakeEP("app-plug", _register)])
    from ocode.app import OcodeApp

    target = tmp_path / "f.txt"
    target.write_text("x\n", encoding="utf-8")
    app = OcodeApp(start_path=target)
    async with app.run_test():
        pass
    assert app.commands.get("plug.from-app") is not None
    assert [p.name for p in app.plugins.loaded] == ["app-plug"]


def test_doctor_plugins_line(capsys: object) -> None:
    from ocode.__main__ import main

    assert main(["doctor"]) == 0
    out = capsys.readouterr().out  # type: ignore[union-attr]
    assert "plugins:" in out
