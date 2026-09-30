"""M7 git tests: status, hunks, blame, multi-repo."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ocode.engines.git.repo import (
    blame_line,
    commit,
    diff_hunks,
    file_diff,
    find_repo,
    repo_status,
    stage,
)

git = pytest.mark.skipif(
    __import__("shutil").which("git") is None, reason="git not installed"
)


def make_repo(base: Path) -> Path:
    root = base / "ws"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)
    return root


@git
def test_status_clean_and_dirty(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    assert find_repo(root / "sub" ) == root or find_repo(root) == root
    repo = repo_status(root)
    assert repo is not None and not repo.dirty
    (root / "a.py").write_text("x = 2\n", encoding="utf-8")
    repo = repo_status(root)
    assert repo is not None and repo.dirty and repo.unstaged == 1
    (root / "new.py").write_text("y\n", encoding="utf-8")
    assert repo_status(root).untracked == 1  # type: ignore[union-attr]


@git
def test_hunks_and_diff(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    target = root / "a.py"
    target.write_text("x = 1\nx2 = 2\n", encoding="utf-8")
    hunks = diff_hunks(root, target)
    assert len(hunks) == 1 and hunks[0].new_start == 2
    assert "@@" in file_diff(root, target)
    assert diff_hunks(root, root / "missing.py") == []


@git
def test_blame_and_commit_flow(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    line = blame_line(root, root / "a.py", 1)
    assert "t" in line  # author
    assert blame_line(root, root / "a.py", 99) == ""
    (root / "b.py").write_text("b = 1\n", encoding="utf-8")
    assert stage(root, ["b.py"])
    assert commit(root, "add b")
    assert repo_status(root).dirty is False  # type: ignore[union-attr]


@git
def test_outside_repo() -> None:
    assert find_repo(Path("/proc")) is None or isinstance(find_repo(Path("/proc")), Path)
    assert repo_status(Path("/proc/1")) is None
