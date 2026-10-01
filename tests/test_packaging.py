"""Packaging regression test: the wheel must ship code + data (M6 lesson)."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent

REQUIRED = (
    "ocode/app.py",
    "ocode/ui/screens/palette.py",
    "ocode/ui/widgets/editor.py",
    "ocode/ui/default.tcss",
    "ocode/templates/model.j2",
    "ocode/templates/view.j2",
    "ocode/data/versions/17.0.toml",
    "ocode/engines/omls/complete.py",
)


def test_wheel_contains_code_and_data(tmp_path: Path) -> None:
    outdir = tmp_path / "dist"
    proc = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(outdir)],
        cwd=ROOT, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    wheels = list(outdir.glob("*.whl"))
    assert len(wheels) == 1
    names = set(zipfile.ZipFile(wheels[0]).namelist())
    missing = [r for r in REQUIRED if r not in names]
    assert not missing, f"missing from wheel: {missing}"
