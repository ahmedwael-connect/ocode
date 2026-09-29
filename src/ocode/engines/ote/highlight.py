"""Highlighting interface (FR-OMLS-001 subset for M1).

Tree-sitter when installed; otherwise regex fallback for
Python/XML/JS/JSON/YAML. Returns per-line token spans:
(offset_in_line, length, scope). Never raises on bad input.
"""

from __future__ import annotations

import re
from pathlib import Path

EXT_LANG: dict[str, str] = {
    ".py": "python",
    ".xml": "xml",
    ".html": "html",
    ".js": "javascript",
    ".ts": "javascript",
    ".css": "css",
    ".scss": "scss",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".csv": "csv",
    ".po": "po",
    ".pot": "po",
}


def detect_language(path: Path | str | None, text: str = "") -> str:
    if path:
        ext = Path(str(path)).suffix.lower()
        if ext in EXT_LANG:
            return EXT_LANG[ext]
    if text.lstrip().startswith("<"):
        return "xml"
    return "text"


_PY_KW = (
    "False|None|True|and|as|assert|async|await|break|class|continue|def|del|elif|else|"
    "except|finally|for|from|global|if|import|in|is|lambda|nonlocal|not|or|pass|raise|"
    "return|try|while|with|yield"
)
_PY_RE = re.compile(
    rf"(?P<comment>#[^\n]*)|(?P<string>(\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''|\"[^\n\"]*\"|'[^\n']*'))"
    rf"|(?P<keyword>\b(?:{_PY_KW})\b)|(?P<number>\b\d[\d_]*(?:\.\d+)?\b)"
    r"|(?P<decorator>@[A-Za-z_][\w.]*)|(?P<builtin>\b(?:self|cls|super)\b)"
)
_XML_RE = re.compile(
    r"(?P<comment><!--[\s\S]*?-->)|(?P<tag></?[A-Za-z_][\w:.-]*|/?>)"
    r"|(?P<attr>[A-Za-z_][\w:.-]*(?=\s*=))|(?P<string>\"[^\"]*\"|'[^']*')"
    r"|(?P<entity>&\w+;)"
)
_GENERIC_STR = re.compile(r"\"[^\n\"]*\"|'[^']*'|`[^`]*`")


def _spans(rx: re.Pattern[str], line: str) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    try:
        for m in rx.finditer(line):
            scope = m.lastgroup or "text"
            out.append((m.start(), m.end() - m.start(), scope))
    except re.error:
        pass
    return out


def _try_treesitter(lang: str, lines: list[str]) -> list[list[tuple[int, int, str]]] | None:
    try:
        import tree_sitter  # type: ignore[import-not-found]
    except ImportError:
        return None
    _ = (tree_sitter, lang)
    return None  # grammar wiring lands post-M1; fallback used until then


def highlight_lines(
    lang: str, lines: list[str], limit_lines: int = 2000
) -> list[list[tuple[int, int, str]]]:
    """Highlight up to `limit_lines` (perf guard, FR-OMLS-004). Rest get []."""
    ts = _try_treesitter(lang, lines[:limit_lines])
    if ts is not None:
        return ts
    out: list[list[tuple[int, int, str]]] = []
    for i, line in enumerate(lines):
        if i >= limit_lines:
            out.append([])
            continue
        if lang == "python":
            out.append(_spans(_PY_RE, line))
        elif lang in ("xml", "html"):
            out.append(_spans(_XML_RE, line))
        elif lang in ("javascript", "json", "yaml", "css", "scss"):
            out.append(_spans(_GENERIC_STR, line))
        else:
            out.append([])
    return out
