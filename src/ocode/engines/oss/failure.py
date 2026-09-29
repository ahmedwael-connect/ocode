"""Failure-cause detection with jump links (FR-OSS-010)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ocode.engines.oss.logs import extract_file_links


@dataclass
class FailureHint:
    kind: str  # port_in_use | db_missing | traceback | module_error | unknown
    summary: str
    links: list[tuple[str, int]] = field(default_factory=list)


def detect_failure(output: str) -> FailureHint | None:
    low = output.lower()
    if "address already in use" in low or "port" in low and "already in use" in low:
        return FailureHint("port_in_use", "Port already in use — another Odoo/server holds it.")
    missing = ("does not exist" in low or "missing" in low or "could not connect" in low)
    if "database" in low and missing:
        return FailureHint("db_missing", "Database missing or unreachable — check db_name.")
    if "traceback (most recent call last)" in low:
        links = extract_file_links(output)
        last_err = ""
        for line in reversed(output.splitlines()):
            if line.strip() and "error" in line.lower():
                last_err = line.strip()[:200]
                break
        return FailureHint("traceback", last_err or "Python traceback at startup.", links)
    mod_missing = "not found" in low or "no module named" in low
    mod_missing = mod_missing or "failed to load" in low
    if "module" in low and mod_missing:
        links = extract_file_links(output)
        return FailureHint("module_error", "Module load error — check manifest.", links)
    if "psycopg2" in low or "operationalerror" in low:
        return FailureHint("db_missing", "PostgreSQL connection failed.", [])
    return None
