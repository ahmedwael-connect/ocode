"""M7 DAP tests: handshake, breakpoints, stopped event, evaluate (stub adapter)."""

from __future__ import annotations

from pathlib import Path

from ocode.engines.dap import DapClient

STUB = """\
import json, sys
seq = 100
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
    global seq
    seq += 1
    obj = dict(obj)
    obj.setdefault("seq", seq)
    body = json.dumps(obj).encode()
    sys.stdout.buffer.write(b"Content-Length: %d\\r\\n\\r\\n" % len(body) + body)
    sys.stdout.buffer.flush()
while True:
    msg = read_msg()
    if msg is None:
        break
    cmd = msg.get("command", "")
    req = msg.get("seq", 0)
    if cmd == "initialize":
        send({"type": "response", "request_seq": req, "success": True,
              "command": "initialize", "body": {"supportsConfigurationDoneRequest": True}})
    elif cmd == "launch":
        send({"type": "response", "request_seq": req, "success": True, "command": "launch"})
    elif cmd == "setBreakpoints":
        n = len(msg.get("arguments", {}).get("breakpoints", []))
        send({"type": "response", "request_seq": req, "success": True, "command": "setBreakpoints",
              "body": {"breakpoints": [{"verified": True} for _ in range(n)]}})
    elif cmd == "configurationDone":
        send({"type": "response", "request_seq": req, "success": True,
              "command": "configurationDone"})
        send({"type": "event", "event": "stopped",
              "body": {"reason": "breakpoint", "threadId": 1}})
    elif cmd == "threads":
        send({"type": "response", "request_seq": req, "success": True, "command": "threads",
              "body": {"threads": [{"id": 1, "name": "main"}]}})
    elif cmd == "evaluate":
        send({"type": "response", "request_seq": req, "success": True, "command": "evaluate",
              "body": {"result": "42", "type": "int"}})
    elif cmd == "disconnect":
        send({"type": "response", "request_seq": req, "success": True, "command": "disconnect"})
        break
"""


async def _client(tmp_path: Path) -> DapClient:
    import sys

    stub = tmp_path / "stub_dap.py"
    stub.write_text(STUB, encoding="utf-8")
    client = DapClient()
    await client.start([sys.executable, str(stub)])
    return client


async def test_dap_handshake_breakpoints(tmp_path: Path) -> None:
    client = await _client(tmp_path)
    try:
        caps = await client.initialize()
        assert caps.get("supportsConfigurationDoneRequest") is True
        await client.launch({"program": "x.py"})
        assert await client.set_breakpoints("/tmp/x.py", [10, 20]) == [True, True]
        await client.configuration_done()
        threads = await client.threads()
        assert [t["id"] for t in threads] == [1]
        assert await client.evaluate("1+1") == "42"
    finally:
        await client.disconnect()
    assert not client.connected


async def test_dap_stopped_event(tmp_path: Path) -> None:
    import asyncio as _aio

    client = await _client(tmp_path)
    try:
        stopped: list[dict[str, object]] = []
        client.on_event("stopped", stopped.append)
        await client.initialize()
        await client.launch({})
        await client.set_breakpoints("/tmp/x.py", [3])
        await client.configuration_done()
        for _ in range(50):
            if stopped:
                break
            await _aio.sleep(0.1)
        assert stopped and stopped[0].get("reason") == "breakpoint"
    finally:
        await client.disconnect()


async def test_dap_connect_failure() -> None:
    from ocode.engines.dap import DapError

    client = DapClient()
    try:
        await client.connect("127.0.0.1", 1, timeout=1.0)
    except DapError:
        pass
    else:
        raise AssertionError("expected DapError")
    await client.stop()


async def test_breakpoint_toggle_persist_gutter(tmp_path: Path, monkeypatch: object) -> None:
    import ocode.engines.ses as ses

    monkeypatch.setattr(ses, "state_dir", lambda: tmp_path / "state")
    from ocode.app import OcodeApp
    from ocode.ui.widgets.editor import OcodeEditor

    ws = tmp_path / "ws"
    ws.mkdir()
    target = ws / "a.py"
    target.write_text("x = 1\ny = 2\n", encoding="utf-8")
    app = OcodeApp(start_path=target)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_debug_breakpoint()
        await pilot.pause()
        assert app.breakpoints == {str(target): [1]}
        editor = app.query_one("#editor", OcodeEditor)
        assert 1 in editor.breakpoints
        assert editor._gutter_mark(1) == ("●", "bold blue")
        assert (ws / ".ocode" / "breakpoints.json").is_file()
        app.action_debug_breakpoint()
        assert app.breakpoints.get(str(target)) == []


async def test_manager_start_debug_needs_python(tmp_path: Path) -> None:
    from ocode.engines.oss.manager import ServerManager
    from ocode.engines.oss.profiles import ServerProfile

    mgr = ServerManager(ServerProfile(name="dev"))
    assert await mgr.start_debug() == "Crashed"
