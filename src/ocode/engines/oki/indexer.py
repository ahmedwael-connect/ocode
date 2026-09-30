"""Background indexer: walk modules, hash-gated parse, bulk upsert (FR-OKI-001..004)."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ocode.engines.oki.csvparse import parse_access_csv
from ocode.engines.oki.db import OkiDb
from ocode.engines.oki.pyparse import parse_python
from ocode.engines.oki.xmlparse import parse_xml
from ocode.engines.opd.module import ModuleInfo, manifest_str, manifest_str_list, read_manifest

INDEXABLE_EXTS = {".py", ".xml", ".csv"}
SKIP_DIRS = {"__pycache__", ".git", "node_modules", "static", "i18n"}


@dataclass
class IndexStats:
    modules: int = 0
    files: int = 0
    skipped_unchanged: int = 0
    models: int = 0
    fields: int = 0
    xmlids: int = 0
    errors: int = 0
    elapsed: float = 0.0


def file_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Indexer:
    def __init__(self, db: OkiDb, modules: list[ModuleInfo]) -> None:
        self.db = db
        self.modules = modules
        self.by_path: dict[str, ModuleInfo] = {str(m.path): m for m in modules}

    def module_for(self, path: Path) -> ModuleInfo | None:
        best: ModuleInfo | None = None
        best_len = -1
        sp = str(path)
        for mp, mod in self.by_path.items():
            if sp == mp or sp.startswith(mp.rstrip("/") + "/"):
                if len(mp) > best_len:
                    best, best_len = mod, len(mp)
        return best

    def build(self, progress: Callable[[int, int], None] | None = None) -> IndexStats:
        stats = IndexStats(modules=len(self.modules))
        t0 = time.time()
        # modules table first (dep graph for resolution)
        for mod in self.modules:
            data = read_manifest(mod.manifest_path)
            deps = ",".join(manifest_str_list(data, "depends"))
            ver = manifest_str(data, "version")
            self.db.conn.execute(
                "INSERT INTO modules(name, path, depends, version) VALUES(?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET path=excluded.path, "
                "depends=excluded.depends, version=excluded.version",
                (mod.name, str(mod.path), deps, ver),
            )
        self.db.commit()
        # collect files
        targets: list[tuple[Path, ModuleInfo]] = []
        for mod in self.modules:
            try:
                it = mod.path.rglob("*")
            except OSError:
                continue
            for f in it:
                try:
                    if not f.is_file() or f.suffix not in INDEXABLE_EXTS:
                        continue
                    if any(part in SKIP_DIRS for part in f.parts[-4:-1]):
                        continue
                except OSError:
                    continue
                targets.append((f, mod))
        total = len(targets)
        for i, (f, mod) in enumerate(targets):
            if progress and i % 50 == 0:
                progress(i, total)
            try:
                raw = f.read_bytes()
            except OSError:
                stats.errors += 1
                continue
            digest = file_digest(raw)
            sp = str(f)
            if self.db.file_hash(sp) == digest:
                stats.skipped_unchanged += 1
                continue
            try:
                mtime = f.stat().st_mtime
            except OSError:
                mtime = 0.0
            try:
                text = raw.decode("utf-8", errors="ignore")
            except OSError:
                stats.errors += 1
                continue
            self.db.clear_file(sp)
            lang = f.suffix.lstrip(".")
            self.db.upsert_file(sp, mod.name, mtime, digest, lang)
            try:
                if f.suffix == ".py":
                    n = self._index_py(sp, mod.name, text)
                    stats.models += n[0]
                    stats.fields += n[1]
                elif f.suffix == ".xml":
                    stats.xmlids += self._index_xml(sp, mod.name, text)
                elif f.suffix == ".csv" and f.name == "ir.model.access.csv":
                    self._index_access(sp, mod.name, text)
                stats.files += 1
            except OSError:
                stats.errors += 1
        self.db.commit()
        if progress:
            progress(total, total)
        stats.elapsed = time.time() - t0
        return stats

    def _index_py(self, path: str, module: str, text: str) -> tuple[int, int]:
        info = parse_python(text)
        nm = nf = 0
        for cls in info.classes:
            if not cls.odoo_base and not cls.model_name and not cls.inherit:
                continue
            names = [cls.model_name] if cls.model_name else []
            names += [inh for inh in cls.inherit if "." in inh]
            for model in names:
                kind = "base" if cls.model_name else "extension"
                self.db.conn.execute(
                    "INSERT INTO models(name, module, kind, file, lineno) "
                    "VALUES(?,?,?,?,?) "
                    "ON CONFLICT(name, module) DO UPDATE SET kind=excluded.kind, "
                    "file=excluded.file, lineno=excluded.lineno",
                    (model, module, kind, path, cls.lineno),
                )
                nm += 1
                for fld in cls.fields:
                    self.db.conn.execute(
                        "INSERT INTO fields("
                        "model, name, module, ftype, comodel, s, required, file, lineno"
                        ") VALUES(?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(model, name, module) DO UPDATE SET "
                        "ftype=excluded.ftype, comodel=excluded.comodel, "
                        "s=excluded.s, required=excluded.required, "
                        "file=excluded.file, lineno=excluded.lineno",
                        (
                            model, fld.name, module, fld.ftype, fld.comodel,
                            fld.string, int(fld.required), path, fld.lineno,
                        ),
                    )
                    nf += 1
                for m in cls.methods:
                    self.db.conn.execute(
                        "INSERT INTO methods(model, name, module, decorators, file, lineno) "
                        "VALUES(?,?,?,?,?,?) "
                        "ON CONFLICT(model, name, module) DO UPDATE SET "
                        "decorators=excluded.decorators, "
                        "file=excluded.file, lineno=excluded.lineno",
                        (model, m.name, module, ",".join(m.decorators), path, m.lineno),
                    )
        return (nm, nf)

    def _index_xml(self, path: str, module: str, text: str) -> int:
        info = parse_xml(text)
        n = 0
        for x in info.xmlids:
            self.db.conn.execute(
                "INSERT INTO xmlids(xmlid, module, kind, model, file, lineno) "
                "VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(xmlid, module) DO UPDATE SET kind=excluded.kind, "
                "model=excluded.model, file=excluded.file, lineno=excluded.lineno",
                (x.xmlid, module, x.kind, x.model, path, x.lineno),
            )
            n += 1
        for v in info.views:
            self.db.conn.execute(
                "INSERT INTO views(xmlid, module, model, inherit_id, fields, refs, file) "
                "VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(xmlid, module) DO UPDATE SET model=excluded.model, "
                "inherit_id=excluded.inherit_id, fields=excluded.fields, "
                "refs=excluded.refs, file=excluded.file",
                (
                    v.xmlid, module, v.model, v.inherit_id,
                    ",".join(v.fields), ",".join(v.refs), path,
                ),
            )
        return n

    def _index_access(self, path: str, module: str, text: str) -> None:
        _, rows = parse_access_csv(text)
        for r in rows:
            perms = f"{r.perm_read}{r.perm_write}{r.perm_create}{r.perm_unlink}"
            self.db.conn.execute(
                "INSERT INTO acls(name, module, model_xmlid, group_xmlid, perms, file, lineno) "
                "VALUES(?,?,?,?,?,?,?)",
                (r.name, module, r.model_xmlid, r.group_xmlid, perms, path, r.lineno),
            )

    def update_file(self, path: Path) -> bool:
        mod = self.module_for(path)
        if mod is None or path.suffix not in INDEXABLE_EXTS:
            return False
        try:
            raw = path.read_bytes()
        except OSError:
            # deleted → drop rows
            self.db.clear_file(str(path))
            self.db.conn.execute("DELETE FROM files WHERE path=?", (str(path),))
            self.db.commit()
            return True
        digest = file_digest(raw)
        if self.db.file_hash(str(path)) == digest:
            return False
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        text = raw.decode("utf-8", errors="ignore")
        self.db.clear_file(str(path))
        self.db.upsert_file(str(path), mod.name, mtime, digest, path.suffix.lstrip("."))
        if path.suffix == ".py":
            self._index_py(str(path), mod.name, text)
        elif path.suffix == ".xml":
            self._index_xml(str(path), mod.name, text)
        elif path.suffix == ".csv" and path.name == "ir.model.access.csv":
            self._index_access(str(path), mod.name, text)
        self.db.commit()
        return True

    def prune_missing(self) -> int:
        rows = self.db.query("SELECT path FROM files")
        n = 0
        for row in rows:
            if not Path(str(row["path"])).exists():
                self.db.clear_file(str(row["path"]))
                self.db.conn.execute("DELETE FROM files WHERE path=?", (str(row["path"]),))
                n += 1
        if n:
            self.db.commit()
        return n
