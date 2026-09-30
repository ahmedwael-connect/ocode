"""Stable OKI query API for SMN/OMLS/OSG + plugins (FR-OKI-007)."""

from __future__ import annotations

from ocode.engines.oki.db import OkiDb


class OkiQuery:
    def __init__(self, db: OkiDb) -> None:
        self.db = db

    def models(self) -> list[str]:
        rows = self.db.query("SELECT DISTINCT name FROM models ORDER BY name")
        return [str(r["name"]) for r in rows]

    def model_modules(self, model: str) -> list[str]:
        """Modules defining/extending model, dependency-ordered (base providers first)."""
        rows = self.db.query("SELECT module, kind FROM models WHERE name=?", (model,))
        mods = [(str(r["module"]), str(r["kind"])) for r in rows]
        base = sorted(m for m, k in mods if k == "base")
        ext = sorted(m for m, k in mods if k != "base")
        return base + ext

    def merged_fields(self, model: str) -> dict[str, dict[str, object]]:
        out: dict[str, dict[str, object]] = {}
        for mod in self.model_modules(model):
            rows = self.db.query(
                "SELECT name, ftype, comodel, s, required, file, lineno "
                "FROM fields WHERE model=? AND module=?",
                (model, mod),
            )
            for r in rows:
                out[str(r["name"])] = {
                    "type": str(r["ftype"]),
                    "comodel": str(r["comodel"]),
                    "string": str(r["s"]),
                    "required": bool(r["required"]),
                    "module": mod,
                    "file": str(r["file"]),
                    "lineno": int(r["lineno"]),
                }
        return out

    def methods_of(self, model: str) -> dict[str, dict[str, object]]:
        out: dict[str, dict[str, object]] = {}
        for mod in self.model_modules(model):
            rows = self.db.query(
                "SELECT name, decorators, file, lineno FROM methods WHERE model=? AND module=?",
                (model, mod),
            )
            for r in rows:
                out[str(r["name"])] = {
                    "decorators": str(r["decorators"]),
                    "module": mod,
                    "file": str(r["file"]),
                    "lineno": int(r["lineno"]),
                }
        return out

    def depends_closure(self, module: str) -> set[str]:
        seen: set[str] = {module}
        stack = [module]
        while stack:
            cur = stack.pop()
            row = self.db.query_one("SELECT depends FROM modules WHERE name=?", (cur,))
            if not row:
                continue
            for dep in str(row["depends"]).split(","):
                dep = dep.strip()
                if dep and dep not in seen:
                    seen.add(dep)
                    stack.append(dep)
        return seen

    def module_names(self) -> list[str]:
        return [str(r["name"]) for r in self.db.query("SELECT name FROM modules ORDER BY name")]

    def xmlid_exists(self, xmlid: str) -> bool:
        if "." in xmlid:
            mod, bare = xmlid.split(".", 1)
            row = self.db.query_one("SELECT 1 FROM xmlids WHERE xmlid=? AND module=?", (bare, mod))
            return row is not None
        return self.db.query_one("SELECT 1 FROM xmlids WHERE xmlid=?", (xmlid,)) is not None

    def duplicate_xmlids(self) -> list[str]:
        rows = self.db.query(
            "SELECT xmlid, COUNT(DISTINCT module) c FROM xmlids GROUP BY xmlid HAVING c > 1"
        )
        return [str(r["xmlid"]) for r in rows]

    def views_for_model(self, model: str) -> list[dict[str, object]]:
        rows = self.db.query(
            "SELECT xmlid, module, inherit_id, fields, file FROM views WHERE model=?",
            (model,),
        )
        out: list[dict[str, object]] = []
        for r in rows:
            fields = str(r["fields"]).split(",") if r["fields"] else []
            out.append({
                "xmlid": str(r["xmlid"]),
                "module": str(r["module"]),
                "inherit_id": str(r["inherit_id"]),
                "fields": fields,
                "file": str(r["file"]),
            })
        return out

    def acls_for_model_xmlid(self, model_xmlid: str) -> list[dict[str, object]]:
        rows = self.db.query(
            "SELECT name, module, group_xmlid, file, lineno FROM acls "
            "WHERE model_xmlid=?",
            (model_xmlid,),
        )
        return [dict(r) for r in rows]

    def stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for table in ("modules", "models", "fields", "methods", "xmlids", "views", "files"):
            row = self.db.query_one(f"SELECT COUNT(*) c FROM {table}")
            out[table] = int(row["c"]) if row else 0
        return out
