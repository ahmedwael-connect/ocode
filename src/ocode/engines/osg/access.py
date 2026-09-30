"""Access-rights automation: idempotent CSV updates (FR-OSG-006)."""

from __future__ import annotations

from ocode.engines.oki.csvparse import ACCESS_HEADER


def access_rows_for(model: str, module: str, groups: list[str]) -> list[str]:
    base = f"access_{model.replace('.', '_')}"
    xmlid = f"model_{module}_{model.replace('.', '_')}"
    rows: list[str] = []
    if "user" in groups:
        g = f"{module}.group_{module}_user"
        rows.append(f"{base}_user,{model} user,{xmlid},{g},1,0,0,0")
    if "manager" in groups:
        g = f"{module}.group_{module}_manager"
        rows.append(f"{base}_manager,{model} manager,{xmlid},{g},1,1,1,1")
    extra = [g for g in groups if g not in ("user", "manager")]
    for g in extra:
        rows.append(f"{base}_{g},{model} {g},{xmlid},{g},1,1,0,0")
    return rows


def ensure_access_csv(
    existing: str, model: str, module: str, groups: list[str]
) -> tuple[str, bool]:
    """Add missing standard rows. Creates header when absent. Idempotent."""
    lines = existing.splitlines() if existing.strip() else []
    if not lines:
        lines = [",".join(ACCESS_HEADER)]
    elif lines[0].strip() != ",".join(ACCESS_HEADER):
        # unknown format: leave untouched
        return (existing, False)
    wanted = access_rows_for(model, module, groups)
    have = set(lines)
    missing = [r for r in wanted if r not in have]
    if not missing:
        return ("\n".join(lines) + "\n" if lines else "", False)
    # drop exact-duplicate base ids (regenerate): keep custom lines intact
    return ("\n".join(lines + missing) + "\n", True)
