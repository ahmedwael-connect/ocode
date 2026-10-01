"""M6 tests: help screen, doctor keys, ascii flag, packaging files, perf smoke."""

from __future__ import annotations

import time
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_help_screen_opens(tmp_path: Path, monkeypatch: object) -> None:
    import ocode.engines.ses as ses

    monkeypatch.setattr(ses, "state_dir", lambda: tmp_path / "state")
    from ocode.app import OcodeApp
    from ocode.ui.screens.info import HELP_SECTIONS, HelpScreen

    assert any("Ctrl+P" in keys for _, rows in HELP_SECTIONS for keys, _ in rows)
    target = tmp_path / "f.txt"
    target.write_text("hi\n", encoding="utf-8")
    app = OcodeApp(start_path=target)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_show_help()
            await pilot.pause()
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.pause()

    import asyncio as _aio

    _aio.run(_run())


def test_doctor_keys_output(capsys: object) -> None:
    from ocode.__main__ import main

    assert main(["doctor", "keys"]) == 0
    out = capsys.readouterr().out  # type: ignore[union-attr]
    assert "kitty" in out and "Ctrl+`" in out


def test_ascii_flag_parses() -> None:
    from ocode.__main__ import _extract_subcommand, build_parser, main

    assert _extract_subcommand(["."])[0] is None
    assert _extract_subcommand(["models/a.py:3"])[0] is None
    assert _extract_subcommand(["doctor"]) == ("doctor", [])
    assert _extract_subcommand(["doctor", "keys"]) == ("doctor", ["keys"])
    assert _extract_subcommand(["--db", "x", "index"]) == ("index", ["--db", "x"])
    args = build_parser().parse_args(["--ascii", "models/a.py:3"])
    assert args.path == "models/a.py:3" and args.ascii is True
    assert main(["--version"]) == 0


def test_cli_init_and_index_no_project(tmp_path: Path, monkeypatch: object) -> None:
    from ocode.__main__ import main

    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    assert (tmp_path / ".ocode" / "servers.toml").is_file()
    assert main(["index"]) == 1  # no Odoo project here


def test_packaging_files_exist() -> None:
    for rel in ("ocode.1", "CHANGELOG.md", "README.md",
                "completions/ocode.bash", "completions/ocode.zsh",
                "completions/ocode.fish", "debian/control", "debian/rules",
                "debian/changelog", "debian/copyright", "debian/source/format",
                "debian/ocode.manpages", "debian/README.Debian"):
        assert (ROOT / rel).is_file(), rel
    import stat as _stat

    assert bool((ROOT / "debian" / "rules").stat().st_mode & _stat.S_IXUSR)


def test_version_is_release() -> None:
    from ocode import __version__

    assert __version__ == "1.0.2"
    from importlib.metadata import version as _v

    assert _v("ocode") == "1.0.2"


def test_log_throughput_smoke() -> None:
    from ocode.engines.oss.logs import LogBuffer

    buf = LogBuffer(max_lines=20000)
    line = "2026-09-29 10:21:03 INFO mydb odoo.modules.loading: loaded"
    t0 = time.time()
    for _ in range(5000):
        buf.append_raw(line)
    assert time.time() - t0 < 5.0  # ≥5k lines/s with margin
    assert len(buf) == 5000
