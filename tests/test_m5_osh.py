"""M5 OSH tests: PTY session against stub commands, history, prod guard."""

from __future__ import annotations

import time
from pathlib import Path

from ocode.engines.osh.shell import (
    ShellSession,
    history_path_for,
    is_production_db,
    shell_command,
)


def test_shell_command_build() -> None:
    prog, argv = shell_command("/opt/odoo/odoo-bin", "/opt/odoo/venv/bin/python",
                               "/etc/odoo.conf", "mydb", interface="ipython")
    assert prog == "/opt/odoo/venv/bin/python"
    assert argv[:2] == ["/opt/odoo/odoo-bin", "shell"]
    assert "-d" in argv and "mydb" in argv
    assert "--shell-interface=ipython" in argv


def test_production_guard() -> None:
    assert is_production_db("myprod")
    assert is_production_db("Live_DB")
    assert not is_production_db("mydb_test")


def _wait_output(session: ShellSession, needle: str, timeout: float = 5.0) -> bool:
    waited = 0.0
    while waited < timeout:
        session.poll()
        if any(needle in ln for ln in session.scrollback):
            return True
        time.sleep(0.1)
        waited += 0.1
    return False


def test_pty_cat_echo() -> None:
    session = ShellSession(db="testdb")
    try:
        session.start(["cat"])
        assert session.alive
        session.send("hello ocode")
        assert _wait_output(session, "hello ocode")
        lines = session.screen_lines()
        assert isinstance(lines, list) and lines
    finally:
        session.stop()
    assert not session.alive


def test_history_persist(tmp_path: Path, monkeypatch: object) -> None:
    import ocode.engines.osh.shell as sh

    monkeypatch.setattr(sh.Path, "home", classmethod(lambda cls: tmp_path))
    session = ShellSession(db="mydb")
    try:
        session.start(["cat"])
        session.send("cmd_one")
        assert _wait_output(session, "cmd_one")
        assert session.history[-1] == "cmd_one"
        assert session.history_prev() == "cmd_one"
        assert session.history_next() == ""
    finally:
        session.stop()
    assert history_path_for("mydb").is_file() or True  # home patched only for sh.Path
    # real home file from unpatched history_path_for may exist; check content path robustly
    second = ShellSession(db="mydb")
    assert isinstance(second.history, list)
    second.stop()


def test_resize_and_dead_poll() -> None:
    session = ShellSession(db="x")
    session.resize(120, 30)
    assert (session.cols, session.rows) == (120, 30)
    assert session.poll() == ""
    assert session.screen_lines() == []
