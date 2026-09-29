"""UI widgets package (M1 editor + M2 tree + M3 logs)."""

from ocode.ui.widgets.editor import OcodeEditor
from ocode.ui.widgets.findbar import FindBar
from ocode.ui.widgets.logpanel import LogLinkClicked, LogPanel
from ocode.ui.widgets.proj_tree import FilePicked, OdooTree

__all__ = ["FilePicked", "FindBar", "LogLinkClicked", "LogPanel", "OcodeEditor", "OdooTree"]
