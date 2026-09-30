"""High-level scaffolds: specs → planned changes (FR-OSG-001..008)."""

from __future__ import annotations

from pathlib import Path

from ocode.engines.omls.quickfix import apply_fix
from ocode.engines.osg.access import ensure_access_csv
from ocode.engines.osg.applier import PlannedChange, plan_ensure_contains, plan_file
from ocode.engines.osg.naming import (
    class_name_for,
    file_stem_for,
    model_name_for,
    xml_id_for,
)
from ocode.engines.osg.render import render_template, version_ctx
from ocode.engines.osg.specs import (
    AccessSpec,
    ControllerSpec,
    CronSpec,
    ModelSpec,
    ModuleSpec,
    ReportSpec,
    TestSpec,
    ViewSpec,
    WizardSpec,
    XpathSpec,
)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError:
        return ""


def scaffold_module(
    base: Path, spec: ModuleSpec, data_files: list[str] | None = None
) -> list[PlannedChange]:
    errs = spec.errors()
    if errs:
        raise ValueError("; ".join(errs))
    root = base / spec.technical
    ctx: dict[str, object] = {
        "display": spec.display, "technical": spec.technical, "version": spec.version,
        "depends": spec.depends, "category": spec.category, "license": spec.license,
        "author": spec.author, "website": spec.website, "summary": spec.summary,
        "data_files": data_files or [],
    }
    changes: list[PlannedChange] = []
    manifest = render_template("module_manifest", ctx)
    init = render_template("module_init", ctx)
    for rel, text in (
        ("__manifest__.py", manifest),
        ("__init__.py", init),
        ("models/__init__.py", ""),
        ("views/.gitkeep", ""),
        ("security/ir.model.access.csv",
         "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"),
        ("data/.gitkeep", ""),
        ("tests/__init__.py", "from . import test_module\n"),
        ("tests/test_module.py", render_template("test", {
            "module": spec.technical, "model": "res.partner", "class_name": "TestModule"})),
        ("controllers/__init__.py", ""),
        ("wizard/__init__.py", ""),
        ("report/.gitkeep", ""),
        ("i18n/.gitkeep", ""),
        ("static/description/.gitkeep", ""),
    ):
        planned = plan_file(root / rel, text, f"new module {spec.technical}")
        if planned is not None:
            changes.append(planned)
    return changes


def scaffold_model(
    module_dir: Path, spec: ModelSpec, version: str | None = None,
    methods: list[str] | None = None,
) -> list[PlannedChange]:
    errs = spec.errors()
    if errs:
        raise ValueError("; ".join(errs))
    name = spec.name or model_name_for(spec.module, spec.display or "Item")
    stem = file_stem_for(name)
    changes: list[PlannedChange] = []
    if spec.inherit:
        # inherited extension (FR-OSG-003)
        body = render_template("model_extension", {
            "class_name": class_name_for(stem),
            "inherit": spec.inherit,
            "fields": [f.__dict__ for f in spec.fields],
            "methods": [{"name": m} for m in (methods or [])],
            **version_ctx(version),
        })
    else:
        use_api = any(f.compute for f in spec.fields) or bool(spec.mixins)
        body = render_template("model", {
            "class_name": class_name_for(stem),
            "name": name, "description": spec.description or name,
            "order": spec.order, "rec_name": spec.rec_name,
            "mixins": [m for m in spec.mixins if m not in ("", "models.Model")],
            "fields": [f.__dict__ for f in spec.fields],
            "use_api": use_api,
            **version_ctx(version),
        })
    model_file = module_dir / "models" / f"{stem}.py"
    planned = plan_file(model_file, body, f"model {name}")
    if planned is not None:
        changes.append(planned)
    # models/__init__.py (idempotent)
    init_path = module_dir / "models" / "__init__.py"
    old_init = _read(init_path)
    new_init, _ = apply_fix("init-import", old_init or "", stem)
    if new_init != old_init:
        changes.append(PlannedChange(init_path, "create" if not old_init else "overwrite",
                                     new_init, f"import {stem}", old_init))
    # access rows for new models (not extensions)
    if not spec.inherit:
        access_path = module_dir / "security" / "ir.model.access.csv"
        new_csv, changed = ensure_access_csv(
            _read(access_path), name, spec.module, ["user", "manager"]
        )
        if changed or not access_path.exists():
            action = "create" if not access_path.exists() else "overwrite"
            changes.append(PlannedChange(access_path, action, new_csv, f"access for {name}",
                                         _read(access_path)))
    return changes


