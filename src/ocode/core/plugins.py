"""Plugin system: third-party extensions via entry points (M7).

Contract (group ``ocode.plugins``)::

    [project.entry-points."ocode.plugins"]
    myplug = "myplug:register"

    def register(api: PluginAPI) -> None:
        api.commands.register("myplug.hello", "Say Hello", lambda: api.notify("hi"))
        api.bus.subscribe("server.log", lambda record: ...)

A failing plugin never breaks the host: load errors are recorded and
reported, the app continues with the rest.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any

from ocode.core.commands import CommandRegistry
from ocode.core.events import EventBus

GROUP = "ocode.plugins"


@dataclass
class PluginAPI:
    """What a plugin may touch. Kept deliberately narrow."""

    commands: CommandRegistry
    bus: EventBus
    notify: Callable[[str], None] = lambda _msg: None
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class PluginInfo:
    name: str
    version: str = ""
    origin: str = ""


@dataclass
class PluginError:
    name: str
    error: str


class PluginRegistry:
    def __init__(self, api: PluginAPI, group: str = GROUP) -> None:
        self.api = api
        self.group = group
        self.loaded: list[PluginInfo] = []
        self.errors: list[PluginError] = []

    def discover(self) -> list[Any]:
        """Return entry points for the group (version-tolerant)."""
        try:
            eps = entry_points()
        except OSError:
            return []
        try:
            if hasattr(eps, "select"):
                return list(eps.select(group=self.group))
            get = getattr(eps, "get", None)
            if callable(get):
                return list(get(self.group, []))
            return list(eps)  # already an iterable of entry points (tests)
        except OSError:
            return []

    def load_all(self) -> list[PluginInfo]:
        for ep in self.discover():
            name = getattr(ep, "name", str(ep))
            try:
                target = ep.load()
            except Exception as exc:  # noqa: BLE001 - isolation by design
                self.errors.append(PluginError(name, f"load: {exc}"))
                continue
            try:
                register = target if callable(target) else getattr(target, "register", None)
                if not callable(register):
                    raise TypeError("no callable register(api) found")
                register(self.api)
            except Exception as exc:  # noqa: BLE001 - isolation by design
                self.errors.append(PluginError(name, f"register: {exc}"))
                continue
            version = getattr(target, "__version__", "") or ""
            origin = getattr(getattr(ep, "dist", None), "version", "") or ""
            self.loaded.append(PluginInfo(name, str(version), str(origin)))
        return list(self.loaded)
