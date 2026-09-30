"""SQLite index store (FR-OKI-001/006). Safe to delete; rebuild via Indexer."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import cast


def state_cache_dir() -> Path:
    return Path.home() / ".cache" / "ocode" / "index"


def index_path_for(workspace: Path) -> Path:
    digest = hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()[:16]
    d = state_cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{workspace.name}-{digest}.sqlite"


SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
  path TEXT PRIMARY KEY, module TEXT, mtime REAL, hash TEXT, lang TEXT);
CREATE TABLE IF NOT EXISTS modules(
  name TEXT PRIMARY KEY, path TEXT, depends TEXT, version TEXT);
CREATE TABLE IF NOT EXISTS models(
  name TEXT, module TEXT, kind TEXT, file TEXT, lineno INTEGER,
  PRIMARY KEY(name, module));
CREATE TABLE IF NOT EXISTS fields(
  model TEXT, name TEXT, module TEXT, ftype TEXT, comodel TEXT, s TEXT,
  required INTEGER, file TEXT, lineno INTEGER,
  PRIMARY KEY(model, name, module));
CREATE TABLE IF NOT EXISTS methods(
  model TEXT, name TEXT, module TEXT, decorators TEXT, file TEXT,
  lineno INTEGER, PRIMARY KEY(model, name, module));
CREATE TABLE IF NOT EXISTS xmlids(
  xmlid TEXT, module TEXT, kind TEXT, model TEXT, file TEXT, lineno INTEGER,
  PRIMARY KEY(xmlid, module));
CREATE TABLE IF NOT EXISTS views(
  xmlid TEXT, module TEXT, model TEXT, inherit_id TEXT, fields TEXT,
  refs TEXT, file TEXT, PRIMARY KEY(xmlid, module));
CREATE TABLE IF NOT EXISTS acls(
  name TEXT, module TEXT, model_xmlid TEXT, group_xmlid TEXT, perms TEXT,
  file TEXT, lineno INTEGER);
CREATE INDEX IF NOT EXISTS idx_fields_model ON fields(model);
CREATE INDEX IF NOT EXISTS idx_methods_model ON methods(model);
CREATE INDEX IF NOT EXISTS idx_xmlids_id ON xmlids(xmlid);
CREATE INDEX IF NOT EXISTS idx_views_model ON views(model);
"""


class OkiDb:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:
            pass

    def file_hash(self, path: str) -> str | None:
        cur = self.conn.execute("SELECT hash FROM files WHERE path=?", (path,))
        row = cur.fetchone()
        return str(row["hash"]) if row else None

    def upsert_file(self, path: str, module: str, mtime: float, digest: str, lang: str) -> None:
        self.conn.execute(
            "INSERT INTO files(path, module, mtime, hash, lang) VALUES(?,?,?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET module=excluded.module, "
            "mtime=excluded.mtime, hash=excluded.hash, lang=excluded.lang",
            (path, module, mtime, digest, lang),
        )

    def clear_file(self, path: str) -> None:
        for table in ("models", "fields", "methods", "xmlids", "views", "acls"):
            self.conn.execute(f"DELETE FROM {table} WHERE file=?", (path,))

    def commit(self) -> None:
        self.conn.commit()

    def query(self, sql: str, args: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, args).fetchall())

    def query_one(self, sql: str, args: tuple[object, ...] = ()) -> sqlite3.Row | None:
        row = self.conn.execute(sql, args).fetchone()
        return cast("sqlite3.Row | None", row)
