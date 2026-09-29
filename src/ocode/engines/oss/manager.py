"""ServerManager: profiles + process + logs + failure hints (FR-OSS-001..010)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ocode.engines.oss.failure import FailureHint, detect_failure
from ocode.engines.oss.flags import build_args, preview_command
from ocode.engines.oss.logs import LogBuffer, LogRecord
from ocode.engines.oss.process import ManagedProc
from ocode.engines.oss.profiles import ServerProfile
from ocode.engines.oss.tailer import LogTailer

ServerStatus = str  # Stopped|Starting|Running|Updating|Crashed


@dataclass
class ServerSnapshot:
    status: ServerStatus = "Stopped"
    pid: int | None = None
    port: int = 8069
    uptime: float = 0.0
    db: str = ""
    last_hint: FailureHint | None = None


class ServerManager:
    def __init__(self, profile: ServerProfile | None = None, max_log_lines: int = 20000) -> None:
        self.profile = profile or ServerProfile()
        self.proc = ManagedProc()
        self.logs = LogBuffer(max_log_lines)
        self.tailer: LogTailer | None = None
        self.status: ServerStatus = "Stopped"
        self.started_at: float | None = None
        self._recent_output: list[str] = []
        self._status_listeners: list[Callable[[ServerStatus], None]] = []
        self._log_listeners: list[Callable[[LogRecord], None]] = []
        self.proc.on_line = self._feed
        if self.profile.conf:
            lf = _logfile_of_conf(self.profile.conf)
            if lf:
                self.tailer = LogTailer(Path(lf))

    # -- listeners -----------------------------------------------------
    def on_status(self, fn: Callable[[ServerStatus], None]) -> None:
        self._status_listeners.append(fn)

    def on_log(self, fn: Callable[[LogRecord], None]) -> None:
        self._log_listeners.append(fn)

    def _set_status(self, s: ServerStatus) -> None:
        self.status = s
        for fn in self._status_listeners:
            fn(s)

    def _feed(self, line: str) -> None:
        rec = self.logs.append_raw(line)
        self._recent_output.append(line)
        self._recent_output = self._recent_output[-300:]
        for fn in self._log_listeners:
            fn(rec)

    # -- commands ------------------------------------------------------
    def command_for(
        self,
        update: list[str] | None = None,
        install: list[str] | None = None,
        one_shot: bool = False,
    ) -> tuple[str, list[str]]:
        p = self.profile
        return build_args(
            odoo_bin=p.odoo_bin or "odoo-bin",
            python=p.python or None,
            conf=p.conf or None,
            db=p.db or None,
            extra_flags=list(p.flags),
            update=update,
            install=install,
            stop_after_init=one_shot,
        )

    def preview(self, **kwargs: object) -> str:
        update = kwargs.get("update")
        install = kwargs.get("install")
        one_shot = bool(kwargs.get("one_shot", False))
        prog, argv = self.command_for(
            update=update if isinstance(update, list) else None,
            install=install if isinstance(install, list) else None,
            one_shot=one_shot,
        )
        return preview_command(prog, argv)

    def systemd_command(self, action: str = "restart") -> list[str]:
        return ["systemctl", action, self.profile.systemd_unit or "odoo"]

    def docker_command(self, action: str = "restart") -> list[str]:
        return ["docker", "compose", action, self.profile.docker_service or "odoo"]

    async def start(self) -> ServerStatus:
        if self.profile.mode in ("systemd", "docker"):
            # app layer runs these via sudo prompt; manager records intent
            self._set_status("Running")
            return self.status
        prog, argv = self.command_for()
        self._set_status("Starting")
        try:
            await self.proc.start(prog, argv, env=dict(self.profile.env) or None)
        except OSError as exc:
            self._feed(f"ERROR ocode: failed to start: {exc}")
            self._set_status("Crashed")
            return self.status
        self.started_at = time.time()
        self._set_status("Running")
        return self.status

    async def stop(self) -> ServerStatus:
        if self.profile.mode in ("systemd", "docker") or not self.proc.running:
            self._set_status("Stopped")
            return self.status
        await self.proc.stop(timeout=self.profile.stop_timeout)
        hint = detect_failure("\n".join(self._recent_output[-120:]))
        self.snapshot_hint = hint
        self._set_status("Stopped")
        return self.status

    async def restart(self) -> ServerStatus:
        await self.stop()
        return await self.start()

    async def restart_update(self, modules: list[str]) -> ServerStatus:
        """One-shot -u then normal start (FR-OSS-007)."""
        if not modules:
            return await self.restart()
        if self.profile.mode in ("systemd", "docker") or not self.profile.odoo_bin:
            # without managed process, just record update intent
            self._set_status("Updating")
            mods = ",".join(modules)
            self._feed(f"INFO ocode: update {mods} (mode={self.profile.mode})")
            self._set_status("Stopped")
            return self.status
        self._set_status("Updating")
        prog, argv = self.command_for(update=modules, one_shot=True)
        tmp = ManagedProc()
        lines: list[str] = []

        def _collect(ln: str) -> None:
            lines.append(ln)
            self._feed(ln)

        tmp.on_line = _collect
        try:
            await tmp.start(prog, argv, env=dict(self.profile.env) or None)
            await tmp.wait()
        except OSError as exc:
            self._feed(f"ERROR ocode: update failed: {exc}")
            self._set_status("Crashed")
            return self.status
        hint = detect_failure("\n".join(lines[-150:]))
        if hint is not None and hint.kind in ("traceback", "module_error"):
            self.snapshot_hint = hint
            self._set_status("Crashed")
            return self.status
        return await self.start()

    snapshot_hint: FailureHint | None = None

    def snapshot(self) -> ServerSnapshot:
        port = 8069
        for fl in self.profile.flags:
            if fl.startswith("--http-port"):
                try:
                    port = int(fl.split("=", 1)[1])
                except (IndexError, ValueError):
                    pass
        uptime = self.proc.uptime if self.proc.running else 0.0
        return ServerSnapshot(
            status=self.status,
            pid=self.proc.pid,
            port=port,
            uptime=uptime,
            db=self.profile.db,
            last_hint=self.snapshot_hint,
        )

    def poll_tailer(self) -> list[LogRecord]:
        if self.tailer is None:
            return []
        recs = []
        for ln in self.tailer.poll():
            recs.append(self.logs.append_raw(ln))
        for rec in recs:
            for fn in self._log_listeners:
                fn(rec)
        return recs


def _logfile_of_conf(conf: str) -> str | None:
    import configparser

    parser = configparser.ConfigParser()
    try:
        parser.read(conf, encoding="utf-8")
        if parser.has_section("options"):
            lf = parser.get("options", "logfile", fallback="")
            return lf or None
    except (OSError, configparser.Error):
        return None
    return None


@dataclass
class TestRun:
    modules: list[str] = field(default_factory=list)
    tags: str = ""
    passed: int = 0
    failed: int = 0


def test_command(
    profile: ServerProfile, modules: list[str], tags: str = ""
) -> tuple[str, list[str]]:
    tag = tags or "/" + modules[0]
    flags = list(profile.flags) + ["--test-enable", f"--test-tags={tag}"]
    return build_args(
        odoo_bin=profile.odoo_bin or "odoo-bin",
        python=profile.python or None,
        conf=profile.conf or None,
        db=profile.db or None,
        extra_flags=flags,
        update=modules,
        stop_after_init=True,
    )
