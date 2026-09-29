"""OSS engine: Odoo server control + logs (PRD §4.5, M3)."""

from ocode.engines.oss.failure import FailureHint, detect_failure
from ocode.engines.oss.flags import (
    FLAG_CATALOG,
    FlagSpec,
    build_args,
    preview_command,
    validate_flags,
)
from ocode.engines.oss.logs import (
    LogBuffer,
    LogFilter,
    LogRecord,
    TraceBlock,
    extract_file_links,
    group_tracebacks,
    parse_odoo_line,
)
from ocode.engines.oss.manager import ServerManager, ServerStatus
from ocode.engines.oss.process import ManagedProc, ProcResult
from ocode.engines.oss.profiles import ServerProfile, default_profile, load_profiles, save_profiles
from ocode.engines.oss.tailer import LogTailer

__all__ = [
    "FLAG_CATALOG",
    "FailureHint",
    "FlagSpec",
    "LogBuffer",
    "LogFilter",
    "LogRecord",
    "LogTailer",
    "ManagedProc",
    "ProcResult",
    "ServerManager",
    "ServerProfile",
    "ServerStatus",
    "TraceBlock",
    "build_args",
    "default_profile",
    "detect_failure",
    "extract_file_links",
    "group_tracebacks",
    "load_profiles",
    "parse_odoo_line",
    "preview_command",
    "save_profiles",
    "validate_flags",
]
