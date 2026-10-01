"""DB tools: list/select/drop/duplicate/backup via psql/pg_dump (FR-OSS-026, M7).

Passwords travel via PGPASSWORD in the child env only — never in argv,
logs, or previews.
"""

from __future__ import annotations

import configparser
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class DatabaseError(Exception):
    pass


@dataclass
class DbConf:
    host: str = ""
    port: str = ""
    user: str = ""
    password: str = ""
    maintenance_db: str = "postgres"
    psql: str = "psql"
    pg_dump: str = "pg_dump"


def pg_binaries_available(conf: DbConf | None = None) -> tuple[bool, str]:
    which_psql = shutil.which(conf.psql if conf else "psql")
    which_dump = shutil.which(conf.pg_dump if conf else "pg_dump")
    if which_psql is None:
        return (False, "psql not found (apt install postgresql-client)")
    if which_dump is None:
        return (False, "pg_dump not found (apt install postgresql-client)")
    return (True, "")


def db_conf_from_odoo_conf(conf_path: str | Path) -> DbConf:
    parser = configparser.ConfigParser()
    try:
        parser.read(str(conf_path), encoding="utf-8")
    except (OSError, configparser.Error) as exc:
        raise DatabaseError(f"cannot read {conf_path}: {exc}") from exc

    def g(key: str) -> str:
        try:
            if parser.has_section("options"):
                return parser.get("options", key, fallback="")
            return ""
        except configparser.Error:
            return ""

    return DbConf(
        host=g("db_host"), port=g("db_port"),
        user=g("db_user") or g("dbuser"), password=g("db_password"),
    )


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _base_args(conf: DbConf, dbname: str) -> list[str]:
    args = [conf.psql, "-tAX", "-d", dbname]
    if conf.host:
        args += ["-h", conf.host]
    if conf.port:
        args += ["-p", conf.port]
    if conf.user:
        args += ["-U", conf.user]
    return args


def _env(conf: DbConf) -> dict[str, str]:
    env = dict(os.environ)
    if conf.password:
        env["PGPASSWORD"] = conf.password
    return env


def _run(args: list[str], conf: DbConf, timeout: int = 60) -> str:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              env=_env(conf))
    except FileNotFoundError as exc:
        raise DatabaseError(f"{args[0]} not found (apt install postgresql-client)") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise DatabaseError(str(exc)) from exc
    if proc.returncode != 0:
        # scrub any accidental secret leakage (defensive; we never pass any)
        raise DatabaseError(proc.stderr.strip()[:300] or f"exit {proc.returncode}")
    return proc.stdout


def list_databases(conf: DbConf) -> list[str]:
    out = _run(
        _base_args(conf, conf.maintenance_db) + ["-c", "SELECT datname FROM pg_database;"],
        conf,
    )
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def database_size(conf: DbConf, db: str) -> str:
    out = _run(
        _base_args(conf, conf.maintenance_db)
        + ["-c", f"SELECT pg_size_pretty(pg_database_size({quote_ident(db)}));"],
        conf,
    )
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return lines[0] if lines else "?"


def _terminate_backends(conf: DbConf, db: str) -> None:
    _run(
        _base_args(conf, conf.maintenance_db) + ["-c",
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = {quote_literal(db)} AND pid <> pg_backend_pid();"],
        conf,
    )


def drop_database(conf: DbConf, db: str) -> None:
    _terminate_backends(conf, db)
    _run(_base_args(conf, conf.maintenance_db) + ["-c", f"DROP DATABASE {quote_ident(db)};"], conf)


def duplicate_database(conf: DbConf, src: str, dst: str) -> None:
    _terminate_backends(conf, src)
    _run(
        _base_args(conf, conf.maintenance_db)
        + ["-c", f"CREATE DATABASE {quote_ident(dst)} TEMPLATE {quote_ident(src)};"],
        conf,
    )


def backup_database(conf: DbConf, db: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    args = [conf.pg_dump, "-Fc", "-f", str(dest), db]
    if conf.host:
        args += ["-h", conf.host]
    if conf.port:
        args += ["-p", conf.port]
    if conf.user:
        args += ["-U", conf.user]
    _run(args, conf, timeout=600)
    return dest
