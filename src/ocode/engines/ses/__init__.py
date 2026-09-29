"""SES engine: session save/restore (FR-SES-001, M2 subset)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


def state_dir() -> Path:
    return Path.home() / ".local" / "state" / "ocode"


@dataclass
class CursorPos:
    line: int = 0
    col: int = 0


@dataclass
class SessionData:
    tabs: list[str | None] = field(default_factory=list)
    active: int = 0
    cursors: dict[str, CursorPos] = field(default_factory=dict)
    sidebar_visible: bool = True
    profile: str | None = None
    version: int = 1


class SessionManager:
    def __init__(self, workspace: Path) -> None:
        digest = hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()[:16]
        self.path = state_dir() / "sessions" / f"{workspace.name}-{digest}.json"

    def save(self, data: SessionData) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = asdict(data)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(raw, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def load(self) -> SessionData | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        try:
            cursors = {k: CursorPos(**v) for k, v in raw.get("cursors", {}).items()}
            return SessionData(
                tabs=raw.get("tabs", []),
                active=int(raw.get("active", 0)),
                cursors=cursors,
                sidebar_visible=bool(raw.get("sidebar_visible", True)),
                profile=raw.get("profile"),
            )
        except (TypeError, ValueError, AttributeError):
            return None

    def clear(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
