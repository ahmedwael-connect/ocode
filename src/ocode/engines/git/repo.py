"""Git subprocess wrapper: repo discovery, status, hunks, blame (FR-GIT-001..005)."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


def _run_git(cwd: Path, args: list[str], timeout: int = 15) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError):
        return (128, "")
    return (proc.returncode, proc.stdout)


@dataclass
class GitRepo:
    root: Path
    branch: str = ""
    dirty: bool = False
    ahead: int = 0
    behind: int = 0
    staged: int = 0
    unstaged: int = 0
    untracked: int = 0


@dataclass
class Hunk:
    new_start: int  # 1-based
    new_count: int
    kind: str  # add | mod | del


def find_repo(path: Path) -> Path | None:
    """Nearest enclosing repo root (multi-repo aware: each addons dir may differ)."""
    cur = path if path.is_dir() else path.parent
    for cand in [cur, *cur.parents]:
        try:
            if (cand / ".git").exists():
                return cand
        except OSError:
            continue
        if cand == cand.parent:
            break
    return None


def repo_status(root: Path) -> GitRepo | None:
    code, out = _run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    if code != 0:
        return None
    branch = out.strip() or "HEAD"
    code, out = _run_git(root, ["status", "--porcelain=v1", "--branch"])
    repo = GitRepo(root=root, branch=branch)
    if code != 0:
        return repo
    for line in out.splitlines():
        if line.startswith("##"):
            m = re.search(r"ahead (\d+)", line)
            if m:
                repo.ahead = int(m.group(1))
            m = re.search(r"behind (\d+)", line)
            if m:
                repo.behind = int(m.group(1))
            continue
        if len(line) < 2:
            continue
        x, y = line[0], line[1]
        if x == "?" and y == "?":
            repo.untracked += 1
        else:
            if x != " ":
                repo.staged += 1
            if y != " ":
                repo.unstaged += 1
    repo.dirty = bool(repo.staged or repo.unstaged or repo.untracked)
    return repo


def diff_hunks(repo: Path, file: Path) -> list[Hunk]:
    """Unstaged + staged hunks for a file (gutter markers). Empty when clean/absent."""
    try:
        rel = str(file.relative_to(repo))
    except ValueError:
        return []
    hunks: list[Hunk] = []
    for extra in ([], ["--cached"]):
        _code, out = _run_git(repo, ["diff", "--unified=0", *extra, "--", rel])
        for line in out.splitlines():
            m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            if not m:
                continue
            start, count = int(m.group(1)), int(m.group(2) or "1")
            if count == 0:
                hunks.append(Hunk(max(1, start), 1, "del"))
            elif start == 0:
                hunks.append(Hunk(1, count, "add"))
            else:
                # staged vs unstaged merge: kind add if pure addition hunk
                hunks.append(Hunk(start, count, "mod"))
    # dedupe overlapping
    seen: set[tuple[int, int, str]] = set()
    unique: list[Hunk] = []
    for h in hunks:
        key = (h.new_start, h.new_count, h.kind)
        if key not in seen:
            seen.add(key)
            unique.append(h)
    return sorted(unique, key=lambda h: h.new_start)


def blame_line(repo: Path, file: Path, lineno_1b: int) -> str:
    """'abc1234 Author 2026-01-01 summary' for one line (FR-GIT-004)."""
    try:
        rel = str(file.relative_to(repo))
    except ValueError:
        return ""
    code, out = _run_git(
        repo, ["blame", "-L", f"{lineno_1b},{lineno_1b}", "--porcelain", "--", rel]
    )
    if code != 0 or not out:
        return ""
    sha, author, date, summary = "", "", "", ""
    for line in out.splitlines():
        if line.startswith("author "):
            author = line[7:]
        elif line.startswith("author-time "):
            try:
                import datetime as _dt

                date = _dt.datetime.fromtimestamp(int(line[12:])).strftime("%Y-%m-%d")
            except ValueError:
                pass
        elif line.startswith("summary "):
            summary = line[8:]
        elif re.match(r"^[0-9a-f]{40} ", line):
            sha = line[:8]
    if not sha:
        return ""
    return f"{sha} {author} {date} {summary}".strip()


def stage(repo: Path, files: list[str]) -> bool:
    code, _ = _run_git(repo, ["add", "--", *files])
    return code == 0


def commit(repo: Path, message: str) -> bool:
    code, _ = _run_git(repo, ["commit", "-m", message])
    return code == 0


def porcelain(root: Path, limit: int = 50) -> list[str]:
    _code, out = _run_git(root, ["status", "--porcelain=v1"])
    lines = [ln for ln in out.splitlines() if ln.strip()]
    if len(lines) > limit:
        lines = lines[:limit] + [f"… +{len(lines) - limit} more"]
    return lines


def stage_all_tracked(root: Path) -> bool:
    code, _ = _run_git(root, ["add", "-u"])
    return code == 0


def file_diff(repo: Path, file: Path, staged: bool = False) -> str:
    try:
        rel = str(file.relative_to(repo))
    except ValueError:
        return ""
    args = ["diff", "--", rel] if not staged else ["diff", "--cached", "--", rel]
    _code, out = _run_git(repo, args)
    return out
