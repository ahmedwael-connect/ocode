"""Module scanning + manifest parsing (static, ast-based)."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModuleInfo:
    name: str  # technical name = folder name
    path: Path
    manifest_path: Path
    display_name: str = ""
    version: str = ""
    depends: list[str] = field(default_factory=list)
    data: list[str] = field(default_factory=list)
    kind: str = "custom"  # core | enterprise | custom | thirdparty


def is_module_dir(path: Path) -> bool:
    return (path / "__manifest__.py").is_file() or (path / "__openerp__.py").is_file()


def read_manifest(manifest: Path) -> dict[str, object]:
    """Parse manifest dict statically. Returns {} on failure."""
    try:
        src = manifest.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        node = ast.parse(src, filename=str(manifest))
    except SyntaxError:
        return {}
    for stmt in node.body:
        if isinstance(stmt, ast.Expr):
            val = stmt.value
            if isinstance(val, ast.Dict):
                try:
                    lit = ast.literal_eval(val)
                    if isinstance(lit, dict):
                        return dict(lit)
                except (ValueError, SyntaxError):
                    return {}
    return {}


def manifest_str(m: dict[str, object], key: str, default: str = "") -> str:
    v = m.get(key, default)
    return v if isinstance(v, str) else default


def manifest_str_list(m: dict[str, object], key: str) -> list[str]:
    v = m.get(key, [])
    if isinstance(v, list):
        return [x for x in v if isinstance(x, str)]
    return []
