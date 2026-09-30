"""Python static parser: Odoo models, fields, methods, imports (ast only)."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field


@dataclass
class FieldInfo:
    name: str
    ftype: str  # Char, Many2one, ...
    comodel: str = ""
    string: str = ""
    required: bool = False
    lineno: int = 0


@dataclass
class MethodInfo:
    name: str
    decorators: list[str] = field(default_factory=list)
    lineno: int = 0


@dataclass
class ClassInfo:
    name: str
    bases: list[str] = field(default_factory=list)
    odoo_base: str = ""  # Model | TransientModel | AbstractModel (or "")
    model_name: str = ""  # _name
    inherit: list[str] = field(default_factory=list)  # _inherit str|list
    inherits: dict[str, str] = field(default_factory=dict)  # _inherits
    fields: list[FieldInfo] = field(default_factory=list)
    methods: list[MethodInfo] = field(default_factory=list)
    lineno: int = 0


@dataclass
class ModulePyInfo:
    classes: list[ClassInfo] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)  # from . import x names


ODOO_BASES = ("Model", "TransientModel", "AbstractModel")
FIELD_TYPES = {
    "Char", "Text", "Html", "Integer", "Float", "Monetary", "Boolean", "Date", "Datetime",
    "Binary", "Image", "Selection", "Many2one", "One2many", "Many2many", "Reference",
    "Many2oneReference", "Id", "Json",
}
RELATIONAL = ("Many2one", "One2many", "Many2many", "Reference")


def _const_str(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def _const_str_list(node: ast.AST) -> list[str]:
    if isinstance(node, (ast.List, ast.Tuple)):
        return [
            e.value for e in node.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
    s = _const_str(node)
    return [s] if s else []


def _decorator_name(d: ast.AST) -> str:
    if isinstance(d, ast.Name):
        return d.id
    if isinstance(d, ast.Attribute):
        if isinstance(d.value, (ast.Name, ast.Attribute)):
            return f"{_decorator_name(d.value)}.{d.attr}"
        return d.attr
    if isinstance(d, ast.Call):
        return _decorator_name(d.func)
    return ""


def _call_kwargs(call: ast.Call) -> dict[str, ast.AST]:
    out: dict[str, ast.AST] = {}
    for kw in call.keywords:
        if kw.arg:
            out[kw.arg] = kw.value
    return out


def _field_from_assign(target: str, call: ast.Call, ftype: str, lineno: int) -> FieldInfo:
    kw = _call_kwargs(call)
    comodel = ""
    if ftype in RELATIONAL:
        first = call.args[0] if call.args else None
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            comodel = str(first.value)
        for key in ("comodel_name", "relation"):
            if key in kw:
                comodel = _const_str(kw[key]) or comodel
    string = _const_str(kw.get("string", ast.Constant(value="")))
    req_node = kw.get("required")
    required = isinstance(req_node, ast.Constant) and req_node.value is True
    return FieldInfo(
        name=target, ftype=ftype, comodel=comodel, string=string,
        required=bool(required), lineno=lineno,
    )


def _class_info(node: ast.ClassDef) -> ClassInfo:
    bases: list[str] = []
    for b in node.bases:
        if isinstance(b, ast.Name):
            bases.append(b.id)
        elif isinstance(b, ast.Attribute):
            bases.append(b.attr)
    odoo_base = next((b for b in bases if b in ODOO_BASES), "")
    info = ClassInfo(name=node.name, bases=bases, odoo_base=odoo_base, lineno=node.lineno)
    for stmt in node.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
        ):
            tname = stmt.targets[0].id
            if tname == "_name":
                info.model_name = _const_str(stmt.value)
            elif tname == "_inherit":
                if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                    info.inherit = [stmt.value.value]
                else:
                    info.inherit = _const_str_list(stmt.value)
            elif tname == "_inherits":
                if isinstance(stmt.value, ast.Dict):
                    pairs = zip(stmt.value.keys, stmt.value.values, strict=False)
                    for k, v in pairs:
                        if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                            info.inherits[str(k.value)] = str(v.value)
            elif isinstance(stmt.value, ast.Call):
                func = stmt.value.func
                fname = ""
                if isinstance(func, ast.Attribute):
                    fname = func.attr
                if fname in FIELD_TYPES:
                    info.fields.append(_field_from_assign(tname, stmt.value, fname, stmt.lineno))
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info.methods.append(
                MethodInfo(
                    name=stmt.name,
                    decorators=[d for d in (_decorator_name(d) for d in stmt.decorator_list) if d],
                    lineno=stmt.lineno,
                )
            )
    return info


def parse_python(source: str) -> ModulePyInfo:
    """Parse a Python source file. Never raises on bad input."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return ModulePyInfo()
    info = ModulePyInfo()
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            info.classes.append(_class_info(node))
        elif isinstance(node, ast.ImportFrom) and node.module in (None, "", "."):
            for a in node.names:
                if a.name != "*":
                    info.imports.append(a.asname or a.name)
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("."):
            for a in node.names:
                if a.name != "*":
                    info.imports.append(a.asname or a.name)
    return info
