"""Odoo-aware diagnostics: syntax + semantic rules (FR-OMLS-020..025)."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from ocode.engines.oki.csvparse import ACCESS_HEADER
from ocode.engines.oki.pyparse import parse_python
from ocode.engines.oki.query import OkiQuery
from ocode.engines.oki.xmlparse import parse_xml
from ocode.engines.opd.module import ModuleInfo

AUTO_FIELDS = {
    "id", "create_uid", "create_date", "write_uid", "write_date",
    "__last_update", "display_name",
}

DEFAULT_SEVERITY: dict[str, str] = {
    "PY001": "error",
    "XML001": "error",
    "CSV001": "error",
    "ODOO001": "error",
    "ODOO002": "error",
    "ODOO003": "warning",
    "ODOO004": "warning",
    "ODOO005": "warning",
    "ODOO006": "warning",
    "ODOO007": "warning",
    "ODOO008": "error",
    "MANIFEST001": "error",
    "MANIFEST002": "warning",
    "DEPRECATED001": "warning",
    "DEPRECATED002": "warning",
}


@dataclass
class Diagnostic:
    file: str
    line: int  # 1-based
    col: int  # 1-based
    severity: str  # error|warning|info|hint
    code: str
    message: str
    fix: str = ""  # fix id for Ctrl+. (may be empty)


@dataclass
class FileCtx:
    path: Path
    module: ModuleInfo | None = None
    manifest: dict[str, object] = field(default_factory=dict)
    module_files: list[str] = field(default_factory=list)
    query: OkiQuery | None = None
    version: str | None = None
    rules: dict[str, str] = field(default_factory=dict)


def _sev(code: str, ctx: FileCtx) -> str | None:
    override = ctx.rules.get(code, "")
    if override == "off":
        return None
    if override in ("error", "warning", "info", "hint"):
        return override
    return DEFAULT_SEVERITY.get(code, "warning")


def _emit(
    out: list[Diagnostic], ctx: FileCtx, code: str, msg: str,
    line: int = 1, col: int = 1, fix: str = "",
) -> None:
    sev = _sev(code, ctx)
    if sev is None:
        return
    out.append(Diagnostic(str(ctx.path), line, col, sev, code, msg, fix))


def _line_of(text: str, needle: str, start: int = 1) -> int:
    for i, ln in enumerate(text.splitlines(), start=1):
        if i >= start and needle in ln:
            return i
    return 1


def _major(version: str | None) -> int:
    try:
        return int((version or "").split(".")[0])
    except ValueError:
        return 0


def analyze_file(text: str, ctx: FileCtx) -> list[Diagnostic]:
    suffix = ctx.path.suffix.lower()
    name = ctx.path.name
    if name in ("__manifest__.py", "__openerp__.py"):
        return _analyze_manifest(text, ctx)
    if suffix == ".py":
        return _analyze_python(text, ctx)
    if suffix == ".xml":
        return _analyze_xml(text, ctx)
    if suffix == ".csv" and name == "ir.model.access.csv":
        return _analyze_access_csv(text, ctx)
    return []


def _analyze_python(text: str, ctx: FileCtx) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    try:
        ast.parse(text)
    except SyntaxError as exc:
        _emit(out, ctx, "PY001", f"Python syntax error: {exc.msg}",
              exc.lineno or 1, (exc.offset or 1))
        return out
    info = parse_python(text)
    q = ctx.query
    for cls in info.classes:
        models_here = ([cls.model_name] if cls.model_name else [])
        models_here += [i for i in cls.inherit if "." in i]
        for model in models_here:
            if q is not None and model not in q.models():
                _emit(out, ctx, "ODOO001", f"Unknown model '{model}'",
                      _line_of(text, model), fix="")
        for fld in cls.fields:
            if fld.comodel and q is not None and fld.comodel not in q.models():
                _emit(out, ctx, "ODOO001",
                      f"Unknown comodel '{fld.comodel}' on field '{fld.name}'",
                      _line_of(text, fld.name))
    # ODOO007: models/*.py must be imported in models/__init__.py
    is_models_py = ctx.path.parent.name == "models" and ctx.path.name != "__init__.py"
    if ctx.module is not None and is_models_py:
        init = ctx.module.path / "models" / "__init__.py"
        try:
            init_text = init.read_text(encoding="utf-8") if init.is_file() else ""
        except OSError:
            init_text = ""
        stem = ctx.path.stem
        if stem not in init_text:
            _emit(out, ctx, "ODOO007",
                  f"'{stem}' not imported in models/__init__.py",
                  1, fix="init-import")
    is_models_init = ctx.path.name == "__init__.py" and ctx.path.parent.name == "models"
    if ctx.module is not None and is_models_init:
        try:
            root_init = (ctx.module.path / "__init__.py").read_text(encoding="utf-8")
        except OSError:
            root_init = ""
        if "models" not in root_init:
            _emit(out, ctx, "ODOO007", "'models' not imported in module __init__.py",
                  1, fix="init-import-models")
    return out


def _analyze_xml(text: str, ctx: FileCtx) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    info = parse_xml(text)
    if not info.wellformed:
        _emit(out, ctx, "XML001", f"XML not well-formed: {info.error}")
        return out
    q = ctx.query
    if q is not None:
        for view in info.views:
            if view.model and view.model not in q.models():
                _emit(out, ctx, "ODOO001", f"Unknown model '{view.model}' in view '{view.xmlid}'",
                      _line_of(text, view.xmlid))
            elif view.model:
                known = set(q.merged_fields(view.model)) | AUTO_FIELDS
                for fname in view.fields:
                    if fname not in known:
                        _emit(out, ctx, "ODOO002",
                              f"Field '{fname}' not on model '{view.model}'",
                              _line_of(text, fname))
        for ref in info.refs:
            if "." in ref and not q.xmlid_exists(ref):
                _emit(out, ctx, "ODOO003", f"Unknown XML ID '{ref}'",
                      _line_of(text, ref))
        mine = {x.xmlid for x in info.xmlids}
        for dup in q.duplicate_xmlids():
            if dup in mine:
                _emit(out, ctx, "ODOO005", f"Duplicate XML ID '{dup}' (also defined elsewhere)",
                      _line_of(text, dup))
    # DEPRECATED001: attrs= on 17+
    if _major(ctx.version) >= 17 and "attrs=" in text:
        for i, ln in enumerate(text.splitlines(), start=1):
            if "attrs=" in ln:
                _emit(out, ctx, "DEPRECATED001",
                      "attrs= is deprecated on 17+; use invisible=/readonly=/required= directly",
                      i, fix="attrs-to-invisible")
    # DEPRECATED002: <tree on 18+
    if _major(ctx.version) >= 18 and re.search(r"<tree[\s>]", text):
        for i, ln in enumerate(text.splitlines(), start=1):
            if re.search(r"<tree[\s>]", ln):
                _emit(out, ctx, "DEPRECATED002",
                      "<tree> is deprecated on 18+; use <list>", i, fix="tree-to-list")
    return out


def _analyze_access_csv(text: str, ctx: FileCtx) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    lines = text.splitlines()
    if not lines:
        _emit(out, ctx, "CSV001", "Empty access CSV")
        return out
    header = [h.strip() for h in lines[0].split(",")]
    if header != ACCESS_HEADER:
        _emit(out, ctx, "CSV001",
              f"Expected header {','.join(ACCESS_HEADER)}", 1)
    return out


def _analyze_manifest(text: str, ctx: FileCtx) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    try:
        node = ast.parse(text)
    except SyntaxError as exc:
        _emit(out, ctx, "PY001", f"Manifest syntax error: {exc.msg}", exc.lineno or 1)
        return out
    data: dict[str, object] = {}
    for stmt in node.body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Dict):
            try:
                lit = ast.literal_eval(stmt.value)
                if isinstance(lit, dict):
                    data = dict(lit)
            except (ValueError, SyntaxError):
                pass
    for key in ("name", "version", "license"):
        if key not in data:
            _emit(out, ctx, "MANIFEST001", f"Manifest missing required key '{key}'", 1)
    version = data.get("version", "")
    bad_version = (
        isinstance(version, str) and version
        and not re.match(r"^\d+\.\d+(\.\d+){0,2}$", version)
    )
    if bad_version:
        _emit(out, ctx, "MANIFEST001",
              f"Bad version format '{version}' (expected e.g. 17.0.1.0)", 1)
    # ODOO008: unknown depends
    depends = data.get("depends", [])
    if isinstance(depends, list) and ctx.query is not None:
        known_modules = set(ctx.query.module_names())
        for dep in depends:
            if isinstance(dep, str) and dep not in known_modules:
                _emit(out, ctx, "ODOO008", f"Unknown dependency '{dep}'",
                      _line_of(text, dep))
    # ODOO004: data files listed but missing / present but unlisted
    data_files = data.get("data", [])
    listed: list[str] = []
    if isinstance(data_files, list):
        listed = [d for d in data_files if isinstance(d, str)]
    if ctx.module is not None:
        base = ctx.module.path
        for rel in listed:
            if not (base / rel).exists():
                _emit(out, ctx, "ODOO004", f"Manifest lists missing file '{rel}'",
                      _line_of(text, rel))
        for rel in ctx.module_files:
            p = base / rel
            if p.suffix in (".xml", ".csv") and p.parent.name in ("views", "security", "data"):
                if rel not in listed:
                    _emit(out, ctx, "ODOO004", f"File '{rel}' not listed in manifest data",
                          1, fix="manifest-data:" + rel)
        # MANIFEST002: security should come before views
        order = [d for d in listed if isinstance(d, str)]
        sec_idx = next((i for i, d in enumerate(order) if "security" in d), None)
        view_idx = next(
            (i for i, d in enumerate(order) if "/views/" in d or d.startswith("views/")),
            None,
        )
        if sec_idx is not None and view_idx is not None and sec_idx > view_idx:
            _emit(out, ctx, "MANIFEST002", "Security files should be listed before views", 1)
    return out


def analyze_module(
    module: ModuleInfo, files: dict[str, str], query: OkiQuery | None,
    version: str | None, rules: dict[str, str] | None = None,
) -> list[Diagnostic]:
    """Analyze a whole module (FR-OMLS-032 scope). `files`: relpath → text."""
    out: list[Diagnostic] = []
    manifest_text = ""
    manifest: dict[str, object] = {}
    for rel, text in files.items():
        if Path(rel).name in ("__manifest__.py", "__openerp__.py"):
            manifest_text = text
    if manifest_text:
        try:
            node = ast.parse(manifest_text)
            for stmt in node.body:
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Dict):
                    try:
                        lit = ast.literal_eval(stmt.value)
                        if isinstance(lit, dict):
                            manifest = dict(lit)
                    except (ValueError, SyntaxError):
                        pass
        except SyntaxError:
            pass
    rels = sorted(files)
    for rel, text in files.items():
        ctx = FileCtx(
            path=module.path / rel, module=module, manifest=manifest,
            module_files=rels, query=query, version=version, rules=rules or {},
        )
        out.extend(analyze_file(text, ctx))
    # ODOO006: models with _name but no access row (module-level, needs file text)
    if query is not None:
        defined: dict[str, str] = {}  # model → file
        for rel, text in files.items():
            if not rel.endswith(".py"):
                continue
            for cls in parse_python(text).classes:
                if cls.model_name:
                    defined.setdefault(cls.model_name, rel)
        access_text = ""
        for rel, text in files.items():
            if Path(rel).name == "ir.model.access.csv":
                access_text = text
                break
        for model, rel in defined.items():
            xmlid = "model_" + module.name + "_" + model.replace(".", "_")
            if xmlid not in access_text:
                sev = (rules or {}).get("ODOO006", DEFAULT_SEVERITY["ODOO006"])
                if sev != "off":
                    out.append(Diagnostic(
                        str(module.path / rel), 1, 1, sev, "ODOO006",
                        f"Model '{model}' has no access rule ({xmlid})",
                        fix="access-row:" + model,
                    ))
    return sorted(out, key=lambda d: (d.file, d.line))
