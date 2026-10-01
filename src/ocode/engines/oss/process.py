"""Managed child process: start/stop/restart with graceful escalation (FR-OSS-001..003)."""

from __future__ import annotations

import asyncio
import os
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class ProcResult:
    returncode: int
    output: str


class ManagedProc:
    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self.pid: int | None = None
        self.started_at: float | None = None
        self.returncode: int | None = None
        self._readers: list[asyncio.Task[None]] = []
        self.on_line: Callable[[str], None] | None = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    @property
    def uptime(self) -> float:
        if self.started_at is None:
            return 0.0
        return time.time() - self.started_at

    async def start(
        self,
        prog: str,
        argv: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> int:
        if self.running:
            raise RuntimeError("process already running")
        merged = dict(os.environ)
        if env:
            merged.update(env)
        merged.setdefault("PYTHONUNBUFFERED", "1")
        self.proc = await asyncio.create_subprocess_exec(
            prog,
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged,
            cwd=cwd,
            start_new_session=True,
        )
        self.pid = self.proc.pid
        self.started_at = time.time()
        self.returncode = None
        if self.proc.stdout is not None:
            self._readers.append(asyncio.ensure_future(self._pump(self.proc.stdout)))
        if self.proc.stderr is not None:
            self._readers.append(asyncio.ensure_future(self._pump(self.proc.stderr)))
        return self.pid

    async def _pump(self, stream: asyncio.StreamReader) -> None:
        while True:
            line = await stream.readline()
            if not line:
                break
            if self.on_line is not None:
                try:
                    self.on_line(line.decode("utf-8", errors="ignore").rstrip("\n"))
                except OSError:
                    break

    async def _reap_readers(self) -> None:
        if not self._readers:
            return
        # let pumps drain to EOF first (clean transport shutdown), then cancel stragglers
        _, pending = await asyncio.wait(self._readers, timeout=2.0)
        for t in pending:
            t.cancel()
        await asyncio.gather(*self._readers, return_exceptions=True)
        self._readers = []
        # close the transport deterministically (avoids GC-on-closed-loop warnings)
        transport = getattr(self.proc, "_transport", None)
        if transport is not None:
            try:
                transport.close()
            except (OSError, RuntimeError):
                pass

    async def wait(self) -> int:
        if self.proc is None:
            return -1
        rc = await self.proc.wait()
        self.returncode = rc
        await self._reap_readers()
        return rc

    async def stop(self, timeout: float = 10.0) -> int:
        """SIGINT → SIGTERM → SIGKILL escalation. Returns final returncode."""
        proc = self.proc
        if proc is None:
            return -1
        if proc.returncode is not None:
            return proc.returncode
        assert proc.pid is not None
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                os.killpg(os.getpgid(proc.pid), sig)
            except (OSError, ProcessLookupError):
                break
            try:
                await asyncio.wait_for(proc.wait(), timeout / 2)
                self.returncode = proc.returncode
                await self._reap_readers()
                return proc.returncode if proc.returncode is not None else -1
            except TimeoutError:
                continue
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        try:
            await asyncio.wait_for(proc.wait(), 5.0)
        except TimeoutError:
            pass
        self.returncode = proc.returncode
        await self._reap_readers()
        return proc.returncode if proc.returncode is not None else -1
