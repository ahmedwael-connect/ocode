"""Config hierarchy: defaults, user file, workspace file."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10 fallback
    import tomli as tomllib  # type: ignore[import-not-found]


DEFAULTS: dict[str, Any] = {
    "editor": {
        "tab_width": 4,
        "insert_spaces": True,
        "trim_trailing_ws": True,
        "ensure_final_newline": True,
    },
    "ui": {"theme": "dark", "ascii": False},
    "index": {"enabled": True, "max_lines": 20000},
    "server": {"lint_before_restart": "warn"},
}


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as f:
            data: Any = tomllib.load(f)
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except OSError:
        return {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(value, dict) and isinstance(existing, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def default_config_dir() -> Path:
    override = os.environ.get("OCODE_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "ocode"


@dataclass
class OcodeConfig:
    data: dict[str, Any] = field(default_factory=dict)
    user_path: Path | None = None
    workspace_path: Path | None = None

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def load_config(workspace: Path | None = None, config_dir: Path | None = None) -> OcodeConfig:
    user_dir = config_dir or default_config_dir()
    user_path = user_dir / "config.toml"
    ws_path = (workspace / ".ocode" / "config.toml") if workspace else None

    data: dict[str, Any] = dict(DEFAULTS)
    data = _deep_merge(data, _load_toml(user_path))
    if ws_path is not None:
        data = _deep_merge(data, _load_toml(ws_path))
    return OcodeConfig(data=data, user_path=user_path, workspace_path=ws_path)
