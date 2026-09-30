"""OSH engine: embedded interactive shell via PTY (PRD §4.8, M5)."""

from ocode.engines.osh.shell import (
    PROD_PATTERNS,
    ShellSession,
    history_path_for,
    is_production_db,
    shell_command,
)

__all__ = [
    "PROD_PATTERNS",
    "ShellSession",
    "history_path_for",
    "is_production_db",
    "shell_command",
]
