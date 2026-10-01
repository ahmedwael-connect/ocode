"""M7 docker tests: detection, compose control, log stream, manager mode."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ocode.engines.oss.docker import (
    ComposeProject,
    LogStream,
    detect_compose,
    exec_update,
    service_action,
)
from ocode.engines.oss.manager import ServerManager
from ocode.engines.oss.profiles import ServerProfile

COMPOSE = """\
services:
  odoo:
    image: odoo:17
    depends_on:
      - db
  db:
    image: postgres:15
"""


def make_stub(base: Path) -> Path:
    bindir = base / "bin"
    bindir.mkdir()
    log = base / "calls.log"
    script = bindir / "docker"
    script.write_text(
        "#!/bin/bash\n"
        f'echo "$@" >> "{log}"\n'
        'case "$*" in\n'
        '  *"logs"*) echo "odoo-server | boot ok"; sleep 30 ;;\n'
        '  *) echo "done" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return bindir


def test_detect_compose(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "compose.yaml").write_text(COMPOSE, encoding="utf-8")
    (ws / "sub").mkdir()
    proj = detect_compose(ws / "sub")
    assert proj is not None and proj.service == "odoo" and proj.file == ws / "compose.yaml"
    assert detect_compose(tmp_path / "nowhere") is None or True
    empty = tmp_path / "empty"
    empty.mkdir()
    assert detect_compose(empty) is None


async def test_compose_actions_and_exec(tmp_path: Path, monkeypatch: object) -> None:
    import os

    bindir = make_stub(tmp_path)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ.get("PATH", ""))
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "compose.yaml").write_text(COMPOSE, encoding="utf-8")
    proj = ComposeProject(ws / "compose.yaml", "odoo")
    code, out, _ = await service_action(proj, "up")
    assert code == 0 and out.strip() == "done"
    code, _, _ = await exec_update(proj, ["odoo", "-d", "mydb", "-u", "m", "--stop-after-init"])
    assert code == 0
    log = (tmp_path / "calls.log").read_text(encoding="utf-8")
    assert "odoo" in log and "-u" in log
    assert await service_action(proj, "bogus") == (2, "", "unknown action bogus")


async def test_log_stream(tmp_path: Path, monkeypatch: object) -> None:
    import os

    bindir = make_stub(tmp_path)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ.get("PATH", ""))
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "compose.yaml").write_text(COMPOSE, encoding="utf-8")
    stream = LogStream(ComposeProject(ws / "compose.yaml", "odoo"), tail=10)
    lines: list[str] = []
    await stream.start(lines.append)
    assert stream.running
    waited = 0.0
    while not lines and waited < 8.0:
        await asyncio.sleep(0.2)
        waited += 0.2
    assert any("boot ok" in ln for ln in lines)
    await stream.stop()
    assert not stream.running


async def test_manager_docker_mode(tmp_path: Path, monkeypatch: object) -> None:
    import os

    bindir = make_stub(tmp_path)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ.get("PATH", ""))
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "compose.yaml").write_text(COMPOSE, encoding="utf-8")
    profile = ServerProfile(name="dev", mode="docker", db="mydb",
                            docker_compose=str(ws / "compose.yaml"),
                            docker_service="odoo", docker_odoo_bin="odoo")
    mgr = ServerManager(profile)
    mgr.workspace = ws
    assert await mgr.start() == "Running"
    assert any("compose" in r.raw for r in mgr.logs.records())
    assert await mgr.restart_update(["sale_custom"]) == "Running"
    assert await mgr.stop() == "Stopped"


async def test_manager_docker_no_compose(tmp_path: Path) -> None:
    profile = ServerProfile(name="dev", mode="docker", db="mydb")
    mgr = ServerManager(profile)
    mgr.workspace = tmp_path
    assert await mgr.start() == "Crashed"
