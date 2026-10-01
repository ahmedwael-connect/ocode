"""OSS engine: Odoo server control + logs (PRD §4.5, M3)."""

from ocode.engines.oss.dbtools import (
    DatabaseError,
    DbConf,
    backup_database,
    database_size,
    db_conf_from_odoo_conf,
    drop_database,
    duplicate_database,
    list_databases,
    pg_binaries_available,
)
from ocode.engines.oss.docker import (
    ComposeProject,
    LogStream,
    detect_compose,
    docker_available,
    exec_update,
    service_action,
)
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
    "ComposeProject",
    "DatabaseError",
    "DbConf",
    "FLAG_CATALOG",
    "FailureHint",
    "FlagSpec",
    "LogBuffer",
    "LogFilter",
    "LogRecord",
    "LogStream",
    "LogTailer",
    "ManagedProc",
    "ProcResult",
    "ServerManager",
    "ServerProfile",
    "ServerStatus",
    "TraceBlock",
    "backup_database",
    "build_args",
    "database_size",
    "db_conf_from_odoo_conf",
    "default_profile",
    "detect_compose",
    "detect_failure",
    "docker_available",
    "drop_database",
    "duplicate_database",
    "exec_update",
    "extract_file_links",
    "group_tracebacks",
    "list_databases",
    "load_profiles",
    "parse_odoo_line",
    "pg_binaries_available",
    "preview_command",
    "save_profiles",
    "service_action",
    "validate_flags",
]
