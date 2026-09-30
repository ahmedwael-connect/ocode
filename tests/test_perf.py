"""M6 performance benchmarks (NFR §6.1 smoke level)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.benchmark


def test_bench_buffer_inserts(benchmark: object) -> None:
    from ocode.engines.ote.buffer import PieceTable

    def _run() -> int:
        pt = PieceTable("line\n" * 1000)
        for i in range(200):
            pt.insert(500 + i, "x")
        return len(pt)

    assert benchmark(_run) > 0  # type: ignore[operator]


def test_bench_log_throughput(benchmark: object) -> None:
    from ocode.engines.oss.logs import LogBuffer

    line = "2026-09-29 10:21:03 INFO mydb odoo.modules.loading: 12 modules loaded"

    def _run() -> int:
        buf = LogBuffer(max_lines=20000)
        for _ in range(5000):
            buf.append_raw(line)
        return len(buf)

    assert benchmark(_run) == 5000  # type: ignore[operator]


def test_bench_content_search(benchmark: object, tmp_path: Path) -> None:
    from ocode.engines.smn.search import content_search_sync

    for i in range(50):
        (tmp_path / f"m{i}.py").write_text("x = compute_value()\n" * 40, encoding="utf-8")

    def _run() -> int:
        return len(content_search_sync("compute_value", [tmp_path], max_hits=5000))

    assert benchmark(_run) == 50 * 40  # type: ignore[operator]


def test_bench_diagnostics(benchmark: object, tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from test_m4_oki import make_modules

    from ocode.engines.oki.db import OkiDb
    from ocode.engines.oki.indexer import Indexer
    from ocode.engines.oki.query import OkiQuery
    from ocode.engines.omls.diagnostics import FileCtx, analyze_file

    mods = make_modules(tmp_path)
    db = OkiDb(tmp_path / "idx.sqlite")
    try:
        Indexer(db, mods).build()
        q = OkiQuery(db)
        mod = next(m for m in mods if m.name == "sale_custom")
        text = (mod.path / "models" / "sale_order.py").read_text(encoding="utf-8")
        ctx = FileCtx(mod.path / "models" / "sale_order.py", mod, {}, [], q, "17.0", {})

        def _run() -> int:
            return len(analyze_file(text, ctx))

        benchmark(_run)  # type: ignore[operator]
    finally:
        db.close()
