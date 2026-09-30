"""Jinja2 rendering with user-overridable templates (FR-OSG-010)."""

from __future__ import annotations

from pathlib import Path

from jinja2 import BaseLoader, Environment


def user_template_dir() -> Path:
    return Path.home() / ".config" / "ocode" / "templates"


def bundled_template_dir() -> Path:
    return Path(__file__).parent.parent.parent / "templates"


def template_names() -> list[str]:
    names: set[str] = set()
    for d in (bundled_template_dir(), user_template_dir()):
        try:
            for p in d.glob("*.j2"):
                names.add(p.stem)
        except OSError:
            continue
    return sorted(names)


def _load_source(name: str) -> str:
    user = user_template_dir() / f"{name}.j2"
    if user.is_file():
        return user.read_text(encoding="utf-8")
    bundled = bundled_template_dir() / f"{name}.j2"
    return bundled.read_text(encoding="utf-8")


def render_template(name: str, context: dict[str, object]) -> str:
    env = Environment(loader=BaseLoader(), keep_trailing_newline=True)
    template = env.from_string(_load_source(name))
    return template.render(**context)


def version_ctx(version: str | None) -> dict[str, object]:
    major = 0
    try:
        major = int((version or "").split(".")[0])
    except ValueError:
        major = 0
    return {
        "odoo_version": version or "",
        "odoo_major": major,
        "list_tag": "list" if major >= 18 else "tree",
    }
