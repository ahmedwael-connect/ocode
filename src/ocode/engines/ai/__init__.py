"""AI assist: offline-first provider + extension point (M7).

No network calls by default (NFR). The built-in ``offline`` provider drafts
from the local index + AST. Remote providers plug in via the
``ocode.ai_providers`` entry-point group::

    [project.entry-points."ocode.ai_providers"]
    myremote = "mypkg:RemoteProvider"  # subclass of Provider
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any

from ocode.engines.oki.query import OkiQuery

GROUP = "ocode.ai_providers"


class Provider:
    """Generate text for a prompt. Must never require network unless configured."""

    name = "base"

    def generate(self, prompt: str, context: dict[str, Any]) -> str:
        raise NotImplementedError


def get_provider(name: str = "offline") -> Provider:
    if name == "offline":
        return OfflineProvider()
    try:
        eps: Any = entry_points()
        if hasattr(eps, "select"):
            candidates = list(eps.select(group=GROUP))
        elif hasattr(eps, "get"):
            candidates = list(eps.get(GROUP, []))
        else:
            candidates = list(eps)
    except (OSError, AttributeError, TypeError) as exc:
        raise KeyError(f"unknown AI provider '{name}': {exc}") from exc
    for ep in candidates:
        if ep.name == name:
            target = ep.load()
            provider = target() if isinstance(target, type) else target
            if isinstance(provider, Provider):
                return provider
            raise KeyError(f"AI provider '{name}' is not a Provider")
    raise KeyError(f"unknown AI provider '{name}'")


@dataclass
class ExplainResult:
    title: str
    body: str


class OfflineProvider(Provider):
    name = "offline"

    def generate(self, prompt: str, context: dict[str, Any]) -> str:
        query = context.get("query")
        symbol = str(context.get("symbol", ""))
        if prompt == "explain" and isinstance(query, OkiQuery):
            return explain_symbol(symbol, query).body
        if prompt == "docstring":
            text = str(context.get("text", ""))
            line = int(context.get("line", 1))
            insert, doc = draft_docstring(text, line)
            _ = insert
            return doc
        return ""

    def explain(self, symbol: str, query: OkiQuery) -> ExplainResult:
        return explain_symbol(symbol, query)


def explain_symbol(symbol: str, query: OkiQuery) -> ExplainResult:
    base = symbol.split(".")[-1]
    if symbol in query.models():
        fields = query.merged_fields(symbol)
        methods = query.methods_of(symbol)
        mods = query.model_modules(symbol)
        views = query.views_for_model(symbol)
        lines = [
            f"Model {symbol} (in {', '.join(mods[:4])})",
            f"{len(fields)} fields, {len(methods)} methods, {len(views)} views.",
            "Key fields:",
        ]
        for name, finfo in sorted(fields.items())[:12]:
            lines.append(f"  {name}: {finfo.get('type', '')}"
                         f"{' → ' + str(finfo.get('comodel')) if finfo.get('comodel') else ''}"
                         f"  {finfo.get('string', '')}")
        orm = [m for m in methods if m in ("search", "create", "write", "unlink")]
        if orm:
            lines.append("Note: overrides ORM methods: " + ", ".join(sorted(set(orm))))
        return ExplainResult(symbol, "\n".join(lines))
    for model in query.models():
        fields = query.merged_fields(model)
        if base in fields:
            finfo = fields[base]
            body = (f"{model}.{base}\n"
                    f"Type: {finfo.get('type', '')}\n"
                    f"Comodel: {finfo.get('comodel', '') or '—'}\n"
                    f"Required: {finfo.get('required', False)}\n"
                    f"Defined in: {finfo.get('module', '')} ({finfo.get('file', '')})")
            return ExplainResult(base, body)
    if "." in symbol and query.xmlid_exists(symbol):
        return ExplainResult(symbol, f"XML ID {symbol} — record defined in the index.")
    return ExplainResult(symbol or "?", "No local information found.")


def draft_docstring(text: str, lineno_1b: int) -> tuple[int, str]:
    """Draft a Google-style docstring for the def enclosing `lineno_1b`.

    Returns (insert_line_1b, docstring). insert_line_1b is where the opening
    quotes go (first body line of the function).
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return (lineno_1b, '"""TODO."""\n')
    lines = text.splitlines()
    target: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", None) or (start + 1000)
            if start <= lineno_1b <= end:
                if target is None or start >= target.lineno:
                    target = node
    if target is None:
        return (lineno_1b, '"""TODO."""\n')
    args = [a.arg for a in target.args.args if a.arg not in ("self", "cls")]
    if target.args.vararg:
        args.append("*" + target.args.vararg.arg)
    if target.args.kwarg:
        args.append("**" + target.args.kwarg.arg)
    # indent from the def line + one level
    indent = ""
    if 1 <= target.lineno <= len(lines):
        stripped = lines[target.lineno - 1].lstrip()
        indent = lines[target.lineno - 1][: len(lines[target.lineno - 1]) - len(stripped)]
    body_indent = indent + "    "
    parts = [f"{body_indent}\"\"\"TODO: describe {target.name}.", ""]
    if args:
        parts.append(f"{body_indent}Args:")
        parts += [f"{body_indent}    {a}: ..." for a in args]
        parts.append("")
    returns = not (
        len(target.body) == 1 and isinstance(target.body[0], ast.Expr)
        and isinstance(target.body[0].value, ast.Constant)
        and target.body[0].value.value is Ellipsis
    )
    has_return = any(
        isinstance(n, ast.Return) and n.value is not None for n in ast.walk(target)
    )
    if returns and not has_return:
        returns = False
    if returns:
        parts += [f"{body_indent}Returns:", f"{body_indent}    ...", ""]
    parts.append(f'{body_indent}"""')
    insert_at = target.lineno + 1
    # skip over an existing docstring
    if target.body and isinstance(target.body[0], ast.Expr) and isinstance(
        target.body[0].value, ast.Constant
    ) and isinstance(target.body[0].value.value, str):
        end = getattr(target.body[0], "end_lineno", None) or target.lineno + 1
        insert_at = end + 1
        return (insert_at, "")
    return (insert_at, "\n".join(parts) + "\n")
