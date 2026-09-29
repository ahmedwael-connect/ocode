"""Quick-open fuzzy ranking + content search (FR-SMN-030..035, M2).

ripgrep fast path when installed; built-in async-capable Python fallback.
"""

from __future__ import annotations

import fnmatch
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ocode.engines.smn.model import should_ignore


def _fuzzy_score(query: str, text: str) -> int | None:
    q, t = query.lower(), text.lower()
    pos, score, consec = 0, 0, 0
    for ch in q:
        idx = t.find(ch, pos)
        if idx == -1:
            return None
        if idx == pos:
            consec += 1
        score += idx - pos
        pos = idx + 1
    # bonuses: consecutive, basename, short
    base = t.rsplit("/", 1)[-1]
    if q in base:
        score -= 10
    score -= min(consec, 5)
    return score


def parse_quickopen_query(raw: str) -> dict[str, str]:
    """Split `>cmd`, `@sym`, `#xmlid`, `:line`, `ext:` filters (FR-SMN-031/032)."""
    q = raw.strip()
    out = {"kind": "files", "query": q, "ext": ""}
    if q.startswith(">"):
        out.update(kind="commands", query=q[1:].strip())
    elif q.startswith("@"):
        out.update(kind="symbols", query=q[1:].strip())
    elif q.startswith("#"):
        out.update(kind="xmlids", query=q[1:].strip())
    elif q.startswith(":"):
        out.update(kind="line", query=q[1:].strip())
    m = re.search(r"\bext:([\w,]+)", q)
    if m:
        out["ext"] = m.group(1)
        out["query"] = (q[: m.start()] + q[m.end() :]).strip()
    return out


def quick_open(
    candidates: list[str],
    query: str,
    limit: int = 20,
    recent: list[str] | None = None,
    current_module: str | None = None,
) -> list[str]:
    parsed = parse_quickopen_query(query)
    q = parsed["query"].lower()
    exts = [e.strip().lower().lstrip(".") for e in parsed["ext"].split(",") if e.strip()]
    recent_set = set(recent or [])
    if not q:
        # rank: recent first, then current module, then alpha
        def _key(c: str) -> tuple[int, int, str]:
            return (
                0 if c in recent_set else 1,
                0 if (current_module and current_module in c) else 1,
                c.lower(),
            )

        return sorted(candidates, key=_key)[:limit]
    scored: list[tuple[int, str]] = []
    for c in candidates:
        if exts and not any(c.lower().endswith(f".{e}") for e in exts):
            continue
        s = _fuzzy_score(q, c)
        if s is None:
            continue
        if c in recent_set:
            s -= 15
        if current_module and current_module in c:
            s -= 8
        scored.append((s, c))
    scored.sort(key=lambda item: (item[0], item[1].lower()))
    return [c for _, c in scored[:limit]]


def rg_available() -> bool:
    return shutil.which("rg") is not None


@dataclass(frozen=True)
class ContentHit:
    path: Path
    line: int  # 1-based
    col: int  # 1-based
    snippet: str


def _walk_files(
    roots: list[Path],
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    max_files: int = 20000,
) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        base = root if root.is_dir() else root.parent
        stack = [base]
        while stack and len(out) < max_files:
            cur = stack.pop()
            try:
                entries = list(cur.iterdir())
            except OSError:
                continue
            for e in entries:
                try:
                    if should_ignore(e, base):
                        continue
                except OSError:
                    continue
                rel = e.name
                if exclude and any(fnmatch.fnmatch(rel, p) for p in exclude):
                    continue
                if e.is_dir():
                    stack.append(e)
                elif e.is_file():
                    if include and not any(fnmatch.fnmatch(e.name, p) for p in include):
                        continue
                    out.append(e)
    return out


def content_search_sync(
    pattern: str,
    roots: list[Path],
    regex: bool = False,
    case_sensitive: bool = False,
    whole_word: bool = False,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    max_hits: int = 500,
) -> list[ContentHit]:
    """Built-in fallback searcher (used when rg missing; also for tests)."""
    if not pattern:
        return []
    pat = pattern if regex else re.escape(pattern)
    if whole_word:
        pat = rf"\b(?:{pat})\b"
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        rx = re.compile(pat, flags)
    except re.error:
        return []
    hits: list[ContentHit] = []
    for f in _walk_files(roots, include, exclude):
        try:
            if f.stat().st_size > 2_000_000:
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            for m in rx.finditer(line):
                hits.append(ContentHit(f, i, m.start() + 1, line.strip()[:200]))
                if len(hits) >= max_hits:
                    return hits
    return hits


def content_search_rg(
    pattern: str,
    roots: list[Path],
    regex: bool = False,
    case_sensitive: bool = False,
    whole_word: bool = False,
    include: list[str] | None = None,
    max_hits: int = 500,
) -> list[ContentHit] | None:
    """ripgrep fast path. Returns None when rg missing/failed (caller falls back)."""
    if not rg_available() or not pattern:
        return None
    cmd: list[str] = ["rg", "--no-heading", "--line-number", "--column", "--max-count", "50"]
    if not case_sensitive:
        cmd.append("--ignore-case")
    if whole_word:
        cmd.append("--word-regexp")
    if not regex:
        cmd.append("--fixed-strings")
    for g in include or []:
        cmd += ["--glob", g]
    cmd += ["--", pattern, *[str(r) for r in roots]]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode not in (0, 1):
        return None
    hits: list[ContentHit] = []
    for line in proc.stdout.splitlines():
        parts = line.split(":", 3)
        if len(parts) < 4:
            continue
        try:
            hit = ContentHit(Path(parts[0]), int(parts[1]), int(parts[2]), parts[3].strip()[:200])
            hits.append(hit)
        except ValueError:
            continue
        if len(hits) >= max_hits:
            break
    return hits


def content_search(
    pattern: str,
    roots: list[Path],
    regex: bool = False,
    case_sensitive: bool = False,
    whole_word: bool = False,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    max_hits: int = 500,
) -> list[ContentHit]:
    hits = content_search_rg(pattern, roots, regex, case_sensitive, whole_word, include, max_hits)
    if hits is not None:
        return hits
    return content_search_sync(
        pattern, roots, regex, case_sensitive, whole_word, include, exclude, max_hits
    )