def scaffold_view(
    module_dir: Path, spec: ViewSpec, fields: list[str], version: str | None = None,
) -> list[PlannedChange]:
    errs = spec.errors()
    if errs:
        raise ValueError("; ".join(errs))
    major = (version or "").split(".")[0]
    kinds = [k if k != "tree" or major < "18" else "list" for k in spec.kinds]
    kinds = sorted(set(kinds))
    stem = file_stem_for(spec.model)
    prefix = xml_id_for(spec.module, stem)
    view_mode = ",".join(kinds)
    body = render_template("view", {
        "model": spec.model, "module": spec.module, "kinds": kinds,
        "xml_prefix": prefix, "view_name": spec.view_name or spec.model,
        "fields": [{"name": f} for f in fields],
        "with_action": spec.with_action, "with_menu": spec.with_menu,
        "view_mode": view_mode, "list_tag": version_ctx(version)["list_tag"],
        **version_ctx(version),
    })
    out = module_dir / "views" / f"{stem}_views.xml"
    changes: list[PlannedChange] = []
    planned = plan_file(out, body, f"views for {spec.model}")
    if planned is not None:
        changes.append(planned)
    changes.extend(_ensure_manifest_data(module_dir, f"views/{stem}_views.xml"))
    return changes


def scaffold_xpath(module_dir: Path, spec: XpathSpec) -> list[PlannedChange]:
    errs = spec.errors()
    if errs:
        raise ValueError("; ".join(errs))
    xml_id = xml_id_for(spec.module, file_stem_for(spec.model), "inherit")
    body = render_template("xpath", {
        "xml_id": xml_id, "view_name": spec.view_name or xml_id,
        "model": spec.model, "parent_ref": spec.parent_ref,
        "anchor": spec.anchor, "position": spec.position, "field": spec.field,
    })
    out = module_dir / "views" / f"{file_stem_for(spec.model)}_inherit.xml"
    changes: list[PlannedChange] = []
    if out.exists():
        old = _read(out)
        marker = f'id="{xml_id}"'
        if marker not in old:
            # append second record before </odoo>
            addition = body.split("<odoo>", 1)[1].rsplit("</odoo>", 1)[0]
            new_text = old.replace("</odoo>", addition + "</odoo>")
            changes.append(PlannedChange(out, "overwrite", new_text, f"xpath {xml_id}", old))
    else:
        planned = plan_file(out, body, f"xpath {xml_id}")
        if planned is not None:
            changes.append(planned)
    changes.extend(_ensure_manifest_data(module_dir, f"views/{out.name}"))
    return changes


def scaffold_access(module_dir: Path, spec: AccessSpec) -> list[PlannedChange]:
    errs = spec.errors()
    if errs:
        raise ValueError("; ".join(errs))
    access_path = module_dir / "security" / "ir.model.access.csv"
    new_csv, changed = ensure_access_csv(_read(access_path), spec.model, spec.module, spec.groups)
    changes: list[PlannedChange] = []
    if changed or not access_path.exists():
        action = "create" if not access_path.exists() else "overwrite"
        changes.append(PlannedChange(access_path, action, new_csv, f"access for {spec.model}",
                                     _read(access_path)))
    changes.extend(_ensure_manifest_data(module_dir, "security/ir.model.access.csv"))
    return changes


def scaffold_security_groups(module_dir: Path, module: str) -> list[PlannedChange]:
    body = render_template("security_groups", {"module": module})
    out = module_dir / "security" / f"{module}_groups.xml"
    changes: list[PlannedChange] = []
    planned = plan_file(out, body, "security groups")
    if planned is not None:
        changes.append(planned)
    changes.extend(_ensure_manifest_data(module_dir, f"security/{module}_groups.xml"))
    return changes


def scaffold_record_rule(
    module_dir: Path, model: str, module: str, name: str, group_xmlid: str,
) -> list[PlannedChange]:
    xml_id = xml_id_for(module, file_stem_for(model), "rule")
    model_xmlid = f"model_{module}_{file_stem_for(model)}"
    body = render_template("record_rule", {
        "xml_id": xml_id, "name": name, "model_xmlid": model_xmlid, "group_xmlid": group_xmlid,
    })
    out = module_dir / "security" / "ir.rule.xml"
    changes: list[PlannedChange] = []
    planned = plan_file(out, body, f"rule {name}")
    if planned is not None:
        changes.append(planned)
    changes.extend(_ensure_manifest_data(module_dir, "security/ir.rule.xml"))
    return changes


