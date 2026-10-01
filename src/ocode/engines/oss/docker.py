"""Docker/compose control for Odoo services (M7).

All commands are arg lists (no shell). Tested against stub binaries;
requires a real daemon for actual use.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

COMPOSE_FILES = ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml")


@dataclass
class ComposeProject:
    file: Path
    service: str = "odoo"

    @property
    def directory(self) -> Path:
        return self.file.parent


def detect_compose(start: Path, service_hint: str = "odoo") -> ComposeProject | None:
    """Walk up looking for a compose file mentioning an odoo service."""
    cur = start if start.is_dir() else start.parent
    for cand in [cur, *cur.parents]:
        for name in COMPOSE_FILES:
            found = cand / name
            try:
                if not found.is_file():
                    continue
                text = found.read_text(encoding="utf-8")
            except OSError:
                continue
            services = _service_names(text)
            if not services:
                continue
            service = service_hint if service_hint in services else _odoo_like(services)
            if service is not None:
                return ComposeProject(found, service)
        if cand == cand.parent:
            break
    return None


def _service_names(text: str) -> list[str]:
    """Top-level keys under `services:` (regex-based, no yaml dependency)."""
    lines = text.splitlines()
    in_services, base_indent = False, 0
    names: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if re.match(r"^services\s*:\s*$", stripped):
            in_services, base_indent = True, indent
            continue
        if in_services:
            if indent <= base_indent and re.match(r"^\S", stripped):
                break  # next top-level section
            if indent > base_indent and re.match(r"^[A-Za-z0-9_.-]+\s*:\s*$", stripped):
                names.append(stripped.split(":")[0])
    return names


def _odoo_like(services: list[str]) -> str | None:
    for svc in services:
        if "odoo" in svc.lower():
            return svc
    return services[0] if services else None


def docker_available() -> tuple[bool, str]:
    if shutil.which("docker") is None:
        return (False, "docker not found")
    return (True, "")


def base_args(project: ComposeProject) -> list[str]:
    return ["docker", "compose", "-f", str(project.file)]


async def compose(
    project: ComposeProject, args: list[str], timeout: int = 120,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Run `docker compose …`. Returns (returncode, stdout, stderr)."""
    merged = dict(os.environ)
    if env:
        merged.update(env)
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "-f", str(project.file), *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=merged, cwd=str(project.directory),
        )
    except (OSError, NotImplementedError) as exc:
        return (127, "", str(exc))
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return (124, "", "timed out")
    code = proc.returncode if proc.returncode is not None else 1
    return (code, out.decode("utf-8", errors="ignore"), err.decode("utf-8", errors="ignore"))


async def service_action(project: ComposeProject, action: str) -> tuple[int, str, str]:
    """up -d | stop | start | restart | down for the odoo service."""
    if action == "up":
        return await compose(project, ["up", "-d", project.service])
    if action in ("stop", "start", "restart"):
        return await compose(project, [action, project.service])
    if action == "down":
        return await compose(project, ["down"])
    return (2, "", f"unknown action {action}")


async def exec_update(
    project: ComposeProject, odoo_argv: list[str], timeout: int = 600
) -> tuple[int, str, str]:
    """Run an update inside the running container (exec, not a new one)."""
    return await compose(project, ["exec", "-T", project.service, *odoo_argv], timeout=timeout)


class LogStream:
    """`docker compose logs -f` streamer feeding lines to a callback."""

    def __init__(self, project: ComposeProject, tail: int = 200) -> None:
        self.project = project
        self.tail = tail
        self._proc: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self, on_line: Callable[[str], None]) -> None:
        try:
            self._proc = await asyncio.create_subprocess_exec(
                "docker", "compose", "-f", str(self.project.file),
                "logs", "-f", "--tail", str(self.tail), self.project.service,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                cwd=str(self.project.directory),
            )
        except (OSError, NotImplementedError):
            return
        assert self._proc.stdout is not None

        async def _pump() -> None:
            assert self._proc is not None and self._proc.stdout is not None
            while True:
                line = await self._proc.stdout.readline()
                if not line:
                    break
                on_line(line.decode("utf-8", errors="ignore").rstrip("\n"))

        self._task = asyncio.ensure_future(_pump())

    async def stop(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            try:
                self._proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self._proc.wait(), 5.0)
            except TimeoutError:
                try:
                    self._proc.kill()
                except ProcessLookupError:
                    pass
        # drain pump to EOF so the pipe transport closes cleanly
        if self._task is not None and not self._task.done():
            try:
                await asyncio.wait_for(self._task, 2.0)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
        self._task = None
        self._proc = None
