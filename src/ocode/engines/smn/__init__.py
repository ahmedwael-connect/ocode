"""SMN engine: smart module navigation + search models (PRD §4.3, M2)."""

from ocode.engines.smn.model import (
    VIRTUAL_GROUPS,
    ModuleNode,
    build_module_nodes,
    iter_files,
    should_ignore,
)
from ocode.engines.smn.related import cycle_related, key_file, related_files
from ocode.engines.smn.search import (
    ContentHit,
    content_search_sync,
    parse_quickopen_query,
    quick_open,
    rg_available,
)

__all__ = [
    "VIRTUAL_GROUPS",
    "ContentHit",
    "ModuleNode",
    "build_module_nodes",
    "content_search_sync",
    "cycle_related",
    "iter_files",
    "key_file",
    "parse_quickopen_query",
    "quick_open",
    "related_files",
    "rg_available",
    "should_ignore",
]
