"""M7 DB UI tests: manager select/backup/drop flows against stub binaries."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from ocode.app import OcodeApp


def make_stubs(base: Path) -> Path:
    bindir = base / "bin"
    bindir.mkdir()
    log = base / "calls.log"
    psql = bindir / "psql"
    psql.write_text(
        "#!/bin/bash\n"
        f'echo "$@" >> "{log}"\n'
        'case "$*" in\n'
        "  *pg_size_pretty*) echo '9 MB' ;;\n"
        "  *pg_database*) printf 'mydb\\ntestdb\\n' ;;\n"
        "  *) echo '' ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    psql.chmod(0o755)
    dump = bindir / "pg_dump"
    dump.write_text('#!/bin/bash\necho "DUMP" > "$DUMP_DEST"\n', encoding="utf-8")
    dump.chmod(0o755)
    return bindir


def boot(tmp_path: Path, monkeypatch: object) -> tuple[OcodeApp, Path]:
    import ocode.engines.ses as ses

    monkeypatch.setattr(ses, "state_dir", lambda: tmp_path / "state")
    bindir = make_stubs(tmp_path)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ.get("PATH", ""))
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "odoo.conf").write_text("[options]\ndb_name = mydb\n", encoding="utf-8")
    target = ws / "note.txt"
    target.write_text("hi\n", encoding="utf-8")
    app = OcodeApp(start_path=target, conf_override=ws / "odoo.conf")
    return (app, ws)


async def test_db_select_updates_profile(tmp_path: Path, monkeypatch: object) -> None:
    app, _ws = boot(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.server is not None
        app.action_db_manage()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.server.profile.db == "mydb"


async def test_db_backup_flow(tmp_path: Path, monkeypatch: object) -> None:
    app, _ws = boot(tmp_path, monkeypatch)
    dest = tmp_path / "mydb.dump"
    monkeypatch.setenv("DUMP_DEST", str(dest))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_db_manage()
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
        await pilot.press("enter")  # accept default dest (stub writes DUMP_DEST)
        waited = 0.0
        while not dest.is_file() and waited < 8.0:
            await asyncio.sleep(0.2)
            waited += 0.2
        assert dest.is_file()


async def test_db_drop_cancelled(tmp_path: Path, monkeypatch: object) -> None:
    app, _ws = boot(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_db_manage()
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()
        await pilot.press("n")  # cancel confirm
        await pilot.pause()
        log = tmp_path / "calls.log"
        assert "DROP DATABASE" not in (log.read_text(encoding="utf-8") if log.is_file() else "")
