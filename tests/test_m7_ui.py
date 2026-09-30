"""M7 UI tests: branch statusbar, gutter hunks, blame, commit screen."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ocode.app import OcodeApp
from ocode.ui.widgets.editor import OcodeEditor


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


def patch_state(tmp_path: Path, monkeypatch: object) -> None:
    import ocode.engines.ses as ses

    monkeypatch.setattr(ses, "state_dir", lambda: tmp_path / "state")


async def test_branch_and_gutter(tmp_path: Path, monkeypatch: object) -> None:
    root = make_repo(tmp_path)
    patch_state(tmp_path, monkeypatch)
    target = root / "a.py"
    app = OcodeApp(start_path=target)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._poll_git()
        await pilot.pause()
        assert app._git_status is not None
        assert app._git_status.branch != ""
        assert app._git_segment() != ""
        target.write_text("x = 1\nx2 = 2\n", encoding="utf-8")
        app._poll_git()
        await pilot.pause()
        assert len(app._git_hunks) == 1
        editor = app.query_one("#editor", OcodeEditor)
        assert len(editor.hunks) == 1
        assert editor._gutter_mark(2) != (" ", "")


async def test_blame_toggle(tmp_path: Path, monkeypatch: object) -> None:
    root = make_repo(tmp_path)
    patch_state(tmp_path, monkeypatch)
    app = OcodeApp(start_path=root / "a.py")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._blame_on is False
        app.action_git_blame()
        assert app._blame_on is True
        app._poll_git()
        await pilot.pause()
        # breadcrumb carries the blame suffix (or empty when unavailable)
        assert isinstance(app.breadcrumb(), str)
        app.action_git_blame()
        assert app._blame_on is False


async def test_commit_screen_flow(tmp_path: Path, monkeypatch: object) -> None:
    root = make_repo(tmp_path)
    patch_state(tmp_path, monkeypatch)
    (root / "a.py").write_text("x = 2\n", encoding="utf-8")
    app = OcodeApp(start_path=root / "a.py")
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_git_commit()
        await pilot.pause()
        await pilot.press(*list("second"))
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        log = subprocess.run(["git", "log", "--oneline"], cwd=root,
                             capture_output=True, text=True, check=True)
        assert "second" in log.stdout
        app._poll_git()
        assert app._git_status is not None and not app._git_status.dirty
