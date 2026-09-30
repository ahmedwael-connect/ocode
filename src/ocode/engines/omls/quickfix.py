"""Quick fixes: pure text transforms bound to diagnostic codes (FR-OMLS-024)."""

from __future__ import annotations

import re

from ocode.engines.omls.diagnostics import Diagnostic


def available_fixes(diag: Diagnostic) -> list[tuple[str, str]]:
    """Return (fix_id, title) options for a diagnostic."""
    if diag.fix:
        return [(diag.fix, _TITLE.get(diag.fix.split(":")[0], diag.fix))]
    if diag.code in ("DEPRECATED001", "DEPRECATED002"):
        fix = "attrs-to-invisible" if diag.code == "DEPRECATED001" else "tree-to-list"
        return [(fix, _TITLE[fix])]
    return []


_TITLE = {
    "init-import": "Add import to models/__init__.py",
    "init-import-models": "Add 'models' to module __init__.py",
    "manifest-data": "Add file to manifest data",
    "manifest-depends": "Add module to manifest depends",
    "access-row": "Add access rule to ir.model.access.csv",
    "attrs-to-invisible": "Convert attrs= to invisible=",
    "tree-to-list": "Convert <tree> to <list>",
}


def apply_fix(fix_id: str, text: str, arg: str = "") -> tuple[str, bool]:
    """Apply fix to file text. Returns (new_text, applied)."""
    kind = fix_id.split(":")[0]
    payload = fix_id.split(":", 1)[1] if ":" in fix_id else arg
    if kind == "init-import":
        return _add_init_import(text, payload)
    if kind == "init-import-models":
        return _add_init_import(text, "models")
    if kind == "manifest-data":
        return _add_manifest_list_entry(text, "data", payload)
    if kind == "manifest-depends":
        return _add_manifest_list_entry(text, "depends", payload)
    if kind == "access-row":
        return _add_access_row(text, payload)
    if kind == "attrs-to-invisible":
        return _fix_attrs(text)
    if kind == "tree-to-list":
        return _fix_tree(text)
    return (text, False)


def _add_init_import(text: str, module: str) -> tuple[str, bool]:
    if not module:
        return (text, False)
    line = f"from . import {module}\n"
    if line.strip() in [ln.strip() for ln in text.splitlines()]:
        return (text, False)
    lines = text.splitlines(keepends=True)
    pos = 0
    for i, ln in enumerate(lines):
        if ln.startswith(("from .", "from odoo", "import ")):
            pos = i + 1
    lines.insert(pos, line)
    return ("".join(lines), True)


def _add_manifest_list_entry(text: str, key: str, value: str) -> tuple[str, bool]:
    if not value or f"'{value}'" in text or f'"{value}"' in text:
        return (text, False)
    m = re.search(rf"""(['"]{key}['"]\s*:\s*\[)(.*?)(\])""", text, re.DOTALL)
    if not m:
        return (text, False)
    inner = m.group(2).rstrip()
    sep = "" if not inner.strip() else ("" if inner.rstrip().endswith(",") else ",")
    new_inner = f"{inner}{sep}\n        '{value}',\n    "
    return (text[: m.start(2)] + new_inner + text[m.end(2):], True)


def _add_access_row(text: str, model: str) -> tuple[str, bool]:
    """`model` is the dotted name; module guessed from existing rows when possible."""
    if not model:
        return (text, False)
    lines = text.splitlines()
    module = "custom"
    for ln in lines[1:]:
        parts = ln.split(",")
        if len(parts) >= 3 and parts[2].startswith("model_"):
            segs = parts[2].split("_")
            if len(segs) >= 3:
                module = segs[1]
                break
    xmlid = f"model_{module}_{model.replace('.', '_')}"
    if xmlid in text:
        return (text, False)
    if not lines or not lines[0].startswith("id,"):
        header = "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink"
        lines = [header]
    base = f"access_{model.replace('.', '_')}"
    row_u = f"{base}_user,{model} user,{xmlid},base.group_user,1,0,0,0"
    row_m = f"{base}_manager,{model} manager,{xmlid},base.group_system,1,1,1,1"
    lines += [row_u, row_m]
    return ("\n".join(lines) + "\n", True)


def _fix_attrs(text: str) -> tuple[str, bool]:
    """attrs="{'invisible': DOM}" → invisible="DOM" (single-key best effort)."""
    pat = re.compile(r"""\sattrs\s*=\s*"\{'invisible'\s*:\s*(.*?)\}"\s*""")
    changed = False

    def _repl(m: re.Match[str]) -> str:
        nonlocal changed
        changed = True
        return f' invisible="{m.group(1).strip()}" '

    out = pat.sub(_repl, text)
    pat2 = re.compile(r"""\sattrs\s*=\s*'\{'invisible'\s*:\s*(.*?)\}'\s*""")

    def _repl2(m: re.Match[str]) -> str:
        nonlocal changed
        changed = True
        return f" invisible='{m.group(1).strip()}' "

    out = pat2.sub(_repl2, out)
    return (out, changed)


def _fix_tree(text: str) -> tuple[str, bool]:
    out = re.sub(r"<tree([\s>])", r"<list\1", text)
    out = re.sub(r"</tree\s*>", "</list>", out)
    return (out, out != text)
