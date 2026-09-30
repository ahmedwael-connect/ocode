"""Generator screens: form-driven scaffolds with live preview (FR-OSG-001..008)."""

from __future__ import annotations

from pathlib import Path

from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Checkbox, Input, Select, Static

from ocode.engines.osg.applier import PlannedChange
from ocode.engines.osg.scaffold import (
    scaffold_access,
    scaffold_controller,
    scaffold_cron,
    scaffold_model,
    scaffold_module,
    scaffold_record_rule,
    scaffold_report,
    scaffold_security_groups,
    scaffold_test,
    scaffold_view,
    scaffold_wizard,
    scaffold_xpath,
)
from ocode.engines.osg.specs import (
    FieldSpec,
    ModelSpec,
    ModuleSpec,
    ViewSpec,
)


def parse_fields_spec(text: str) -> list[FieldSpec]:
    """'name:Char:Label:required, partner:Many2one:Partner:comodel=res.partner'."""
    out: list[FieldSpec] = []
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = [p.strip() for p in chunk.split(":")]
        name = parts[0]
        ftype = parts[1] if len(parts) > 1 and parts[1] else "Char"
        label = parts[2] if len(parts) > 2 else ""
        spec = FieldSpec(name=name, ftype=ftype, string=label)
        for extra in parts[3:]:
            if extra == "required":
                spec.required = True
            elif extra.startswith("comodel="):
                spec.comodel = extra.split("=", 1)[1]
            elif extra.startswith("compute="):
                spec.compute = extra.split("=", 1)[1]
            elif extra.startswith("related="):
                spec.related = extra.split("=", 1)[1]
        out.append(spec)
    return out


class DiffScreen(ModalScreen[bool]):
    """Preview diffs before applying (FR-OSG-009). Y=apply, N/Esc=cancel."""

    def __init__(self, title: str, diffs: str, has_overwrite: bool) -> None:
        super().__init__()
        self._title = title
        self._diffs = diffs
        self._has_overwrite = has_overwrite

    def compose(self) -> ComposeResult:
        warn = "  ⚠ overwrites existing files" if self._has_overwrite else ""
        yield Static(f"{self._title}{warn}")
        yield Static(self._diffs[:6000] or "(no changes)", id="diff-body")
        yield Static("Y=apply, N/Esc=cancel")

    async def on_key(self, event: events.Key) -> None:
        if event.key in ("y", "Y"):
            self.dismiss(True)
        elif event.key in ("n", "N", "escape"):
            self.dismiss(False)


class _BaseGen(ModalScreen[list[PlannedChange] | None]):
    title = "Generate"

    def compose(self) -> ComposeResult:
        yield Static(f"{self.title} (Enter=plan, Esc=cancel)")
        yield from self.fields()
        yield Static("", id="gen-preview")

    def fields(self) -> ComposeResult:
        yield Static("")

    def val(self, wid: str) -> str:
        try:
            return self.query_one(f"#{wid}", Input).value.strip()
        except Exception:
            return ""

    def checked(self, wid: str) -> bool:
        try:
            return bool(self.query_one(f"#{wid}", Checkbox).value)
        except Exception:
            return False

    def selected(self, wid: str, default: str = "") -> str:
        try:
            v = self.query_one(f"#{wid}", Select).value
            return str(v) if v else default
        except Exception:
            return default

    def build(self) -> list[PlannedChange]:
        raise NotImplementedError

    def on_mount(self) -> None:
        self._refresh()
        try:
            self.query_one("Input").focus()
        except Exception:
            pass

    def _refresh(self) -> None:
        try:
            preview = self.query_one("#gen-preview", Static)
        except Exception:
            return
        try:
            changes = self.build()
        except ValueError as exc:
            preview.update(f"⚠ {exc}")
            return
        if not changes:
            preview.update("(no changes — files already up to date)")
            return
        lines = [f"{c.action:9} {c.path.name}  {c.detail}" for c in changes[:15]]
        if len(changes) > 15:
            lines.append(f"… +{len(changes) - 15} more")
        preview.update("\n".join(lines))

    def on_input_changed(self, event: Input.Changed) -> None:
        _ = event
        self._refresh()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        _ = event
        try:
            self.dismiss(self.build())
        except ValueError:
            pass

    async def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)


