"""GIT engine: status, diff gutter data, blame, multi-repo (PRD §4.10, M7)."""

from ocode.engines.git.repo import (
    GitRepo,
    Hunk,
    blame_line,
    commit,
    diff_hunks,
    find_repo,
    porcelain,
    repo_status,
    stage,
    stage_all_tracked,
)

__all__ = [
    "GitRepo",
    "Hunk",
    "blame_line",
    "commit",
    "diff_hunks",
    "find_repo",
    "porcelain",
    "repo_status",
    "stage",
    "stage_all_tracked",
]
