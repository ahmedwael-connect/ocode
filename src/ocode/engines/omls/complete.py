"""Context-aware completion over the OKI index (FR-OMLS-010..018)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ocode.engines.oki.query import OkiQuery
from ocode.engines.omls.snippets import SNIPPETS

ORM_METHODS = [
    "search", "browse", "create", "write", "unlink", "read", "search_read",
    "search_count", "mapped", "filtered", "sorted", "exists", "ensure_one",
    "copy", "name_get", "name_search", "fields_get", "default_get",
]
FIELD_TYPES = [
    "Char", "Text", "Html", "Integer", "Float", "Monetary", "Boolean",
    "Date", "Datetime", "Binary", "Image", "Selection",
    "Many2one", "One2many", "Many2many", "Reference",
]
API_DECORATORS = [
    "api.depends", "api.depends_context", "api.model", "api.model_create_multi",
    "api.onchange", "api.constrains", "api.returns", "api.autovacuum",
]
VIEW_TAGS = [
    "form", "list", "tree", "kanban", "search", "graph", "pivot",
    "calendar", "activity", "field", "xpath", "record", "template",
    "menuitem", "group", "page", "notebook", "header", "sheet", "button",
]
FIELD_ATTRS = [
    "name", "string", "ref", "domain", "context", "groups", "attrs",
    "invisible", "readonly", "required", "widget", "options", "on_change",
    "placeholder", "help", "colspan", "nolabel",
]
MANIFEST_KEYS = [
    "name", "version", "depends", "data", "demo", "category", "summary",
    "description", "author", "website", "license", "installable",
    "application", "auto_install", "assets", "external_dependencies",
]


@dataclass
class Completion:
    label: str
    kind: str  # model|field|method|xmlid|module|snippet|keyword|path
    detail: str = ""
    doc: str = ""
    insert: str = ""
    priority: int = 1

    def __post_init__(self) -> None:
        if not self.insert:
            self.insert = self.label


def _line_prefix(text: str, offset: int) -> tuple[str, int, int]:
    """Return (current line text before offset, line_no 0-based, col)."""
    before = text[:offset]
    lineno = before.count("\n")
    col = offset - (before.rfind("\n") + 1)
    line = before.split("\n")[-1]
    return (line, lineno, col)


def _current_class_model(text: str, offset: int) -> str:
    """Best-effort _name of the enclosing class (regex scan backwards)."""
    before = text[:offset]
    names = re.findall(r"_name\s*=\s*['\"]([\w.]+)['\"]", before)
    return names[-1] if names else ""


def complete_at(
    path: Path | str | None,
    text: str,
    offset: int,
    query: OkiQuery | None,
    current_module: str | None = None,
    version: str | None = None,
) -> list[Completion]:
    lang = _lang_of(path, text)
    if lang == "python":
        return _complete_python(text, offset, query, current_module)
    if lang in ("xml", "html"):
        return _complete_xml(text, offset, query, current_module)
    if lang == "csv":
        return _complete_csv(text, offset, query)
    if str(path or "").endswith("__manifest__.py"):
        return _complete_manifest(text, offset, query)
    _ = version
    return []


def _lang_of(path: Path | str | None, text: str) -> str:
    if path:
        ext = Path(str(path)).suffix.lower()
        return {"py": "python", ".py": "python"}.get(ext, ext.lstrip(".") or "text")
    return "xml" if text.lstrip().startswith("<") else "text"


def _boost(module: str | None, current: str | None, closure: set[str]) -> int:
    if not module:
        return 1
    if current and module == current:
        return 0
    if module in closure:
        return 0
    return 2


def _model_items(
    query: OkiQuery, prefix: str, current: str | None, closure: set[str]
) -> list[Completion]:
    out: list[Completion] = []
    for model in query.models():
        if not model.startswith(prefix):
            continue
        mods = query.model_modules(model)
        first = mods[0] if mods else None
        out.append(Completion(model, "model", ", ".join(mods[:3]),
                              priority=_boost(first, current, closure)))
    return out


def _complete_python(
    text: str, offset: int, query: OkiQuery | None, current_module: str | None
) -> list[Completion]:
    line, _, _ = _line_prefix(text, offset)
    out: list[Completion] = []
    closure = query.depends_closure(current_module) if query and current_module else set()

    m = re.search(r"""self\.env\[['"]([\w.]*)$""", line)
    if m and query:
        return _rank(_model_items(query, m.group(1), current_module, closure))

    m = re.search(r"""fields\.(\w*)$""", line)
    if m:
        prefix = m.group(1)
        return _rank([Completion(t, "keyword", "fields type")
                      for t in FIELD_TYPES if t.startswith(prefix)])

    m = re.search(r"""api\.(\w*)$""", line)
    if m:
        prefix = m.group(1)
        return _rank([Completion(d.split(".", 1)[1], "keyword", d)
                      for d in API_DECORATORS if d.split(".", 1)[1].startswith(prefix)])

    m = re.search(r"""(?:_inherit|_inherits|comodel_name)\s*[=:]\s*['"]([\w.]*)$""", line)
    if m and query:
        return _rank(_model_items(query, m.group(1), current_module, closure))

    m = re.search(r"""Many2one|One2many|Many2many|Reference\(\s*['"]([\w.]*)$""", line)
    if m and query:
        return _rank(_model_items(query, m.group(1), current_module, closure))

    m = re.search(r"""self\.(\w*)$""", line)
    if m and query:
        prefix, model = m.group(1), _current_class_model(text, offset)
        if model:
            for fname, finfo in query.merged_fields(model).items():
                if fname.startswith(prefix):
                    mod = str(finfo.get("module") or None)
                    ftype = str(finfo.get("type", ""))
                    out.append(Completion(fname, "field", ftype,
                                          priority=_boost(mod, current_module, closure)))
            for mname in query.methods_of(model):
                if mname.startswith(prefix):
                    out.append(Completion(mname, "method", "method", priority=1))
        for orm in ORM_METHODS:
            if orm.startswith(prefix):
                out.append(Completion(orm, "method", "orm", priority=3))
        return _rank(out)

    # snippets by trigger prefix (last word)
    word = re.search(r"(\w+)$", line)
    if word:
        for trigger, spec in SNIPPETS.items():
            if spec.get("languages") == "python" and trigger.startswith(word.group(1)):
                out.append(Completion(trigger, "snippet", str(spec.get("label", "")),
                                      insert=trigger, priority=2))
    return _rank(out)


def _complete_xml(
    text: str, offset: int, query: OkiQuery | None, current_module: str | None
) -> list[Completion]:
    line, _, _ = _line_prefix(text, offset)
    out: list[Completion] = []
    closure = query.depends_closure(current_module) if query and current_module else set()

    m = re.search(r"""<(/?)(\w*)$""", line)
    if m and not re.search(r"""\s\w*=\s*["']?[\w.,]*$""", line):
        prefix = m.group(2)
        tags = [Completion(t, "keyword", "tag") for t in VIEW_TAGS if t.startswith(prefix)]
        return _rank(tags)

    m = re.search(r"""<field\s+name\s*=\s*["']([\w]*)$""", line)
    if m and query:
        model = _xml_model(text, offset)
        prefix = m.group(1)
        if model:
            for fname, finfo in query.merged_fields(model).items():
                if fname.startswith(prefix):
                    mod = str(finfo.get("module") or None)
                    ftype = str(finfo.get("type", ""))
                    out.append(Completion(fname, "field", ftype,
                                          priority=_boost(mod, current_module, closure)))
            return _rank(out)

    m = re.search(r"""(?:ref|inherit_id|action|t-call)=["']([\w.]*)$""", line)
    if m and query:
        prefix = m.group(1)
        rows = query.db.query("SELECT xmlid, module, kind FROM xmlids")
        for r in rows:
            xmlid, mod, kind = str(r["xmlid"]), str(r["module"]), str(r["kind"])
            for cand in (f"{mod}.{xmlid}", xmlid):
                if cand.startswith(prefix):
                    out.append(Completion(cand, "xmlid", f"{kind} · {mod}",
                                          priority=_boost(mod, current_module, closure)))
                    break
        return _rank(out[:60])

    m = re.search(r"""<(\w+)\s+(\w*)$""", line)
    if m:
        prefix = m.group(2)
        attrs = [Completion(a, "keyword", "attr")
                 for a in FIELD_ATTRS if a.startswith(prefix)]
        return _rank(attrs)

    word = re.search(r"(\w+)$", line)
    if word:
        for trigger, spec in SNIPPETS.items():
            if spec.get("languages") == "xml" and trigger.startswith(word.group(1)):
                out.append(Completion(trigger, "snippet", str(spec.get("label", "")),
                                      insert=trigger, priority=2))
    return _rank(out)


def _xml_model(text: str, offset: int) -> str:
    before = text[:offset]
    pat = r"""<field\s+name\s*=\s*["']model["']\s*>([\w.]+)<"""
    models = re.findall(pat, before)
    return models[-1] if models else ""


def _complete_csv(text: str, offset: int, query: OkiQuery | None) -> list[Completion]:
    before = text[:offset]
    lineno = before.count("\n")
    if lineno == 0:
        from ocode.engines.oki.csvparse import ACCESS_HEADER

        frag = before.split(",")[-1].strip()
        heads = [Completion(h, "keyword", "header")
                 for h in ACCESS_HEADER if h.startswith(frag)]
        return _rank(heads)
    if query:
        frag_m = re.search(r"([\w.]*)$", before.split("\n")[-1])
        frag = frag_m.group(1) if frag_m else ""
        out: list[Completion] = []
        for model in query.models():
            for mod in query.model_modules(model):
                cand = f"model_{mod}_{model.replace('.', '_')}"
                if cand.startswith(frag):
                    out.append(Completion(cand, "xmlid", model, priority=1))
        return _rank(out[:40])
    return []


def _complete_manifest(
    text: str, offset: int, query: OkiQuery | None
) -> list[Completion]:
    line, _, _ = _line_prefix(text, offset)
    m = re.search(r"""['"](\w*)$""", line)
    frag = m.group(1) if m else ""
    out = [Completion(k, "keyword", "manifest key")
           for k in MANIFEST_KEYS if k.startswith(frag)]
    if "depends" in text[:offset][-500:] and query:
        out += [Completion(mo, "module", "depends")
                for mo in query.module_names() if mo.startswith(frag)]
    return _rank(out)


def _rank(items: list[Completion]) -> list[Completion]:
    items.sort(key=lambda c: (c.priority, c.label.lower()))
    seen: set[str] = set()
    out: list[Completion] = []
    for c in items:
        if c.label not in seen:
            seen.add(c.label)
            out.append(c)
        if len(out) >= 60:
            break
    return out
