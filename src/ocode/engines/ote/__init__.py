"""OTE engine package (PRD §4.6, M1)."""

from ocode.engines.ote.buffer import PieceTable
from ocode.engines.ote.cursor import CursorSet, Position, Selection
from ocode.engines.ote.document import Document
from ocode.engines.ote.highlight import detect_language, highlight_lines
from ocode.engines.ote.history import EditOp, UndoStack
from ocode.engines.ote.search import FindOptions, SearchEngine
from ocode.engines.ote.session import SwapManager
from ocode.engines.ote.state import EditorState
from ocode.engines.ote.tabs import TabState

__all__ = [
    "CursorSet",
    "Document",
    "EditOp",
    "EditorState",
    "FindOptions",
    "PieceTable",
    "Position",
    "SearchEngine",
    "Selection",
    "SwapManager",
    "TabState",
    "UndoStack",
    "detect_language",
    "highlight_lines",
]
