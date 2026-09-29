"""Swap/backup + crash recovery (FR-OTE-072, SES-lite for M1)."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path


def state_dir() -> Path:
    return Path.home() / ".local" / "state" / "ocode"


def swap_path_for(target: Path | None, tag: str = "anon") -> Path:
    d = state_dir() / "swap"
    d.mkdir(parents=True, exist_ok=True)
    key = str(target) if target else f"anon:{tag}:{time.time_ns()}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    name = (target.name if target else "untitled") + f".{digest}.swp"
    return d / name


class SwapManager:
    def __init__(self, swap_file: Path) -> None:
        self.swap_file = swap_file
        self.swap_file.parent.mkdir(parents=True, exist_ok=True)

    def write(self, text: str) -> None:
        tmp = self.swap_file.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self.swap_file)

    def read(self) -> str | None:
        try:
            return self.swap_file.read_text(encoding="utf-8")
        except OSError:
            return None

    def clear(self) -> None:
        try:
            self.swap_file.unlink(missing_ok=True)
        except OSError:
            pass

    def exists(self) -> bool:
        return self.swap_file.exists()

    @staticmethod
    def pending() -> list[Path]:
        d = state_dir() / "swap"
        if not d.is_dir():
            return []
        return sorted(d.glob("*.swp"))
