"""UI widgets package (M1 editor + M2 tree + M3 logs + M4 complete/problems + M5 shell)."""

from ocode.ui.widgets.complete import CompletionAccepted, CompletionPopup
from ocode.ui.widgets.editor import OcodeEditor
from ocode.ui.widgets.findbar import FindBar
from ocode.ui.widgets.logpanel import LogLinkClicked, LogPanel
from ocode.ui.widgets.problems import ProblemChosen, ProblemsPanel
from ocode.ui.widgets.proj_tree import FilePicked, OdooTree
from ocode.ui.widgets.shell import ShellExited, ShellPanel

__all__ = [
    "CompletionAccepted",
    "CompletionPopup",
    "FilePicked",
    "FindBar",
    "LogLinkClicked",
    "LogPanel",
    "OcodeEditor",
    "OdooTree",
    "ProblemChosen",
    "ProblemsPanel",
    "ShellExited",
    "ShellPanel",
]
