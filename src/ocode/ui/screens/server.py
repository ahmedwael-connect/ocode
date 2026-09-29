"""Server screens: setup (profile+flags), update chooser, confirm (FR-OSS-020..025)."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Checkbox, Input, OptionList, Select, Static
from textual.widgets.option_list import Option

from ocode.engines.oss.flags import FLAG_CATALOG, preview_command
from ocode.engines.oss.profiles import ServerProfile


class ConfirmScreen(ModalScreen[bool]):
    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        yield Static(self._message)
        yield Static("Press Y to confirm, N/Esc to cancel")

    async def on_key(self, event: events.Key) -> None:
        if event.key in ("y", "Y"):
            self.dismiss(True)
        elif event.key in ("n", "N", "escape"):
            self.dismiss(False)


class UpdateChooserScreen(ModalScreen[list[str] | None]):
    """Pick modules for -u (current preselected, +dependents, all)."""

    def __init__(self, modules: list[str], current: str | None = None) -> None:
        super().__init__()
        self._modules = modules
        self._current = current

    def compose(self) -> ComposeResult:
        yield Static("Update modules (-u). Enter=run, Esc=cancel")
        yield Input(value=self._current or "", placeholder="mod1,mod2 or 'all'", id="upd-input")
        yield OptionList(id="upd-list")

    def on_mount(self) -> None:
        lst = self.query_one("#upd-list", OptionList)
        if self._current:
            cur = self._current
            lst.add_option(Option(f"current: {cur}", id=f"cur:{cur}"))
            lst.add_option(Option("current + dependents", id=f"cur:{cur}"))
        lst.add_option(Option("all modules (-u all) ⚠", id="all"))
        for m in self._modules[:100]:
            lst.add_option(Option(m, id=f"mod:{m}"))
        self.query_one("#upd-input", Input).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        oid = str(event.option.id or "")
        if oid == "all":
            self.dismiss(["all"])
        elif oid.startswith("cur:"):
            self.dismiss([oid[4:]])
        elif oid.startswith("mod:"):
            inp = self.query_one("#upd-input", Input)
            cur = inp.value.strip().rstrip(",")
            inp.value = f"{cur},{oid[4:]}".strip(",") if cur else oid[4:]

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "upd-input":
            return
        raw = event.value.strip()
        if not raw:
            self.dismiss(None)
            return
        mods = [m.strip() for m in raw.split(",") if m.strip()]
        self.dismiss(mods)

    async def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)


class ServerSetupScreen(ModalScreen[ServerProfile | None]):
    """Edit profile fields + common flags with live command preview."""

    def __init__(self, profile: ServerProfile) -> None:
        super().__init__()
        self._profile = profile

    def compose(self) -> ComposeResult:
        p = self._profile
        yield Static(f"Server profile: {p.name} (Enter=safe, Esc=cancel)")
        yield Input(value=p.odoo_bin, placeholder="odoo-bin path", id="sv-bin")
        yield Input(value=p.python, placeholder="python (venv) or empty", id="sv-python")
        yield Input(value=p.conf, placeholder="odoo.conf path", id="sv-conf")
        yield Input(value=p.db, placeholder="database", id="sv-db")
        yield Select(
            [(m, m) for m in ("managed", "systemd", "docker")],
            value=p.mode,
            id="sv-mode",
        )
        yield Input(value=" ".join(p.flags), placeholder="flags", id="sv-flags")
        yield Input(value=p.systemd_unit, placeholder="systemd unit", id="sv-unit")
        yield Checkbox("auto-update on save", value=p.auto_update_on_save, id="sv-auto")
        yield Static("", id="sv-preview")
        yield Static("Flags catalog (group: name — help):")
        yield OptionList(id="sv-catalog")

    def on_mount(self) -> None:
        lst = self.query_one("#sv-catalog", OptionList)
        for spec in FLAG_CATALOG[:40]:
            lst.add_option(Option(f"{spec.group}: {spec.name} — {spec.help}", id=spec.name))
        self._update_preview()
        self.query_one("#sv-bin", Input).focus()

    def _collect(self) -> ServerProfile:
        def val(wid: str) -> str:
            try:
                return self.query_one(f"#{wid}", Input).value.strip()
            except Exception:
                return ""

        try:
            mode = self.query_one("#sv-mode", Select).value
            mode_s = str(mode) if mode else "managed"
        except Exception:
            mode_s = "managed"
        try:
            auto = self.query_one("#sv-auto", Checkbox).value
        except Exception:
            auto = False
        flags = [f for f in val("sv-flags").split() if f]
        return ServerProfile(
            name=self._profile.name,
            odoo_bin=val("sv-bin"),
            python=val("sv-python"),
            conf=val("sv-conf"),
            db=val("sv-db"),
            mode=mode_s,
            flags=flags,
            env=dict(self._profile.env),
            lint_before_restart=self._profile.lint_before_restart,
            systemd_unit=val("sv-unit") or "odoo",
            docker_service=self._profile.docker_service,
            auto_update_on_save=bool(auto),
        )

    def _update_preview(self) -> None:
        from ocode.engines.oss.flags import build_args

        p = self._collect()
        prog, argv = build_args(
            p.odoo_bin or "odoo-bin", p.python or None, p.conf or None, p.db or None, p.flags
        )
        try:
            self.query_one("#sv-preview", Static).update("$ " + preview_command(prog, argv))
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        _ = event
        self._update_preview()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        _ = event
        self.dismiss(self._collect())

    async def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            # avoid double-dismiss with input submitted; only when catalog focused
            try:
                focused = self.focused
                if focused is not None and getattr(focused, "id", "") == "sv-catalog":
                    self.dismiss(self._collect())
            except Exception:
                pass


__all__ = ["ConfirmScreen", "ServerSetupScreen", "UpdateChooserScreen"]
