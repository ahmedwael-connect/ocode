"""Version profile data (PRD §3.4 data/versions, M4)."""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found]


def version_profile(version: str) -> dict[str, object]:
    """Load data/versions/<major>.0.toml, falling back to 17.0."""
    major = (version or "").split(".")[0] or "17"
    base = Path(__file__).parent / "versions"
    for cand in (base / f"{major}.0.toml", base / "17.0.toml"):
        try:
            with cand.open("rb") as f:
                data: object = tomllib.load(f)
                if isinstance(data, dict):
                    return dict(data)
        except OSError:
            continue
    return {"version": "17.0", "tree_tag": "list", "attrs_deprecated": True}


__all__ = ["version_profile"]
