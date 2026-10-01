"""Minimal LSP client: initialize, didOpen/Change, completion, hover (M7).

Optional backend (editor.lsp, disabled by default). Tested against a stub
server; intended for real servers like pyright.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ocode.core.proto import FramedReader, write_message


@dataclass
class LspCompletion:
    label: str
    kind: str = ""
    detail: str = ""
    insert: str = ""


@dataclass
class LspHover:
    text: str = ""


class LspError(Exception):
    pass


class LspClient:
    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._notif: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self.capabilities: dict[str, Any] = {}
        self._stderr_task: asyncio.Task[None] | None = None
        self.stderr_lines: list[str] = []

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    def on_notification(self, method: str, fn: Callable[[dict[str, Any]], None]) -> None:
        self._notif.setdefault(method, []).append(fn)

    def _emit(self, method: str, params: dict[str, Any]) -> None:
        for fn in self._notif.get(method, []):
            try:
                fn(params)
            except OSError:
                pass

    async def start(self, cmd: list[str], cwd: str | None = None) -> None:
        if self.running:
            return
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, cwd=cwd,
            )
        except (OSError, NotImplementedError) as exc:
            raise LspError(f"cannot start {cmd[0]}: {exc}") from exc
        assert self._proc.stdout is not None and self._proc.stdin is not None
        if self._proc.stderr is not None:
            self._stderr_task = asyncio.ensure_future(self._drain_stderr())
        self._reader_task = asyncio.ensure_future(self._read_loop())

    async def _drain_stderr(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        while True:
            line = await self._proc.stderr.readline()
            if not line:
                break
            self.stderr_lines.append(line.decode("utf-8", errors="ignore").rstrip())
            self.stderr_lines = self.stderr_lines[-100:]

    async def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        framed = FramedReader(self._proc.stdout)
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
                    fut.set_exception(LspError("server exited"))
            self._pending.clear()

    def _dispatch(self, msg: dict[str, Any]) -> None:
        if "id" in msg and ("result" in msg or "error" in msg):
            key = msg["id"]
            fut = self._pending.pop(int(key)) if isinstance(key, int) else None
            if fut is None or fut.done():
                return
            if "error" in msg:
                fut.set_exception(LspError(str(msg["error"])[:300]))
            else:
                fut.set_result(msg.get("result"))
            return
        method = str(msg.get("method", ""))
        if method:
            self._emit(method, msg.get("params", {}) if isinstance(msg.get("params"), dict) else {})

    async def request(self, method: str, params: dict[str, Any], timeout: float = 15.0) -> Any:
        if self._proc is None or self._proc.stdin is None:
            raise LspError("not running")
        rid = next(self._ids)
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._pending[rid] = fut
        await write_message(self._proc.stdin, {
            "jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(rid, None)

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise LspError("not running")
        await write_message(self._proc.stdin, {
            "jsonrpc": "2.0", "method": method, "params": params})

    async def initialize(self, root: Path) -> dict[str, Any]:
        result = await self.request("initialize", {
            "processId": None, "rootUri": root.as_uri(),
            "capabilities": {"textDocument": {"completion": {}, "hover": {}}},
        })
        await self.notify("initialized", {})
        caps = result.get("capabilities", {}) if isinstance(result, dict) else {}
        self.capabilities = caps if isinstance(caps, dict) else {}
        return self.capabilities

    async def did_open(self, path: Path, language: str, text: str, version: int = 0) -> None:
        await self.notify("textDocument/didOpen", {
            "textDocument": {"uri": path.as_uri(), "languageId": language,
                             "version": version, "text": text}})

    async def did_change(self, path: Path, text: str, version: int = 1) -> None:
        await self.notify("textDocument/didChange", {
            "textDocument": {"uri": path.as_uri(), "version": version},
            "contentChanges": [{"text": text}]})

    async def completion(self, path: Path, line: int, col: int) -> list[LspCompletion]:
        result = await self.request("textDocument/completion", {
            "textDocument": {"uri": path.as_uri()},
            "position": {"line": line, "character": col}})
        items: list[Any] = []
        if isinstance(result, dict) and isinstance(result.get("items"), list):
            items = result["items"]
        elif isinstance(result, list):
            items = result
        out: list[LspCompletion] = []
        for it in items[:60]:
            if not isinstance(it, dict):
                continue
            label = str(it.get("label", ""))
            if label:
                out.append(LspCompletion(label, str(it.get("kind", "")),
                                         str(it.get("detail", "")),
                                         str(it.get("insertText", label))))
        return out

    async def hover(self, path: Path, line: int, col: int) -> LspHover:
        result = await self.request("textDocument/hover", {
            "textDocument": {"uri": path.as_uri()},
            "position": {"line": line, "character": col}})
        if isinstance(result, dict):
            contents = result.get("contents", "")
            if isinstance(contents, dict):
                contents = contents.get("value", "")
            if isinstance(contents, list):
                parts = [str(c.get("value", c)) if isinstance(c, dict) else str(c)
                         for c in contents]
                contents = "\n".join(parts)
            return LspHover(str(contents)[:2000])
        return LspHover()

    async def shutdown(self) -> None:
        try:
            if self.running:
                await self.request("shutdown", {}, timeout=5.0)
                await self.notify("exit", {})
        except (LspError, OSError, TimeoutError):
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        from ocode.core.proto import reap_subprocess

        proc, self._proc = self._proc, None
        await reap_subprocess([self._reader_task, self._stderr_task], proc)
        self._reader_task, self._stderr_task = None, None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(LspError("stopped"))
        self._pending.clear()
