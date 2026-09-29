"""Odoo root/version/conf/module/venv detection (FR-OPD-001..007)."""

from __future__ import annotations

import ast
import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path

from ocode.engines.opd.module import (
    ModuleInfo,
    is_module_dir,
    manifest_str,
    manifest_str_list,
    read_manifest,
)


@dataclass
class OdooConf:
    path: Path | None = None
    addons_path: list[Path] = field(default_factory=list)
    db_name: str = ""
    db_user: str = ""
    http_port: int = 8069
    logfile: str = ""
    data_dir: str = ""


@dataclass
class OdooProject:
    start: Path
    root: Path | None = None
    odoo_bin: Path | None = None
    version: str | None = None
    conf: OdooConf | None = None
    addons_paths: list[Path] = field(default_factory=list)
    modules: list[ModuleInfo] = field(default_factory=list)
    venv: Path | None = None
    systemd: str | None = None

    @property
    def found(self) -> bool:
        return self.root is not None


def _safe_is_file(p: Path) -> bool:
    try:
        return p.is_file()
    except OSError:
        return False


def _safe_is_dir(p: Path) -> bool:
    try:
        return p.is_dir()
    except OSError:
        return False


def _safe_exists(p: Path) -> bool:
    try:
        return p.exists()
    except OSError:
        return False


_SKIP_SIBLING_SCAN: frozenset[str] = frozenset(
    {"/", "/tmp", "/proc", "/sys", "/dev", "/run", "/var"}
)


def _is_root_dir(d: Path) -> Path | None:
    """Return odoo-bin path if d looks like an Odoo root."""
    try:
        for cand in (d / "odoo-bin", d / "openerp-server"):
            if _safe_is_file(cand):
                return cand
        if _safe_is_file(d / "odoo" / "release.py"):
            # root with package dir but maybe no odoo-bin wrapper
            obin = d / "odoo-bin"
            return obin if _safe_exists(obin) else None
    except OSError:
        return None
    return None


def find_odoo_root(start: Path) -> tuple[Path | None, Path | None]:
    """Walk up from start; at each near level also scan siblings. Returns (root, odoo_bin)."""
    try:
        cur = start.resolve() if _safe_exists(start) else start.absolute()
    except OSError:
        cur = start.absolute()
    try:
        if cur.is_file():
            cur = cur.parent
    except OSError:
        pass

    def _is_root(d: Path) -> bool:
        try:
            return _is_root_dir(d) is not None or _safe_is_file(d / "odoo" / "release.py")
        except OSError:
            return False

    def _obin(d: Path) -> Path | None:
        try:
            hit = _is_root_dir(d)
        except OSError:
            return None
        if hit is None:
            return None
        try:
            return hit if hit.is_file() else None
        except OSError:
            return None

    ancestors = [cur, *cur.parents]
    for depth, cand in enumerate(ancestors):
        if _is_root(cand):
            return (cand, _obin(cand))
        # sibling scan only near the start (workspace-sized), never system dirs
        if depth <= 4 and str(cand) not in _SKIP_SIBLING_SCAN:
            try:
                children = [p for p in cand.iterdir() if _safe_is_dir(p)][:60]
            except OSError:
                children = []
            for child in children:
                if _is_root(child):
                    return (child, _obin(child))
        if cand == cand.parent:
            break
    # down-scan: children + grandchildren of start dir
    base = cur if _safe_is_dir(cur) else cur.parent
    try:
        l1 = [p for p in base.iterdir() if _safe_is_dir(p)] if _safe_is_dir(base) else []
    except OSError:
        l1 = []
    for depth_dirs in l1:
        if _is_root(depth_dirs):
            return (depth_dirs, _obin(depth_dirs))
        try:
            subs = list(depth_dirs.iterdir())
        except OSError:
            continue
        for sub in subs:
            try:
                if not sub.is_dir():
                    continue
            except OSError:
                continue
            if _is_root(sub):
                return (sub, _obin(sub))
    return (None, None)


def detect_version(root: Path) -> str | None:
    rel = root / "odoo" / "release.py"
    try:
        src = rel.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    info: tuple[str, ...] | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "version_info":
                    try:
                        lit = ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        lit = None
                    if isinstance(lit, (tuple, list)) and lit:
                        info = tuple(str(x) for x in lit)
    if info:
        major = info[0]
        minor = info[1] if len(info) > 1 else "0"
        return f"{major}.{minor}"
    return None


def find_conf(explicit: str | Path | None = None, root: Path | None = None) -> Path | None:
    cands: list[Path] = []
    if explicit:
        cands.append(Path(str(explicit)).expanduser())
    if root is not None:
        cands.append(root / "odoo.conf")
        cands.append(root / "debian" / "odoo.conf")
    cands.append(Path.cwd() / "odoo.conf")
    cands.append(Path.home() / ".odoorc")
    cands.append(Path("/etc/odoo.conf"))
    cands.append(Path("/etc/odoo/odoo.conf"))
    for c in cands:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    return None


