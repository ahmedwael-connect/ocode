"""M7 LSP tests: framing + client handshake against a stub server."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from ocode.core.proto import FramingBuffer, encode_message, read_message
from ocode.engines.lsp import LspClient

STUB = """\
import json, sys
def read_msg():
    headers = b""
    while b"\\r\\n\\r\\n" not in headers:
        chunk = sys.stdin.buffer.read(1)
        if not chunk:
            return None
        headers += chunk
    head, _, rest = headers.partition(b"\\r\\n\\r\\n")
    length = 0
    for line in head.split(b"\\r\\n"):
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())
    body = rest
    while len(body) < length:
        more = sys.stdin.buffer.read(length - len(body))
        if not more:
            break
        body += more
    return json.loads(body.decode())
def send(obj):
    body = json.dumps(obj).encode()
    sys.stdout.buffer.write(b"Content-Length: %d\\r\\n\\r\\n" % len(body) + body)
    sys.stdout.buffer.flush()
while True:
    msg = read_msg()
    if msg is None:
        break
    method = msg.get("method", "")
    mid = msg.get("id")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid,
              "result": {"capabilities": {"completionProvider": {}, "hoverProvider": True}}})
    elif method == "textDocument/completion":
        send({"jsonrpc": "2.0", "id": mid,
              "result": [{"label": "stub_complete", "detail": "stub-kind"}]})
    elif method == "textDocument/hover":
        send({"jsonrpc": "2.0", "id": mid, "result": {"contents": "stub hover text"}})
    elif method == "shutdown":
        send({"jsonrpc": "2.0", "id": mid, "result": None})
    elif method == "exit":
        break
"""


def test_framing_roundtrip_and_partial() -> None:
    encoded = encode_message({"a": 1})
    assert encoded.startswith(b"Content-Length:")
    buf = FramingBuffer()
    assert buf.feed(encoded[:10]) == []
    assert buf.feed(encoded[10:]) == [{"a": 1}]
    both = encode_message({"x": 1}) + encode_message({"y": 2})
    assert buf.feed(both) == [{"x": 1}, {"y": 2}]


async def test_read_write_message() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(encode_message({"hello": "world"}))
    reader.feed_eof()
    assert await read_message(reader) == {"hello": "world"}
    try:
        await read_message(reader)
    except EOFError:
        pass
    else:
        raise AssertionError("expected EOFError")


async def test_lsp_handshake_and_requests(tmp_path: Path) -> None:
    stub = tmp_path / "stub_lsp.py"
    stub.write_text(STUB, encoding="utf-8")
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    client = LspClient()
    try:
        await client.start([sys.executable, str(stub)])
        caps = await client.initialize(tmp_path)
        assert "completionProvider" in caps
        await client.did_open(target, "python", "x = 1\n")
        items = await client.completion(target, 0, 0)
        assert [i.label for i in items] == ["stub_complete"]
        assert items[0].detail == "stub-kind"
        hover = await client.hover(target, 0, 0)
        assert hover.text == "stub hover text"
    finally:
        await client.shutdown()
    assert not client.running


async def test_lsp_notification_hook() -> None:
    client = LspClient()
    seen: list[str] = []
    client.on_notification("test/notice", lambda params: seen.append(str(params.get("v"))))
    client._dispatch({"jsonrpc": "2.0", "method": "test/notice", "params": {"v": "1"}})
    assert seen == ["1"]
    await client.stop()


async def test_lsp_start_failure() -> None:
    from ocode.engines.lsp import LspError

    client = LspClient()
    try:
        await client.start(["/nonexistent/lsp-xyz"])
    except LspError:
        pass
    else:
        raise AssertionError("expected LspError")


async def test_lsp_merges_into_popup(tmp_path: Path, monkeypatch: object) -> None:
    import ocode.engines.ses as ses

    monkeypatch.setattr(ses, "state_dir", lambda: tmp_path / "state")
    stub = tmp_path / "stub_lsp.py"
    stub.write_text(STUB.replace("stub_complete", "lsp_magic"), encoding="utf-8")
    target = tmp_path / "m.py"
    target.write_text("x = 1\n", encoding="utf-8")
    from ocode.app import OcodeApp
    from ocode.core.config import OcodeConfig
    from ocode.engines.oki.db import OkiDb
    from ocode.engines.oki.query import OkiQuery
    from ocode.ui.widgets.complete import CompletionPopup

    lsp_cfg: dict[str, object] = {"enabled": True, "command": [sys.executable, str(stub)]}
    cfg = OcodeConfig(data={"editor": {"lsp": lsp_cfg}})
    app = OcodeApp(start_path=target, config=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        db = OkiDb(tmp_path / "empty.sqlite")
        app.oki_db, app.oki = db, OkiQuery(db)
        app._ensure_lsp()
        waited = 0.0
        while (app.lsp is None or not app.lsp.running) and waited < 8.0:
            await asyncio.sleep(0.2)
            waited += 0.2
        assert app.lsp is not None and app.lsp.running
        st = app.active_state()
        st.set_cursor(st.offset_to_pos(len(st.doc.text)))
        st.type_text("xy")
        await app._lsp_refresh_popup()
        await pilot.pause()
        pop = app.query_one("#complete", CompletionPopup)
        assert any(c.label == "lsp_magic" for c in pop.items)
        if app.lsp is not None:
            await app.lsp.shutdown()
