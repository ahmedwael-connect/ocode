"""Odoo CLI flag catalog (FR-OSS-021/022): grouped, typed, version-aware."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FlagSpec:
    name: str  # e.g. --db-filter or -d
    group: str  # database|http|logging|dev|testing|workers|i18n|advanced
    kind: str  # flag (bool) | value | multi (repeatable) | csv
    help: str = ""
    default: str = ""
    versions: tuple[str, ...] = ()
    example: str = ""


V_ALL = ("14.0", "15.0", "16.0", "17.0", "18.0")

FLAG_CATALOG: tuple[FlagSpec, ...] = (
    FlagSpec("-c", "database", "value", "Odoo config file", versions=V_ALL,
             example="-c /etc/odoo.conf"),
    FlagSpec("-d", "database", "value", "Database name", versions=V_ALL,
             example="-d mydb"),
    FlagSpec("-i", "database", "csv", "Install modules (comma list)", versions=V_ALL,
             example="-i sale_custom"),
    FlagSpec("-u", "database", "csv", "Update modules (list, or 'all')", versions=V_ALL,
             example="-u sale_custom"),
    FlagSpec("--addons-path", "database", "value", "Comma-separated addons paths",
             versions=V_ALL),
    FlagSpec("--db-filter", "database", "value", "Regex filter for databases",
             versions=V_ALL),
    FlagSpec("--data-dir", "database", "value", "Data directory", versions=V_ALL),
    FlagSpec("--without-demo", "database", "value", "Disable demo data", versions=V_ALL),
    FlagSpec("--stop-after-init", "database", "flag", "Stop after init (one-shot)",
             versions=V_ALL),
    FlagSpec("--http-port", "http", "value", "HTTP port", default="8069",
             versions=V_ALL),
    FlagSpec("--longpolling-port", "http", "value", "Longpolling port (<=15)",
             versions=("14.0", "15.0")),
    FlagSpec("--gevent-port", "http", "value", "Geven port (>=16 rename)",
             versions=("16.0", "17.0", "18.0")),
    FlagSpec("--workers", "workers", "value", "Workers (0 = threaded)", default="0",
             versions=V_ALL),
    FlagSpec("--max-cron-threads", "workers", "value", "Cron threads", default="2",
             versions=V_ALL),
    FlagSpec("--limit-time-cpu", "workers", "value", "CPU time limit per request",
             versions=V_ALL),
    FlagSpec("--limit-time-real", "workers", "value", "Wall time limit per request",
             versions=V_ALL),
    FlagSpec("--log-level", "logging", "value", "Log level", default="info",
             versions=V_ALL),
    FlagSpec("--log-handler", "logging", "multi", "Logger:LEVEL pairs (repeatable)",
             versions=V_ALL, example="--log-handler odoo.addons.sale:DEBUG"),
    FlagSpec("--logfile", "logging", "value", "Log file path", versions=V_ALL),
    FlagSpec("--dev", "dev", "value", "Dev features: reload,qweb,xml,werkzeug",
             versions=V_ALL, example="--dev=reload,qweb,xml"),
    FlagSpec("-l", "i18n", "value", "Load language code", versions=V_ALL),
    FlagSpec("--load-language", "i18n", "value", "Load language on init",
             versions=V_ALL),
    FlagSpec("--test-enable", "testing", "flag", "Enable tests", versions=V_ALL),
    FlagSpec("--test-tags", "testing", "value", "Test tags selector", versions=V_ALL,
             example="--test-tags /sale_custom"),
    FlagSpec("--save", "advanced", "flag", "Save config to file", versions=V_ALL),
)

_BY_NAME: dict[str, FlagSpec] = {f.name: f for f in FLAG_CATALOG}


def flag_spec(name: str) -> FlagSpec | None:
    return _BY_NAME.get(name)


def validate_flags(flags: list[str], version: str | None = None) -> list[str]:
    """Return warnings for unknown flags or version mismatches (no raise)."""
    warnings: list[str] = []
    for fl in flags:
        name = fl.split("=", 1)[0].strip()
        spec = _BY_NAME.get(name)
        if spec is None:
            # allow free-form extra args starting with - (warn only)
            if name.startswith("-"):
                warnings.append(f"unknown flag: {name}")
            continue
        if version and spec.versions and version not in spec.versions:
            major = version.split(".")[0]
            if not any(v.split(".")[0] == major for v in spec.versions):
                warnings.append(f"{name} may not apply to Odoo {version}")
    return warnings


def build_args(
    odoo_bin: str,
    python: str | None,
    conf: str | None,
    db: str | None,
    extra_flags: list[str],
    update: list[str] | None = None,
    install: list[str] | None = None,
    stop_after_init: bool = False,
) -> tuple[str, list[str]]:
    """Return (program, argv) with arg list (no shell)."""
    prog = python or odoo_bin
    argv: list[str] = []
    if python:
        argv = [odoo_bin]
    if conf:
        argv += ["-c", conf]
    if db:
        argv += ["-d", db]
    if install:
        argv += ["-i", ",".join(install)]
    if update:
        argv += ["-u", ",".join(update)]
    argv += list(extra_flags)
    if stop_after_init and "--stop-after-init" not in argv:
        argv.append("--stop-after-init")
    return (prog, argv)


def preview_command(prog: str, argv: list[str]) -> str:
    import shlex

    return " ".join(shlex.quote(a) for a in [prog, *argv])
