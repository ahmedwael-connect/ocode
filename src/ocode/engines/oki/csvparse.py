"""CSV parsing: ir.model.access rows + generic id columns."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass


@dataclass
class AccessRow:
    name: str
    model: str  # technical model name (resolved from model_id:id when possible)
    model_xmlid: str = ""
    group_xmlid: str = ""
    perm_read: str = "1"
    perm_write: str = "0"
    perm_create: str = "0"
    perm_unlink: str = "0"
    lineno: int = 0


def parse_access_csv(source: str) -> tuple[list[str], list[AccessRow]]:
    """Return (header, rows). Empty header on parse failure."""
    try:
        reader = csv.DictReader(io.StringIO(source))
        header = list(reader.fieldnames or [])
    except (csv.Error, ValueError):
        return ([], [])
    rows: list[AccessRow] = []
    lineno = 1  # header
    for record in reader:
        lineno += 1
        try:
            get = record.get
        except AttributeError:
            continue
        model_ref = (get("model_id:id") or get("model_id") or "").strip()
        model = ""
        if "." in model_ref and "_" in model_ref:
            model = model_ref.split(".")[-1].replace("_", ".")
        # model xmlids look like model_sale_order; dotted names need model map,
        # so resolution happens in the indexer; keep raw too
        rows.append(
            AccessRow(
                name=(get("id") or "") + "",
                model=model,
                model_xmlid=model_ref,
                group_xmlid=(get("group_id:id") or get("group_id") or "").strip(),
                perm_read=(get("perm_read") or "1").strip() or "1",
                perm_write=(get("perm_write") or "0").strip() or "0",
                perm_create=(get("perm_create") or "0").strip() or "0",
                perm_unlink=(get("perm_unlink") or "0").strip() or "0",
                lineno=lineno,
            )
        )
    return (header, rows)


ACCESS_HEADER = [
    "id", "name", "model_id:id", "group_id:id",
    "perm_read", "perm_write", "perm_create", "perm_unlink",
]
