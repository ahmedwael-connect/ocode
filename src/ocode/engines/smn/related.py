"""Related-file jumping via naming conventions (FR-SMN-020..022, M2).

OKI-backed resolution lands in M4; M2 uses manifest + filename heuristics
which already cover the standard module layout.
"""

from __future__ import annotations

from pathlib import Path

from ocode.engines.opd.module import ModuleInfo

KEY_KINDS = ("manifest", "init", "access", "views", "conf")


def find_module_dir(path: Path, modules: list[ModuleInfo]) -> ModuleInfo | None:
    path = path.resolve() if path.exists() else path.absolute()
    best: ModuleInfo | None = None
    best_len = -1
    for mod in modules:
        try:
            base = mod.path.resolve() if mod.path.exists() else mod.path.absolute()
            path.relative_to(base)
            if len(base.parts) > best_len:
                best, best_len = mod, len(base.parts)
        except ValueError:
            continue
    return best


def key_file(mod: ModuleInfo, kind: str, conf: Path | None = None) -> Path | None:
    base = mod.path
    if kind == "manifest":
        for cand in (base / "__manifest__.py", base / "__openerp__.py"):
            if cand.is_file():
                return cand
        return base / "__manifest__.py"
    if kind == "init":
        return base / "__init__.py"
    if kind == "access":
        return base / "security" / "ir.model.access.csv"
    if kind == "views":
        views = sorted((base / "views").glob("*.xml")) if (base / "views").is_dir() else []
        return views[0] if views else None
    if kind == "conf":
        return conf
    return None


def _stem_variants(stem: str) -> list[str]:
    """sale_order ↔ sale_order_views, sale.order ↔ sale_order, etc."""
    variants = [stem]
    suffixes: tuple[str, ...] = (
        "_views",
        "_view",
        "_templates",
        "_template",
        "_menus",
        "_menu",
        "_data",
        "_security",
    )
    for suffix in suffixes:
        if stem.endswith(suffix):
            variants.append(stem[: -len(suffix)])
        else:
            variants.append(stem + suffix)
    variants.append(stem.replace(".", "_"))
    return list(dict.fromkeys(variants))


def related_files(current: Path, modules: list[ModuleInfo]) -> list[Path]:
    """Ordered related targets for `current` (cycle order for Alt+M)."""
    mod = find_module_dir(current, modules)
    if mod is None:
        return []
    base = mod.path
    ordered: list[Path] = []

    def push(p: Path | None) -> None:
        if p is not None and p != current and p not in ordered:
            ordered.append(p)

    # key files first (manifest, init, access, main views)
    push(key_file(mod, "manifest"))
    push(key_file(mod, "init"))
    push(key_file(mod, "access"))
    for v in sorted((base / "views").glob("*.xml")) if (base / "views").is_dir() else []:
        push(v)

    # model ↔ view stem heuristic
    stem = current.stem
    suffix = current.suffix.lower()
    search_dirs: list[Path] = []
    if current.parent.name == "models" and suffix == ".py":
        search_dirs = [base / "views", base / "security", base / "data"]
    elif current.parent.name == "views" and suffix == ".xml":
        search_dirs = [base / "models", base / "security", base / "data"]
    elif current.parent.name == "security":
        search_dirs = [base / "models", base / "views"]
    for variant in _stem_variants(stem):
        for d in search_dirs:
            for ext in (".py", ".xml", ".csv"):
                cand = d / f"{variant}{ext}"
                push(cand if cand.is_file() else None)
                # <name>_views.xml pattern for models
                cand2 = d / f"{variant}_views.xml"
                if cand2.is_file():
                    push(cand2)

    # data / reports / wizards / tests / i18n siblings
    sib_folders: tuple[str, ...] = (
        "data",
        "report",
        "reports",
        "wizard",
        "wizards",
        "tests",
        "i18n",
        "controllers",
        "static",
    )
    for folder in sib_folders:
        d = base / folder
        if d.is_dir():
            try:
                for f in sorted(d.rglob("*")):
                    if f.is_file() and f != current and len(ordered) < 40:
                        # prefer same-stem matches
                        if stem in f.stem or not any(stem in str(o) for o in ordered):
                            push(f if f.is_file() else None)
            except OSError:
                continue
    return [p for p in ordered if p.is_file() or p.parent.is_dir()][:40]


def cycle_related(current: Path, modules: list[ModuleInfo]) -> Path | None:
    """Next related file after current (Alt+M cycle)."""
    rel = related_files(current, modules)
    if not rel:
        return None
    # if current is inside the related set, step to next; else first
    if current in rel:
        return rel[(rel.index(current) + 1) % len(rel)]
    return rel[0]
