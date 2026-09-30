"""Change planning: preview diffs, never silently overwrite (FR-OSG-009)."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PlannedChange:
    path: Path
    action: str  # create | overwrite | append | patch
    new_text: str
    detail: str = ""
    old_text: str = ""


def preview_diff(change: PlannedChange) -> str:
    old = change.old_text.splitlines(keepends=True) if change.old_text else []
    new = change.new_text.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old, new, fromfile=f"a/{change.path.name}", tofile=f"b/{change.path.name}"
    )
    return "".join(diff)


def plan_file(path: Path, new_text: str, detail: str = "") -> PlannedChange | None:
    """Plan create/overwrite for a file. None when identical (no-op)."""
    if path.exists():
        try:
            old = path.read_text(encoding="utf-8")
        except OSError:
            old = ""
        if old == new_text:
            return None
        return PlannedChange(path, "overwrite", new_text, detail, old)
    return PlannedChange(path, "create", new_text, detail, "")


def plan_ensure_contains(path: Path, snippet: str, detail: str = "") -> PlannedChange | None:
    """Plan append when snippet missing (idempotent)."""
    try:
        old = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError:
        old = ""
    if snippet.strip() in old:
        return None
    sep = "" if not old or old.endswith("\n") else "\n"
    return PlannedChange(path, "append" if old else "create", old + sep + snippet, detail, old)


def apply_changes(changes: list[PlannedChange], allow_overwrite: bool = True) -> list[Path]:
    """Write planned changes. Overwrites need allow_overwrite=True."""
    written: list[Path] = []
    for change in changes:
        if change.action == "overwrite" and not allow_overwrite:
            continue
        change.path.parent.mkdir(parents=True, exist_ok=True)
        change.path.write_text(change.new_text, encoding="utf-8")
        written.append(change.path)
    return written