def scaffold_wizard(module_dir: Path, spec: WizardSpec) -> list[PlannedChange]:
    errs = spec.errors()
    if errs:
        raise ValueError("; ".join(errs))
    stem = file_stem_for(spec.name)
    body = render_template("wizard", {
        "class_name": class_name_for(stem), "name": spec.name,
        "description": spec.description or spec.name,
    })
    out = module_dir / "wizard" / f"{stem}.py"
    changes: list[PlannedChange] = []
    planned = plan_file(out, body, f"wizard {spec.name}")
    if planned is not None:
        changes.append(planned)
    init_path = module_dir / "wizard" / "__init__.py"
    old_init = _read(init_path)
    new_init, _ = apply_fix("init-import", old_init or "", stem)
    if new_init != old_init:
        changes.append(PlannedChange(init_path, "create" if not old_init else "overwrite",
                                     new_init, f"import {stem}", old_init))
    return changes


def scaffold_report(module_dir: Path, spec: ReportSpec) -> list[PlannedChange]:
    errs = spec.errors()
    if errs:
        raise ValueError("; ".join(errs))
    stem = file_stem_for(spec.name)
    template_id = xml_id_for(spec.module, stem, "document")
    body = render_template("report", {
        "template_id": template_id, "template_ref": f"{spec.module}.{template_id}",
        "report_id": xml_id_for(spec.module, stem, "report"),
        "name": spec.name, "description": spec.description,
        "model": spec.model,
    })
    out = module_dir / "report" / f"{stem}.xml"
    changes: list[PlannedChange] = []
    planned = plan_file(out, body, f"report {spec.name}")
    if planned is not None:
        changes.append(planned)
    changes.extend(_ensure_manifest_data(module_dir, f"report/{stem}.xml"))
    return changes


def scaffold_controller(module_dir: Path, spec: ControllerSpec) -> list[PlannedChange]:
    errs = spec.errors()
    if errs:
        raise ValueError("; ".join(errs))
    body = render_template("controller", {
        "class_name": class_name_for(spec.module), "route": spec.route,
        "auth": spec.auth, "module": spec.module,
    })
    out = module_dir / "controllers" / "main.py"
    changes: list[PlannedChange] = []
    planned = plan_file(out, body, "controller")
    if planned is not None:
        changes.append(planned)
    return changes


def scaffold_cron(module_dir: Path, spec: CronSpec) -> list[PlannedChange]:
    errs = spec.errors()
    if errs:
        raise ValueError("; ".join(errs))
    xml_id = xml_id_for(spec.module, file_stem_for(spec.name), "cron")
    model_xmlid = f"model_{spec.module}_{file_stem_for(spec.model)}"
    body = render_template("cron", {
        "xml_id": xml_id, "name": spec.name, "model_xmlid": model_xmlid,
        "code": spec.code, "interval_number": spec.interval_number,
        "interval_type": spec.interval_type,
    })
    out = module_dir / "data" / "cron.xml"
    changes: list[PlannedChange] = []
    planned = plan_file(out, body, f"cron {spec.name}")
    if planned is not None:
        changes.append(planned)
    changes.extend(_ensure_manifest_data(module_dir, "data/cron.xml"))
    return changes


def scaffold_test(module_dir: Path, spec: TestSpec) -> list[PlannedChange]:
    errs = spec.errors()
    if errs:
        raise ValueError("; ".join(errs))
    body = render_template("test", {
        "class_name": spec.class_name, "model": spec.model, "module": spec.module,
    })
    out = module_dir / "tests" / f"test_{file_stem_for(spec.model)}.py"
    changes: list[PlannedChange] = []
    planned = plan_file(out, body, "test")
    if planned is not None:
        changes.append(planned)
    init_path = module_dir / "tests" / "__init__.py"
    stem = f"test_{file_stem_for(spec.model)}"
    change = plan_ensure_contains(init_path, f"from . import {stem}", "test import")
    if change is not None:
        changes.append(change)
    return changes


def _ensure_manifest_data(module_dir: Path, rel: str) -> list[PlannedChange]:
    manifest = module_dir / "__manifest__.py"
    if not manifest.exists():
        return []
    old = _read(manifest)
    new_text, applied = apply_fix("manifest-data", old, rel)
    if applied and new_text != old:
        return [PlannedChange(manifest, "overwrite", new_text, f"manifest += {rel}", old)]
    return []
