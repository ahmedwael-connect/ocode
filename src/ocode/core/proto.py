"""Content-Length framing shared by LSP and DAP (both use LSP-style headers)."""

from __future__ import annotations

import asyncio
import json
from typing import Any


def encode_message(obj: dict[str, Any]) -> bytes:
    body = json.dumps(obj).encode("utf-8")
    return b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body


class FramingBuffer:
    """Incremental parser; feed() returns complete decoded messages."""

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, data: bytes) -> list[dict[str, Any]]:
        self._buf += data
        out: list[dict[str, Any]] = []
        while True:
            head, sep, rest = self._buf.partition(b"\r\n\r\n")
            if not sep:
                break
            length: int | None = None
            for line in head.split(b"\r\n"):
                name, _, value = line.partition(b":")
                if name.strip().lower() == b"content-length":
                    try:
                        length = int(value.strip())
                    except ValueError:
                        length = None
            if length is None:
                # desync: drop header block
                self._buf = rest
                continue
            if len(rest) < length:
                break
            body, self._buf = rest[:length], rest[length:]
            try:
                obj = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(obj, dict):
                out.append(obj)
        return out


async def read_message(reader: asyncio.StreamReader) -> dict[str, Any]:
    """Read one message. NOTE: prefer FramedReader for streams with back-to-back messages."""
    buf = FramingBuffer()
    while True:
        chunk = await reader.read(65536)
        if not chunk:
            pending = buf.feed(b"")
            if pending:
                return pending[0]
            raise EOFError("stream closed")
        messages = buf.feed(chunk)
        if messages:
            return messages[0]


class FramedReader:
    """Stateful reader that never drops pipelined messages."""

    def __init__(self, reader: asyncio.StreamReader) -> None:
        self._reader = reader
        self._buf = FramingBuffer()
        self._ready: list[dict[str, Any]] = []

    async def read(self) -> dict[str, Any]:
        while not self._ready:
            chunk = await self._reader.read(65536)
            if not chunk:
                raise EOFError("stream closed")
            self._ready.extend(self._buf.feed(chunk))
        return self._ready.pop(0)


async def write_message(writer: asyncio.StreamWriter, obj: dict[str, Any]) -> None:
    writer.write(encode_message(obj))
    await writer.drain()


async def reap_subprocess(
    tasks: list[asyncio.Task[Any] | None],
    proc: asyncio.subprocess.Process | None,
) -> None:
    """Terminate, wait, drain pumps, close transport (no GC-on-closed-loop warnings)."""
    if proc is not None and proc.returncode is None:
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), 5.0)
        except TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
    live = [t for t in tasks if t is not None and not t.done()]
    if live:
        _, pending = await asyncio.wait(live, timeout=2.0)
        for t in pending:
            t.cancel()
        await asyncio.gather(*live, return_exceptions=True)
    transport = getattr(proc, "_transport", None)
    if transport is not None:
        try:
            transport.close()
        except (OSError, RuntimeError):
            pass
