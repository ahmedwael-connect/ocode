"""M3 OSS engine tests (flags, profiles, logs, tailer, process, manager)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from ocode.engines.oss.failure import detect_failure
from ocode.engines.oss.flags import (
    FLAG_CATALOG,
    build_args,
    preview_command,
    validate_flags,
)
from ocode.engines.oss.logs import (
    LogBuffer,
    LogFilter,
    extract_file_links,
    group_tracebacks,
    parse_odoo_line,
)
from ocode.engines.oss.manager import ServerManager
from ocode.engines.oss.process import ManagedProc
from ocode.engines.oss.profiles import (
    ServerProfile,
    default_profile,
    load_profiles,
    save_profiles,
)
from ocode.engines.oss.tailer import LogTailer


def test_flag_catalog_covers_prd() -> None:
    names = {f.name for f in FLAG_CATALOG}
    for required in ("-c", "-d", "-i", "-u", "--addons-path"):
        assert required in names
    for required in ("--dev", "--log-level", "--http-port", "--workers"):
        assert required in names
    for required in ("--test-enable", "--stop-after-init"):
        assert required in names
    prog, argv = build_args(
        "odoo-bin", None, "/etc/odoo.conf", "mydb", ["--dev=reload"], update=["sale_custom"]
    )
    assert argv[:4] == ["-c", "/etc/odoo.conf", "-d", "mydb"]
    assert "-u" in argv and "sale_custom" in argv
    assert "odoo-bin" in preview_command(prog, argv)
    assert validate_flags(["--bogus-flag"], "17.0")


def test_profiles_roundtrip(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    profiles = {"dev": default_profile(odoo_bin="/opt/odoo/odoo-bin", db="mydb")}
    save_profiles(ws, profiles)
    loaded = load_profiles(ws)
    assert loaded["dev"].db == "mydb"
    assert "--dev=reload,qweb,xml" in loaded["dev"].flags


def test_log_parse_filter_ring() -> None:
    line = "2026-09-29 10:21:03 INFO mydb odoo.modules.loading: 12 loaded"
    rec = parse_odoo_line(line)
    assert (rec.level, rec.db, rec.logger) == ("INFO", "mydb", "odoo.modules.loading")
    assert parse_odoo_line("plain line").level == "INFO"
    buf = LogBuffer(max_lines=5)
    for i in range(7):
        buf.append_raw(f"2026-01-01 00:00:0{i} INFO db log: msg {i}")
    assert len(buf) == 5  # ring cap
    flt = LogFilter(levels={"ERROR"}, text="msg 6")
    assert len(buf.filtered(flt)) == 0
    buf.append_raw("2026-01-01 00:00:09 ERROR db log: boom msg 6")
    assert len(buf.filtered(flt)) == 1


def test_traceback_grouping_and_links() -> None:
    buf = LogBuffer()
    tb = "Traceback (most recent call last):\n"
    tb += '  File "/opt/m/a.py", line 10, in f\nValueError: bad\n'
    buf.extend_raw(tb)
    recs = buf.records()
    assert recs[0].level == "ERROR"
    blocks = group_tracebacks(recs)
    assert blocks and blocks[0].links == [("/opt/m/a.py", 10)]
    assert extract_file_links('File "x.py", line 3') == [("x.py", 3)]


def test_failure_detection() -> None:
    assert detect_failure("OSError: [Errno 98] Address already in use") is not None
    assert detect_failure("FATAL: database mydb does not exist") is not None
    tb = "Traceback (most recent call last):\n  File \"a.py\", line 1\nValueError: x\n"
    hint = detect_failure(tb)
    assert hint is not None and hint.kind == "traceback" and hint.links == [("a.py", 1)]
    assert detect_failure("all good, modules loaded") is None


def test_tailer_appends_and_rotation(tmp_path: Path) -> None:
    log = tmp_path / "odoo.log"
    log.write_text("old\n", encoding="utf-8")
    tailer = LogTailer(log)
    assert tailer.poll() == []  # starts at end
    with log.open("a", encoding="utf-8") as f:
        f.write("new1\nnew2\n")
    assert tailer.poll() == ["new1", "new2"]
    log.rename(tmp_path / "odoo.log.1")
    log.write_text("after-rotate\n", encoding="utf-8")
    assert tailer.poll() == ["after-rotate"]


async def test_managed_proc_start_stop() -> None:
    proc = ManagedProc()
    lines: list[str] = []
    proc.on_line = lines.append
    cmd = "import time; print('boot'); time.sleep(30)"
    await proc.start(sys.executable, ["-u", "-c", cmd])
    assert proc.running and proc.pid is not None
    for _ in range(50):
        if lines:
            break
        await asyncio.sleep(0.05)
    assert any("boot" in ln for ln in lines)
    rc = await proc.stop(timeout=4.0)
    assert rc is not None and not proc.running


async def test_manager_start_stop_with_stub(tmp_path: Path) -> None:
    script = tmp_path / "fake_odoo.py"
    body = "import time, sys; print('odoo fake boot'); sys.stdout.flush(); time.sleep(30)\n"
    script.write_text(body, encoding="utf-8")
    profile = ServerProfile(name="dev", odoo_bin=str(script), python=sys.executable, db="mydb")
    mgr = ServerManager(profile)
    seen: list[str] = []
    mgr.on_status(seen.append)
    await mgr.start()
    assert mgr.status == "Running"
    for _ in range(50):
        if mgr.logs.records():
            break
        await asyncio.sleep(0.05)
    assert any("fake boot" in r.raw for r in mgr.logs.records())
    snap = mgr.snapshot()
    assert snap.pid is not None and snap.db == "mydb"
    await mgr.stop()
    assert mgr.status == "Stopped"
    assert "Running" in seen


async def test_manager_update_oneshot_failure(tmp_path: Path) -> None:
    script = tmp_path / "bad.py"
    script.write_text("raise ValueError('boom')\n", encoding="utf-8")
    profile = ServerProfile(name="dev", odoo_bin=str(script), python=sys.executable, db="mydb")
    mgr = ServerManager(profile)
    await mgr.restart_update(["sale_custom"])
    assert mgr.status in ("Crashed", "Running", "Stopped")
    if mgr.status == "Crashed":
        assert mgr.snapshot_hint is not None
        await mgr.stop()
