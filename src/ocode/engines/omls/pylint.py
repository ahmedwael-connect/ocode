"""External linters: pylint-odoo (Must) + ruff (optional) as subprocesses (FR-OMLS-030..034)."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ocode.engines.omls.diagnostics import Diagnostic


@dataclass
class PylintResult:
    diagnostics: list[Diagnostic] = field(default_factory=list)
    raw: str = ""
    returncode: int = 0
    hint: str = ""  # set when linter missing


MSG_RE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):\s*(?P<code>[A-Z]\d+):\s*(?P<msg>.*)$"
)


def pylint_available() -> tuple[bool, str]:
    if shutil.which("pylint") is None:
        return (False, "pylint not found (pip install pylint-odoo into the Odoo venv)")
    try:
        proc = subprocess.run(
            [sys.executable, "-c", "import pylint_odoo"],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return (False, "cannot probe pylint_odoo")
    if proc.returncode != 0:
        return (False, "pylint_odoo missing (pip install pylint-odoo into the Odoo venv)")
    return (True, "")


def _sev_for(code: str) -> str:
    if code.startswith("E"):
        return "error"
    if code.startswith("W"):
        return "warning"
    return "info"


def run_pylint_odoo(
    paths: list[Path], version: str | None = None, timeout: int = 120
) -> PylintResult:
    ok, hint = pylint_available()
    if not ok:
        return PylintResult(hint=hint)
    cmd = ["pylint", "--load-plugins=pylint_odoo", "--score=n",
           "--output-format=text", "--disable=all", "--enable=odoolint"]
    if version:
        cmd.append(f"--valid-odoo-versions={version}")
    cmd += [str(p) for p in paths]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return PylintResult(hint=f"pylint failed: {exc}")
    diags: list[Diagnostic] = []
    for line in proc.stdout.splitlines():
        m = MSG_RE.match(line)
        if m:
            try:
                lineno, col = int(m.group("line")), int(m.group("col"))
            except ValueError:
                lineno, col = 1, 1
            diags.append(Diagnostic(
                m.group("file"), lineno, col + 1, _sev_for(m.group("code")),
                "PYLINT", f"{m.group('code')}: {m.group('msg')}",
            ))
    return PylintResult(diags, proc.stdout, proc.returncode)


def run_ruff(paths: list[Path], timeout: int = 60) -> PylintResult:
    if shutil.which("ruff") is None:
        return PylintResult(hint="ruff not found")
    cmd = ["ruff", "check", "--output-format=concise", *[str(p) for p in paths]]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return PylintResult(hint=f"ruff failed: {exc}")
    diags: list[Diagnostic] = []
    pat = r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):\s*(?P<msg>.*)$"
    for line in proc.stdout.splitlines():
        m = re.match(pat, line)
        if m:
            try:
                lineno, col = int(m.group("line")), int(m.group("col"))
            except ValueError:
                lineno, col = 1, 1
            msg = m.group("msg")
            diags.append(Diagnostic(m.group("file"), lineno, col, "warning", "RUFF", msg))
    return PylintResult(diags, proc.stdout, proc.returncode)
