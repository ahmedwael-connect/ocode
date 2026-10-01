"""Minimal DAP client: initialize/launch/breakpoints/evaluate (M7).

Speaks Debug Adapter Protocol over stdio or TCP (same Content-Length
framing as LSP). Tested against a stub adapter; intended for debugpy.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ocode.core.proto import FramedReader, write_message


class DapError(Exception):
    pass


@dataclass
class StoppedEvent:
    reason: str = ""
    thread_id: int = 0


class DapClient:
    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._seq = itertools.count(1)
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._events: dict[str, list[Callable[[dict[str, Any]], None]]] = {}

    @property
    def connected(self) -> bool:
        if self._proc is not None:
            return self._proc.returncode is None
        return self._writer is not None

    def on_event(self, name: str, fn: Callable[[dict[str, Any]], None]) -> None:
        self._events.setdefault(name, []).append(fn)

    def _emit(self, name: str, body: dict[str, Any]) -> None:
        for fn in self._events.get(name, []):
            try:
                fn(body)
            except OSError:
                pass

    async def start(self, cmd: list[str], cwd: str | None = None) -> None:
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, cwd=cwd,
            )
        except (OSError, NotImplementedError) as exc:
            raise DapError(f"cannot start {cmd[0]}: {exc}") from exc
        assert self._proc.stdout is not None
        self._reader_task = asyncio.ensure_future(self._read_loop(self._proc.stdout))

    async def connect(self, host: str, port: int, timeout: float = 10.0) -> None:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        except (OSError, TimeoutError) as exc:
            raise DapError(f"cannot connect {host}:{port}: {exc}") from exc
        self._writer = writer
        self._reader_task = asyncio.ensure_future(self._read_loop(reader))

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        framed = FramedReader(reader)
        try:
            while True:
                try:
                    msg = await framed.read()
                except EOFError:
                    break
                self._dispatch(msg)
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(DapError("adapter exited"))
            self._pending.clear()

    def _dispatch(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "response":
            seq = msg.get("request_seq")
            fut = self._pending.pop(int(seq)) if isinstance(seq, int) else None
            if fut is None or fut.done():
                return
            if msg.get("success"):
                fut.set_result(msg.get("body", {}))
            else:
                fut.set_exception(DapError(str(msg.get("message", "request failed"))[:300]))
        elif kind == "event":
            event = str(msg.get("event", ""))
            body = msg.get("body", {})
            if event:
                self._emit(event, body if isinstance(body, dict) else {})

    async def request(self, command: str, args: dict[str, Any] | None = None,
                      timeout: float = 15.0) -> Any:
        writer: asyncio.StreamWriter | None = None
        if self._proc is not None and self._proc.stdin is not None:
            writer = self._proc.stdin
        elif self._writer is not None:
            writer = self._writer
        if writer is None:
            raise DapError("not connected")
        seq = next(self._seq)
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._pending[seq] = fut
        await write_message(writer, {"seq": seq, "type": "request",
                                     "command": command, "arguments": args or {}})
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(seq, None)

    async def initialize(self) -> dict[str, Any]:
        result = await self.request("initialize", {
            "clientID": "ocode", "adapterID": "debugpy",
            "pathFormat": "path", "linesStartAt1": True, "columnsStartAt1": True})
        return result if isinstance(result, dict) else {}

    async def launch(self, config: dict[str, Any]) -> None:
        await self.request("launch", config)

    async def set_breakpoints(self, path: str, lines: list[int]) -> list[bool]:
        body = await self.request("setBreakpoints", {
            "source": {"path": path},
            "breakpoints": [{"line": ln} for ln in lines]})
        out: list[bool] = []
        bps = body.get("breakpoints", []) if isinstance(body, dict) else []
        for bp in bps if isinstance(bps, list) else []:
            out.append(bool(bp.get("verified", False)) if isinstance(bp, dict) else False)
        while len(out) < len(lines):
            out.append(False)
        return out

    async def configuration_done(self) -> None:
        await self.request("configurationDone", {})

    async def threads(self) -> list[dict[str, Any]]:
        body = await self.request("threads", {})
        threads = body.get("threads", []) if isinstance(body, dict) else []
        return [t for t in threads if isinstance(t, dict)]

    async def evaluate(self, expression: str, frame_id: int = 0) -> str:
        body = await self.request("evaluate", {"expression": expression,
                                               "frameId": frame_id, "context": "repl"})
        if isinstance(body, dict):
            return str(body.get("result", ""))
        return ""

    async def disconnect(self) -> None:
        try:
            if self.connected:
                await self.request("disconnect", {"terminateDebuggee": False}, timeout=5.0)
        except (DapError, OSError, TimeoutError):
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        from ocode.core.proto import reap_subprocess

        writer, self._writer = self._writer, None
        if writer is not None:
            try:
                writer.close()
            except OSError:
                pass
        proc, self._proc = self._proc, None
        await reap_subprocess([self._reader_task], proc)
        self._reader_task = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(DapError("stopped"))
        self._pending.clear()