class NewModuleScreen(_BaseGen):
    title = "New Module (FR-OSG-001)"

    def __init__(self, version: str = "17.0.1.0") -> None:
        super().__init__()
        self._version = version

    def fields(self) -> ComposeResult:
        yield Input(placeholder="Display name (e.g. Sale Custom)", id="f-display")
        yield Input(placeholder="Depends (comma, e.g. base,sale)", value="base", id="f-depends")
        yield Input(placeholder="Author", id="f-author")
        yield Input(placeholder="Category", value="Custom", id="f-category")

    def build(self) -> list[PlannedChange]:
        from ocode.engines.osg.naming import technical_name_for

        display = self.val("f-display") or "My Module"
        depends = [d.strip() for d in self.val("f-depends").split(",") if d.strip()] or ["base"]
        spec = ModuleSpec(display=display, technical=technical_name_for(display),
                          version=self._version, depends=depends,
                          category=self.val("f-category") or "Custom",
                          author=self.val("f-author"))
        # base dir resolved by app via callback context; use cwd placeholder replaced by app
        return scaffold_module(Path.cwd(), spec)


class ModelScreen(_BaseGen):
    title = "New Model (FR-OSG-002)"

    def __init__(self, module: str = "", version: str = "17.0") -> None:
        super().__init__()
        self._module = module
        self._version = version

    def fields(self) -> ComposeResult:
        yield Input(placeholder="Label (e.g. Order)", id="f-display")
        yield Input(placeholder="_name override (optional)", id="f-name")
        yield Input(placeholder="Description", id="f-desc")
        yield Input(placeholder="Mixins (comma: mail.thread)", id="f-mixins")
        yield Input(placeholder="Fields: name:Char:Label:required, ...", id="f-fields")

    def build(self) -> list[PlannedChange]:
        from ocode.engines.osg.naming import model_name_for

        module = self.val("f-module") or self._module
        display = self.val("f-display") or "Item"
        spec = ModelSpec(
            name=self.val("f-name") or model_name_for(module, display),
            display=display, module=module, description=self.val("f-desc"),
            mixins=[m.strip() for m in self.val("f-mixins").split(",") if m.strip()],
            fields=parse_fields_spec(self.val("f-fields")),
        )
        return scaffold_model(Path.cwd() / "__PENDING__", spec, self._version)

    def val(self, wid: str) -> str:
        if wid == "f-module":
            return self._module
        return super().val(wid)


class InheritModelScreen(_BaseGen):
    title = "Extend Model (FR-OSG-003)"

    def __init__(self, module: str = "", models: list[str] | None = None) -> None:
        super().__init__()
        self._module = module
        self._models = models or []

    def fields(self) -> ComposeResult:
        yield Input(placeholder="Model to extend (e.g. sale.order)", id="f-inherit")
        yield Input(placeholder="New fields (spec format)", id="f-fields")
        yield Input(placeholder="Override methods (comma)", id="f-methods")

    def build(self) -> list[PlannedChange]:
        spec = ModelSpec(display="Extension", module=self._module,
                         inherit=self.val("f-inherit"),
                         fields=parse_fields_spec(self.val("f-fields")))
        methods = [m.strip() for m in self.val("f-methods").split(",") if m.strip()]
        return scaffold_model(Path.cwd() / "__PENDING__", spec, None, methods)


