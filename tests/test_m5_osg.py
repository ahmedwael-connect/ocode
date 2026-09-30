"""M5 OSG tests: naming, templates, scaffolds, access idempotency, applier safety."""

from __future__ import annotations

from pathlib import Path

from ocode.engines.osg.access import ensure_access_csv
from ocode.engines.osg.applier import apply_changes, plan_file, preview_diff
from ocode.engines.osg.naming import (
    class_name_for,
    file_stem_for,
    model_name_for,
    technical_name_for,
    xml_id_for,
)
from ocode.engines.osg.render import render_template
from ocode.engines.osg.scaffold import (
    scaffold_access,
    scaffold_controller,
    scaffold_cron,
    scaffold_model,
    scaffold_module,
    scaffold_report,
    scaffold_security_groups,
    scaffold_test,
    scaffold_view,
    scaffold_wizard,
    scaffold_xpath,
)
from ocode.engines.osg.specs import (
    AccessSpec,
    ControllerSpec,
    CronSpec,
    FieldSpec,
    ModelSpec,
    ModuleSpec,
    ReportSpec,
    TestSpec,
    ViewSpec,
    WizardSpec,
    XpathSpec,
)


def test_naming() -> None:
    assert technical_name_for("Sale Custom") == "sale_custom"
    assert class_name_for("sale.order") == "SaleOrder"
    assert model_name_for("sale_custom", "Orders") == "sale_custom.order"
    assert file_stem_for("sale.order") == "sale_order"
    assert xml_id_for("sale_custom", "sale_order", "form") == "sale_custom_sale_order_form"


def test_model_template_renders() -> None:
    body = render_template("model", {
        "class_name": "SaleOrder", "name": "sale.order", "description": "Sale",
        "order": "", "rec_name": "", "mixins": ["mail.thread"],
        "fields": [{"name": "x", "ftype": "Char", "comodel": "", "string": "X",
                    "required": True, "compute": "", "related": "", "help": ""}],
        "use_api": False,
    })
    assert "_name = 'sale.order'" in body
    assert "mail.thread" in body
    assert "required=True" in body


def test_scaffold_module_tree(tmp_path: Path) -> None:
    changes = scaffold_module(tmp_path, ModuleSpec(display="Sale Custom", author="Me"))
    paths = [c.path.relative_to(tmp_path).as_posix() for c in changes]
    assert "sale_custom/__manifest__.py" in paths
    assert "sale_custom/security/ir.model.access.csv" in paths
    assert "sale_custom/tests/test_module.py" in paths
    written = apply_changes(changes)
    assert len(written) == len(changes)
    # second run → no changes (idempotent-ish for creates)
    again = scaffold_module(tmp_path, ModuleSpec(display="Sale Custom", author="Me"))
    assert again == []


def test_scaffold_model_full(tmp_path: Path) -> None:
    mod = tmp_path / "sale_custom"
    (mod / "models").mkdir(parents=True)
    (mod / "__manifest__.py").write_text("{'name': 'C', 'data': []}", encoding="utf-8")
    spec = ModelSpec(display="Order", module="sale_custom", description="Order",
                     mixins=["mail.thread"],
                     fields=[FieldSpec("name", "Char", "Name", True),
                             FieldSpec("partner_id", "Many2one", "Partner", False, "res.partner")])
    changes = scaffold_model(mod, spec, version="17.0")
    created = [c for c in changes if c.action == "create"]
    assert any("sale_custom" in str(c.path) for c in created)
    assert any("access" in str(c.path) for c in changes)
    apply_changes(changes)
    model_file = mod / "models" / "sale_custom_order.py"
    assert model_file.is_file()
    assert "_inherit = ['mail.thread']" in model_file.read_text(encoding="utf-8")
    init_text = (mod / "models" / "__init__.py").read_text(encoding="utf-8")
    assert "from . import sale_custom_order" in init_text


def test_scaffold_model_extension(tmp_path: Path) -> None:
    mod = tmp_path / "m"
    (mod / "models").mkdir(parents=True)
    spec = ModelSpec(display="X", module="m", inherit="sale.order",
                     fields=[FieldSpec("x", "Char", "X")])
    changes = scaffold_model(mod, spec, version="17.0", methods=["action_confirm"])
    apply_changes(changes)
    text = next(c.new_text for c in changes if c.path.suffix == ".py")
    assert "_inherit = 'sale.order'" in text
    assert "super().action_confirm()" in text


