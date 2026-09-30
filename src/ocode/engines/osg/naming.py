"""Naming helpers: OCA/Odoo conventions from a single input (FR-OSG-011)."""

from __future__ import annotations

import re


def technical_name_for(display: str) -> str:
    """'Sale Custom' → 'sale_custom'. Lowercase, non-alnum → underscore."""
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", display.strip().lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    if slug and slug[0].isdigit():
        slug = "m_" + slug
    return slug or "my_module"


def class_name_for(name: str) -> str:
    """'sale.order' or 'sale_order' → 'SaleOrder'."""
    parts = re.split(r"[._\s-]+", name.strip())
    out = "".join(p[:1].upper() + p[1:] for p in parts if p)
    return out or "MyModel"


def model_name_for(module: str, name: str) -> str:
    """Module + short name → dotted _name ('sale_custom','Orders' → 'sale_custom.order')."""
    short = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip().lower()).strip("_")
    short = re.sub(r"_+", "_", short).rstrip("s") or "item"
    # naive singularize common plurals (orders → order)
    if short.endswith("ies"):
        short = short[:-3] + "y"
    elif short.endswith("ses"):
        short = short[:-2]
    elif short.endswith("s") and not short.endswith("ss"):
        short = short[:-1]
    return f"{technical_name_for(module)}.{short}"


def file_stem_for(model: str) -> str:
    """'sale.order' → 'sale_order'."""
    return model.replace(".", "_")


def xml_id_for(module: str, *parts: str) -> str:
    segs = [technical_name_for(p) for p in parts if p]
    return f"{technical_name_for(module)}_{'_'.join(segs)}"