class ViewScreen(_BaseGen):
    title = "New Views + Action + Menu (FR-OSG-004)"

    def __init__(self, module: str = "", model: str = "", version: str = "17.0") -> None:
        super().__init__()
        self._module = module
        self._model = model
        self._version = version

    def fields(self) -> ComposeResult:
        yield Input(placeholder="Model (e.g. sale_custom.order)", value=self._model, id="f-model")
        yield Input(placeholder="Fields (comma)", id="f-fields")
        yield Checkbox("form", value=True, id="k-form")
        yield Checkbox("list", value=True, id="k-list")
        yield Checkbox("search", value=True, id="k-search")
        yield Checkbox("kanban", value=False, id="k-kanban")
        yield Checkbox("action + menu", value=True, id="k-action")

    def build(self) -> list[PlannedChange]:
        kinds = [k for k in ("form", "list", "search", "kanban") if self.checked(f"k-{k}")]
        spec = ViewSpec(model=self.val("f-model") or self._model, module=self._module,
                        kinds=kinds or ["form"], with_action=self.checked("k-action"),
                        with_menu=self.checked("k-action"))
        fields = [f.strip() for f in self.val("f-fields").split(",") if f.strip()] or ["name"]
        return scaffold_view(Path.cwd() / "__PENDING__", spec, fields, self._version)


class XpathScreen(_BaseGen):
    title = "XPath View Inheritance (FR-OSG-005)"

    def __init__(self, module: str = "", model: str = "") -> None:
        super().__init__()
        self._module = module
        self._model = model

    def fields(self) -> ComposeResult:
        yield Input(placeholder="Parent view ref (module.xml_id)", id="f-parent")
        yield Input(placeholder="Model", value=self._model, id="f-model")
        yield Input(placeholder="Anchor field", value="name", id="f-anchor")
        yield Select([(p, p) for p in ("after", "before", "inside", "replace", "attributes")],
                     value="after", id="f-pos")
        yield Input(placeholder="Field to insert", id="f-field")

    def build(self) -> list[PlannedChange]:
        from ocode.engines.osg.specs import XpathSpec as _XS

        spec = _XS(parent_ref=self.val("f-parent"), model=self.val("f-model") or self._model,
                   module=self._module, anchor=self.val("f-anchor") or "name",
                   position=self.selected("f-pos", "after"), field=self.val("f-field") or "x")
        return scaffold_xpath(Path.cwd() / "__PENDING__", spec)


class AccessScreen(_BaseGen):
    title = "Access Rights (FR-OSG-006)"

    def __init__(self, module: str = "", model: str = "") -> None:
        super().__init__()
        self._module = module
        self._model = model

    def fields(self) -> ComposeResult:
        yield Input(placeholder="Model", value=self._model, id="f-model")
        yield Input(placeholder="Groups (comma: user,manager)", value="user,manager", id="f-groups")

    def build(self) -> list[PlannedChange]:
        from ocode.engines.osg.specs import AccessSpec as _AS

        groups = [g.strip() for g in self.val("f-groups").split(",") if g.strip()]
        spec = _AS(model=self.val("f-model") or self._model, module=self._module, groups=groups)
        return scaffold_access(Path.cwd() / "__PENDING__", spec)


class WizardScreen(_BaseGen):
    title = "Wizard (TransientModel)"

    def __init__(self, module: str = "") -> None:
        super().__init__()
        self._module = module

    def fields(self) -> ComposeResult:
        yield Input(placeholder="_name (e.g. my_module.wizard)", id="f-name")
        yield Input(placeholder="Description", id="f-desc")

    def build(self) -> list[PlannedChange]:
        from ocode.engines.osg.specs import WizardSpec as _WS

        spec = _WS(name=self.val("f-name"), module=self._module, description=self.val("f-desc"))
        return scaffold_wizard(Path.cwd() / "__PENDING__", spec)


class ReportScreen(_BaseGen):
    title = "QWeb Report"

    def __init__(self, module: str = "", model: str = "") -> None:
        super().__init__()
        self._module = module
        self._model = model

    def fields(self) -> ComposeResult:
        yield Input(placeholder="Report name", id="f-name")
        yield Input(placeholder="Model", value=self._model, id="f-model")

    def build(self) -> list[PlannedChange]:
        from ocode.engines.osg.specs import ReportSpec as _RS

        spec = _RS(name=self.val("f-name"), module=self._module,
                   model=self.val("f-model") or self._model)
        return scaffold_report(Path.cwd() / "__PENDING__", spec)