def test_scaffold_view_manifest_update(tmp_path: Path) -> None:
    mod = tmp_path / "m"
    (mod / "views").mkdir(parents=True)
    (mod / "__manifest__.py").write_text("{'name': 'M', 'data': []}", encoding="utf-8")
    spec = ViewSpec(model="m.item", module="m", kinds=["form", "list"])
    changes = scaffold_view(mod, spec, ["name"], version="18.0")
    apply_changes(changes)
    xml = (mod / "views" / "m_item_views.xml").read_text(encoding="utf-8")
    assert "<list>" in xml and "<form>" in xml and "ir.actions.act_window" in xml
    assert "views/m_item_views.xml" in (mod / "__manifest__.py").read_text(encoding="utf-8")
    # 16.0 keeps tree
    mod2 = tmp_path / "m2"
    (mod2 / "views").mkdir(parents=True)
    (mod2 / "__manifest__.py").write_text("{'name': 'M2', 'data': []}", encoding="utf-8")
    apply_changes(scaffold_view(mod2, spec, ["name"], version="16.0"))
    assert "<tree>" in (mod2 / "views" / "m_item_views.xml").read_text(encoding="utf-8")


def test_scaffold_xpath_access_groups(tmp_path: Path) -> None:
    mod = tmp_path / "m"
    (mod / "views").mkdir(parents=True)
    (mod / "__manifest__.py").write_text("{'name': 'M', 'data': []}", encoding="utf-8")
    xs = XpathSpec(parent_ref="sale.view_order_form", model="sale.order",
                   module="m", anchor="name", position="after", field="x")
    apply_changes(scaffold_xpath(mod, xs))
    assert "inherit_id" in (mod / "views" / "sale_order_inherit.xml").read_text(encoding="utf-8")
    apply_changes(scaffold_access(mod, AccessSpec("sale.order", "m", ["user"])))
    csv_text = (mod / "security" / "ir.model.access.csv").read_text(encoding="utf-8")
    assert "model_m_sale_order" in csv_text
    apply_changes(scaffold_security_groups(mod, "m"))
    assert "res.groups" in (mod / "security" / "m_groups.xml").read_text(encoding="utf-8")


def test_access_idempotent() -> None:
    first, changed = ensure_access_csv("", "sale.order", "m", ["user", "manager"])
    assert changed and first.count("\n") == 3  # header + 2 rows
    second, changed2 = ensure_access_csv(first, "sale.order", "m", ["user", "manager"])
    assert not changed2 and second == first
    custom, _ = ensure_access_csv(first + "# custom line\n", "sale.order", "m", ["user"])
    assert "# custom line" in custom


def test_applier_never_silent_overwrite(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("old", encoding="utf-8")
    change = plan_file(f, "new", "demo")
    assert change is not None and change.action == "overwrite"
    assert "old" in preview_diff(change) and "new" in preview_diff(change)
    assert apply_changes([change], allow_overwrite=False) == []
    assert f.read_text(encoding="utf-8") == "old"
    assert apply_changes([change], allow_overwrite=True) == [f]


def test_more_scaffolds(tmp_path: Path) -> None:
    mod = tmp_path / "m"
    for d in ("wizard", "report", "controllers", "data", "tests"):
        (mod / d).mkdir(parents=True)
    (mod / "__manifest__.py").write_text("{'name': 'M', 'data': []}", encoding="utf-8")
    apply_changes(scaffold_wizard(mod, WizardSpec("m.wizard", "m", "Wiz")))
    assert (mod / "wizard" / "m_wizard.py").is_file()
    apply_changes(scaffold_report(mod, ReportSpec("m.report", "m", "sale.order", "R")))
    assert (mod / "report" / "m_report.xml").is_file()
    apply_changes(scaffold_controller(mod, ControllerSpec("m", "/m/hello", "user")))
    assert "http.route" in (mod / "controllers" / "main.py").read_text(encoding="utf-8")
    apply_changes(scaffold_cron(mod, CronSpec("m.cron", "m", "sale.order")))
    assert "ir.cron" in (mod / "data" / "cron.xml").read_text(encoding="utf-8")
    apply_changes(scaffold_test(mod, TestSpec("m", "sale.order")))
    assert "TransactionCase" in (mod / "tests" / "test_sale_order.py").read_text(encoding="utf-8")