def parse_odoo_conf(path: Path) -> OdooConf:
    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error):
        return OdooConf(path=path)

    def g(key: str, fallback: str = "") -> str:
        try:
            if parser.has_section("options"):
                return parser.get("options", key, fallback=fallback)
            return parser.defaults().get(key, fallback)
        except configparser.Error:
            return fallback

    raw_addons = g("addons_path", "")
    addons: list[Path] = []
    for part in raw_addons.replace("\n", ",").split(","):
        part = part.strip()
        if part:
            addons.append(Path(part).expanduser())
    try:
        port = int(g("http_port", "8069") or "8069")
    except ValueError:
        port = 8069
    return OdooConf(
        path=path,
        addons_path=addons,
        db_name=g("db_name", ""),
        db_user=g("db_user", g("dbuser", "")),
        http_port=port,
        logfile=g("logfile", ""),
        data_dir=g("data_dir", ""),
    )


def classify_module(mod_path: Path, root: Path | None, addons_paths: list[Path]) -> str:
    parts = {p.lower() for p in mod_path.parts}
    try:
        rel = mod_path.relative_to(root) if root else None
    except ValueError:
        rel = None
    rel_s = str(rel) if rel else ""
    if root and ("odoo" in parts or "addons" in rel_s.split("/")):
        if rel and rel.parts and rel.parts[0] in ("odoo", "addons", "odoo/addons"):
            return "core"
        if rel_s.startswith(("odoo/addons", "addons")):
            return "core"
    if "enterprise" in parts:
        return "enterprise"
    # inside declared addons paths but not core → custom; else thirdparty
    for ap in addons_paths:
        try:
            mod_path.resolve().relative_to(ap.resolve())
            return "custom"
        except (ValueError, OSError):
            continue
    return "thirdparty" if root else "custom"


def scan_modules(addons_paths: list[Path], root: Path | None = None) -> list[ModuleInfo]:
    found: dict[str, ModuleInfo] = {}
    for ap in addons_paths:
        try:
            entries = sorted(ap.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if not is_module_dir(entry):
                continue
            manifest = entry / "__manifest__.py"
            if not manifest.is_file():
                manifest = entry / "__openerp__.py"
            data = read_manifest(manifest)
            mod = ModuleInfo(
                name=entry.name,
                path=entry,
                manifest_path=manifest,
                display_name=manifest_str(data, "name", entry.name),
                version=manifest_str(data, "version", ""),
                depends=manifest_str_list(data, "depends"),
                data=manifest_str_list(data, "data"),
                kind=classify_module(entry, root, addons_paths),
            )
            found.setdefault(entry.name, mod)
    return sorted(found.values(), key=lambda m: m.name)


def detect_venv(root: Path | None, odoo_bin: Path | None = None) -> Path | None:
    env = os.environ.get("VIRTUAL_ENV")
    if env and Path(env).is_dir():
        return Path(env)
    cands: list[Path] = []
    if odoo_bin is not None:
        cands.append(odoo_bin.parent / "venv")
        cands.append(odoo_bin.parent / ".venv")
    if root is not None:
        cands += [root / "venv", root / ".venv", root / ".env"]
    for c in cands:
        try:
            if (c / "bin" / "python").exists() or (c / "bin" / "python3").exists():
                return c
        except OSError:
            continue
    return None


def detect_systemd(unit_dir: Path = Path("/etc/systemd/system")) -> str | None:
    try:
        units = sorted(unit_dir.glob("odoo*.service"))
    except OSError:
        return None
    if not units:
        return None
    # prefer plain odoo.service
    names = [u.stem for u in units]
    if "odoo" in names:
        return "odoo"
    return names[0]


def default_addons_paths(root: Path) -> list[Path]:
    cands = [root / "addons", root / "odoo" / "addons"]
    return [p for p in cands if p.is_dir()]


def detect_project(
    start: Path,
    conf_override: str | Path | None = None,
    bin_override: str | Path | None = None,
) -> OdooProject:
    root, obin = find_odoo_root(start)
    if bin_override:
        obin = Path(str(bin_override)).expanduser()
        if root is None and obin.exists():
            root = obin.parent
    version = detect_version(root) if root else None
    conf_path = find_conf(conf_override, root)
    conf = parse_odoo_conf(conf_path) if conf_path else None
    addons: list[Path] = []
    if conf:
        addons.extend(p for p in conf.addons_path if p not in addons)
    if root:
        addons.extend(p for p in default_addons_paths(root) if p not in addons)
    modules = scan_modules(addons, root)
    venv = detect_venv(root, obin) if root else None
    systemd: str | None = None
    try:
        systemd = detect_systemd()
    except OSError:
        systemd = None
    return OdooProject(
        start=start,
        root=root,
        odoo_bin=obin,
        version=version,
        conf=conf,
        addons_paths=addons,
        modules=modules,
        venv=venv,
        systemd=systemd,
    )