class ControllerScreen(_BaseGen):
    title = "Controller"

    def __init__(self, module: str = "") -> None:
        super().__init__()
        self._module = module

    def fields(self) -> ComposeResult:
        yield Input(placeholder="Route (e.g. /my_module/hello)", id="f-route")
        yield Select([(a, a) for a in ("user", "public", "none")], value="user", id="f-auth")

    def build(self) -> list[PlannedChange]:
        from ocode.engines.osg.specs import ControllerSpec as _CS

        spec = _CS(module=self._module, route=self.val("f-route") or "/",
                   auth=self.selected("f-auth", "user"))
        return scaffold_controller(Path.cwd() / "__PENDING__", spec)


class CronScreen(_BaseGen):
    title = "Cron Job"

    def __init__(self, module: str = "", model: str = "") -> None:
        super().__init__()
        self._module = module
        self._model = model

    def fields(self) -> ComposeResult:
        yield Input(placeholder="Name", id="f-name")
        yield Input(placeholder="Model", value=self._model, id="f-model")

    def build(self) -> list[PlannedChange]:
        from ocode.engines.osg.specs import CronSpec as _CS

        spec = _CS(name=self.val("f-name"), module=self._module,
                   model=self.val("f-model") or self._model)
        return scaffold_cron(Path.cwd() / "__PENDING__", spec)


class TestScreen(_BaseGen):
    title = "Test Case"

    def __init__(self, module: str = "", model: str = "") -> None:
        super().__init__()
        self._module = module
        self._model = model

    def fields(self) -> ComposeResult:
        yield Input(placeholder="Model", value=self._model, id="f-model")

    def build(self) -> list[PlannedChange]:
        from ocode.engines.osg.specs import CaseSpec as _TS

        spec = _TS(module=self._module, model=self.val("f-model") or self._model)
        return scaffold_test(Path.cwd() / "__PENDING__", spec)


class GroupsScreen(_BaseGen):
    title = "Security Groups + Rule (FR-OSG-007)"

    def __init__(self, module: str = "", model: str = "") -> None:
        super().__init__()
        self._module = module
        self._model = model

    def fields(self) -> ComposeResult:
        yield Input(placeholder="Model", value=self._model, id="f-model")
        yield Input(placeholder="Rule name", id="f-rule")
        yield Input(placeholder="Group xmlid (module.group_x_user)", id="f-group")

    def build(self) -> list[PlannedChange]:

        base = Path.cwd() / "__PENDING__"
        out = scaffold_security_groups(base, self._module)
        if self.val("f-rule"):
            out += scaffold_record_rule(
                base, self.val("f-model") or self._model, self._module,
                self.val("f-rule"), self.val("f-group"))
        return out


GENERATORS: list[tuple[str, str]] = [
    ("module", "New Module..."),
    ("model", "New Model..."),
    ("inherit", "Extend Model..."),
    ("view", "Views + Action + Menu..."),
    ("xpath", "XPath Inheritance..."),
    ("access", "Access Rights..."),
    ("groups", "Security Groups + Rule..."),
    ("wizard", "Wizard..."),
    ("report", "QWeb Report..."),
    ("controller", "Controller..."),
    ("cron", "Cron Job..."),
    ("test", "Test Case..."),
    ("snippet", "Insert Snippet..."),
]


__all__ = [
    "GENERATORS",
    "AccessScreen",
    "ControllerScreen",
    "CronScreen",
    "DiffScreen",
    "GroupsScreen",
    "InheritModelScreen",
    "ModelScreen",
    "NewModuleScreen",
    "ReportScreen",
    "TestScreen",
    "ViewScreen",
    "WizardScreen",
    "XpathScreen",
    "parse_fields_spec",
]
