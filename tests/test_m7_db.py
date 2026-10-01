"""M7 dbtools tests: conf parsing, quoting, stub-backed ops."""

from __future__ import annotations

import os
from pathlib import Path

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
    quote_ident,
    quote_literal,
)


def make_stubs(base: Path) -> Path:
    bindir = base / "bin"
    bindir.mkdir()
    log = base / "calls.log"
    psql = bindir / "psql"
    psql.write_text(
        "#!/bin/bash\n"
        f'echo "$@" >> "{log}"\n'
        'case "$*" in\n'
        "  *pg_size_pretty*) echo '42 MB' ;;\n"
        "  *pg_database*) printf 'mydb\\ntestdb\\npostgres\\n' ;;\n"
        "  *FAILME*) echo 'boom' >&2; exit 1 ;;\n"
        "  *) echo '' ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    psql.chmod(0o755)
    dump = bindir / "pg_dump"
    dump.write_text('#!/bin/bash\necho "DUMP" > "$DUMP_DEST"\n', encoding="utf-8")
    dump.chmod(0o755)
    return bindir


def test_quoting() -> None:
    assert quote_ident('a"b') == '"a""b"'
    assert quote_literal("o'h") == "'o''h'"
    # injection attempt stays inside one identifier
    assert quote_ident('x"; DROP DATABASE y; --') == '"x""; DROP DATABASE y; --"'


def test_conf_parse(tmp_path: Path) -> None:
    conf = tmp_path / "odoo.conf"
    conf.write_text("[options]\ndb_host = h\ndb_port = 5433\ndb_user = u\ndb_password = s\n",
                    encoding="utf-8")
    parsed = db_conf_from_odoo_conf(conf)
    assert (parsed.host, parsed.port, parsed.user, parsed.password) == ("h", "5433", "u", "s")


def test_list_and_size(tmp_path: Path) -> None:
    bindir = make_stubs(tmp_path)
    conf = DbConf(psql=str(bindir / "psql"))
    assert list_databases(conf) == ["mydb", "testdb", "postgres"]
    assert database_size(conf, "mydb") == "42 MB"


def test_duplicate_drop_quoted(tmp_path: Path) -> None:
    bindir = make_stubs(tmp_path)
    conf = DbConf(psql=str(bindir / "psql"))
    duplicate_database(conf, "my db", 'evil"; DROP--')
    drop_database(conf, "my db")
    log = (tmp_path / "calls.log").read_text(encoding="utf-8")
    assert 'CREATE DATABASE "evil""; DROP--"' in log
    assert 'DROP DATABASE "my db"' in log


def test_backup_writes_file(tmp_path: Path, monkeypatch: object) -> None:
    bindir = make_stubs(tmp_path)
    dest = tmp_path / "out" / "mydb.dump"
    monkeypatch.setenv("DUMP_DEST", str(dest))
    conf = DbConf(pg_dump=str(bindir / "pg_dump"))
    assert backup_database(conf, "mydb", dest) == dest
    assert dest.read_text(encoding="utf-8").strip() == "DUMP"


def test_errors() -> None:
    conf = DbConf(psql="/nonexistent/psql-xyz")
    try:
        list_databases(conf)
    except DatabaseError as exc:
        assert "psql" in str(exc)
    else:
        raise AssertionError("expected DatabaseError")
    ok, hint = pg_binaries_available(DbConf(psql="/nonexistent/psql-xyz"))
    assert not ok and hint
    os.environ.pop("XX", None)
