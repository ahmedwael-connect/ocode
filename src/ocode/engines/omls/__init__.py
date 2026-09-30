"""OMLS engine: diagnostics, completion, lint, quick-fixes (PRD §4.4, M4)."""

from ocode.engines.omls.complete import Completion, complete_at
from ocode.engines.omls.diagnostics import Diagnostic, FileCtx, analyze_file, analyze_module
from ocode.engines.omls.pylint import PylintResult, pylint_available, run_pylint_odoo, run_ruff
from ocode.engines.omls.quickfix import apply_fix, available_fixes
from ocode.engines.omls.snippets import SNIPPETS, expand_snippet, render_snippet

__all__ = [
    "SNIPPETS",
    "Completion",
    "Diagnostic",
    "FileCtx",
    "PylintResult",
    "analyze_file",
    "analyze_module",
    "apply_fix",
    "available_fixes",
    "complete_at",
    "expand_snippet",
    "pylint_available",
    "render_snippet",
    "run_pylint_odoo",
    "run_ruff",
]
