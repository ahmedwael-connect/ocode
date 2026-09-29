"""File/module tree models: ignores, lazy iteration, virtual groups (FR-SMN-001..006)."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

from ocode.engines.opd.module import ModuleInfo

DEFAULT_IGNORES = (
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "node_modules",
    ".git",
    ".hg",
    ".svn",
    "*.egg-info",
    ".mypy_cache",
    ".pytest_cache",
)

VIRTUAL_GROUPS: dict[str, tuple[str, ...]] = {
    "Models": ("models",),
    "Views": ("views",),
    "Security": ("security",),
    "Data": ("data",),
    "Controllers": ("controllers",),
    "Wizards": ("wizard", "wizards"),
    "Reports": ("report", "reports"),
    "Static": ("static",),
    "i18n": ("i18n",),
    "Tests": ("tests",),
}


def load_gitignore(root: Path) -> list[str]:
    try:
        lines = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def should_ignore(path: Path, root: Path, extra: tuple[str, ...] = DEFAULT_IGNORES) -> bool:
    name = path.name
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        rel = path.name
    for pat in extra:
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel, pat):
            return True
    for pat in load_gitignore(root):
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel, pat.rstrip("/")):
            return True
        if pat.endswith("/") and rel.startswith(pat):
            return True
    return False


def iter_files(root: Path, max_entries: int = 5000) -> list[Path]:
    """Non-recursive depth-first listing (lazy-friendly, capped)."""
    out: list[Path] = []
    stack: list[Path] = [root]
    while stack and len(out) < max_entries:
        cur = stack.pop()
        try:
            entries = sorted(cur.iterdir(), key=lambda p: (p.is_file(), p.name))
        except OSError:
            continue
        for e in entries:
            if should_ignore(e, root):
                continue
            if e.is_dir():
                stack.append(e)
            else:
                out.append(e)
                if len(out) >= max_entries:
                    break
    return out


@dataclass
class ModuleNode:
    info: ModuleInfo
    groups: dict[str, list[Path]] = field(default_factory=dict)


def group_for_dir(dirname: str) -> str | None:
    for group, names in VIRTUAL_GROUPS.items():
        if dirname in names:
            return group
    return None


def build_module_nodes(modules: list[ModuleInfo]) -> list[ModuleNode]:
    nodes: list[ModuleNode] = []
    for mod in modules:
        groups: dict[str, list[Path]] = {g: [] for g in VIRTUAL_GROUPS}
        others: list[Path] = []
        try:
            children = sorted(mod.path.iterdir(), key=lambda p: p.name)
        except OSError:
            children = []
        for child in children:
            if child.name in ("__manifest__.py", "__openerp__.py", "__init__.py"):
                others.append(child)
                continue
            if child.is_dir():
                g = group_for_dir(child.name)
                try:
                    files = sorted(p for p in child.rglob("*") if p.is_file())
                except OSError:
                    files = []
                if g:
                    groups[g].extend(files[:500])
                else:
                    others.extend(files[:200])
            elif child.is_file():
                others.append(child)
        groups["Other"] = others
        nodes.append(ModuleNode(info=mod, groups=groups))
    return nodes
