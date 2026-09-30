"""Generator specs with validation (FR-OSG-001..008)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ocode.engines.osg.naming import technical_name_for


@dataclass
class FieldSpec:
    name: str
    ftype: str = "Char"
    string: str = ""
    required: bool = False
    comodel: str = ""
    compute: str = ""
    related: str = ""
    default: str = ""
    help: str = ""

    def errors(self) -> list[str]:
        errs = []
        if not self.name.replace("_", "").isalnum():
            errs.append(f"bad field name '{self.name}'")
        if self.ftype in ("Many2one", "One2many", "Many2many") and not self.comodel:
            errs.append(f"{self.name}: {self.ftype} needs comodel")
        return errs


@dataclass
class ModelSpec:
    name: str = ""  # dotted _name (derived if empty)
    display: str = ""  # human label → derives _name via module
    module: str = ""
    description: str = ""
    inherit: str = ""  # extension target (empty = new model)
    inherits: str = ""  # _inherits "field: model"
    order: str = ""
    rec_name: str = ""
    mixins: list[str] = field(default_factory=list)  # mail.thread, mail.activity.mixin
    fields: list[FieldSpec] = field(default_factory=list)

    def errors(self) -> list[str]:
        errs = []
        if not self.module:
            errs.append("module is required")
        for f in self.fields:
            errs.extend(f.errors())
        return errs


@dataclass
class ModuleSpec:
    display: str = "My Module"
    technical: str = ""  # derived
    version: str = "17.0.1.0"
    depends: list[str] = field(default_factory=lambda: ["base"])
    category: str = "Custom"
    license: str = "LGPL-3"
    author: str = ""
    website: str = ""
    summary: str = ""

    def __post_init__(self) -> None:
        if not self.technical:
            self.technical = technical_name_for(self.display)

    def errors(self) -> list[str]:
        if not self.technical.replace("_", "").isalnum():
            return [f"bad technical name '{self.technical}'"]
        return []


@dataclass
class ViewSpec:
    model: str = ""
    module: str = ""
    kinds: list[str] = field(default_factory=lambda: ["form", "list"])
    view_name: str = ""  # arch name suffix
    with_action: bool = True
    with_menu: bool = True

    def errors(self) -> list[str]:
        if not self.model or "." not in self.model:
            return [f"bad model '{self.model}'"]
        allowed = {"form", "list", "tree", "kanban", "search", "pivot",
                   "graph", "calendar", "activity"}
        bad = [k for k in self.kinds if k not in allowed]
        return [f"bad view kind '{k}'" for k in bad]


@dataclass
class XpathSpec:
    parent_ref: str = ""  # e.g. sale.view_order_form
    model: str = ""
    module: str = ""
    anchor: str = "name"  # field/pagename to anchor on
    position: str = "after"  # before|after|inside|replace|attributes
    field: str = ""
    view_name: str = ""

    def errors(self) -> list[str]:
        if "." not in self.parent_ref:
            return [f"bad parent ref '{self.parent_ref}'"]
        if self.position not in ("before", "after", "inside", "replace", "attributes"):
            return [f"bad position '{self.position}'"]
        return []


@dataclass
class AccessSpec:
    model: str = ""
    module: str = ""
    groups: list[str] = field(default_factory=lambda: ["user", "manager"])

    def errors(self) -> list[str]:
        if "." not in self.model:
            return [f"bad model '{self.model}'"]
        return []


@dataclass
class WizardSpec:
    name: str = ""
    module: str = ""
    description: str = ""

    def errors(self) -> list[str]:
        return [] if self.name and self.module else ["wizard needs name + module"]


@dataclass
class ReportSpec:
    name: str = ""
    module: str = ""
    model: str = ""
    description: str = ""

    def errors(self) -> list[str]:
        if not self.name or not self.module or "." not in self.model:
            return ["report needs name + module + model"]
        return []


@dataclass
class ControllerSpec:
    module: str = ""
    route: str = "/my_module/hello"
    auth: str = "user"  # user|public|none

    def errors(self) -> list[str]:
        if not self.module or not self.route.startswith("/"):
            return ["controller needs module + /route"]
        return []


@dataclass
class CronSpec:
    name: str = ""
    module: str = ""
    model: str = ""
    code: str = "model._cron_do_something()"
    interval_number: int = 1
    interval_type: str = "days"

    def errors(self) -> list[str]:
        if not self.name or not self.module or "." not in self.model:
            return ["cron needs name + module + model"]
        return []


@dataclass
class CaseSpec:
    module: str = ""
    model: str = ""
    class_name: str = "TestMyModel"

    def errors(self) -> list[str]:
        return [] if self.module and self.model else ["test needs module + model"]
