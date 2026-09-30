"""Snippet library: Tab-expandable Odoo boilerplate (FR-OMLS-017)."""

from __future__ import annotations

SNIPPETS: dict[str, dict[str, str]] = {
    "omodel": {
        "label": "Odoo model",
        "languages": "python",
        "body": (
            "from odoo import models, fields, api\n\n\n"
            "class ${1:Name}(models.Model):\n"
            "    _name = '${2:module.name}'\n"
            "    _description = '${3:Description}'\n\n"
            "    name = fields.Char(string='Name', required=True)\n"
        ),
    },
    "ofield": {
        "label": "Odoo field",
        "languages": "python",
        "body": "${1:name} = fields.${2:Char}(string='${3:Label}'${4:, required=True})",
    },
    "ocompute": {
        "label": "Computed field + method",
        "languages": "python",
        "body": (
            "${1:value} = fields.${2:Char}(string='${3:Label}', compute='_compute_${1:value}')\n\n"
            "    @api.depends('${4:dep}')\n"
            "    def _compute_${1:value}(self):\n"
            "        for rec in self:\n"
            "            rec['${1:value}'] = ${5:False}\n"
        ),
    },
    "oonchange": {
        "label": "Onchange method",
        "languages": "python",
        "body": (
            "@api.onchange('${1:field}')\n"
            "    def _onchange_${1:field}(self):\n"
            "        ${2:pass}\n"
        ),
    },
    "oconstraint": {
        "label": "Constraint method",
        "languages": "python",
        "body": (
            "@api.constrains('${1:field}')\n"
            "    def _check_${1:field}(self):\n"
            "        for rec in self:\n"
            "            if ${2:False}:\n"
            "                raise ValidationError(_('${3:Message}'))\n"
        ),
    },
    "oform": {
        "label": "Form view",
        "languages": "xml",
        "body": (
            "<record id=\"${1:view_id}\" model=\"ir.ui.view\">\n"
            "    <field name=\"name\">${2:name}</field>\n"
            "    <field name=\"model\">${3:model}</field>\n"
            "    <field name=\"arch\" type=\"xml\">\n"
            "        <form>\n"
            "            <sheet>\n"
            "                <group>\n"
            "                    <field name=\"${4:name}\"/>\n"
            "                </group>\n"
            "            </sheet>\n"
            "        </form>\n"
            "    </field>\n"
            "</record>\n"
        ),
    },
    "otree": {
        "label": "List view (tree on ≤17)",
        "languages": "xml",
        "body": (
            "<record id=\"${1:view_id}\" model=\"ir.ui.view\">\n"
            "    <field name=\"name\">${2:name}</field>\n"
            "    <field name=\"model\">${3:model}</field>\n"
            "    <field name=\"arch\" type=\"xml\">\n"
            "        <${4:TAG}>\n"
            "            <field name=\"${5:name}\"/>\n"
            "        </${4:TAG}>\n"
            "    </field>\n"
            "</record>\n"
        ),
    },
    "oxpath": {
        "label": "XPath view inheritance",
        "languages": "xml",
        "body": (
            "<record id=\"${1:view_id}\" model=\"ir.ui.view\">\n"
            "    <field name=\"name\">${2:name}</field>\n"
            "    <field name=\"model\">${3:model}</field>\n"
            "    <field name=\"inherit_id\" ref=\"${4:parent.view}\"/>\n"
            "    <field name=\"arch\" type=\"xml\">\n"
            "        <xpath expr=\"//field[@name='${5:anchor}']\" position=\"${6:after}\">\n"
            "            <field name=\"${7:name}\"/>\n"
            "        </xpath>\n"
            "    </field>\n"
            "</record>\n"
        ),
    },
}


def expand_snippet(trigger: str, version: str | None = None) -> str | None:
    """Expand a snippet trigger. `otree` is version-aware (list on 18+)."""
    spec = SNIPPETS.get(trigger)
    if spec is None:
        return None
    body = spec["body"]
    if trigger == "otree":
        major = 0
        try:
            major = int((version or "").split(".")[0])
        except ValueError:
            major = 0
        body = body.replace("${4:TAG}", "list" if major >= 18 else "tree")
    return body


def render_snippet(body: str) -> tuple[str, int]:
    """Replace placeholders with defaults. Returns (text, cursor_offset)."""
    import re as _re

    pat = _re.compile(r"\$\{(\d+):([^}]*)\}|\$\{(\d+)\}|\$0")
    out: list[str] = []
    cursor: int | None = None
    pos = 0
    for m in pat.finditer(body):
        out.append(body[pos : m.start()])
        if m.group(1) is not None:
            default = m.group(2)
            if int(m.group(1)) == 1 and cursor is None:
                cursor = len("".join(out)) + len(default)
            out.append(default)
        pos = m.end()
    out.append(body[pos:])
    text = "".join(out)
    return (text, cursor if cursor is not None else len(text))
