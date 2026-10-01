"""ServerManager: profiles + process + logs + failure hints (FR-OSS-001..010)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ocode.engines.oss.docker import (
    ComposeProject,
    LogStream,
    detect_compose,
    exec_update,
    service_action,
)
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
        self.workspace: Path | None = None
        self._compose: ComposeProject | None = None
        self._log_stream: LogStream | None = None
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

    def compose_project(self) -> ComposeProject | None:
        if self._compose is not None:
            return self._compose
        if self.profile.docker_compose:
            svc = self.profile.docker_service or "odoo"
            self._compose = ComposeProject(Path(self.profile.docker_compose), svc)
            return self._compose
        base = self.workspace or Path.cwd()
        self._compose = detect_compose(base, self.profile.docker_service or "odoo")
        return self._compose

    async def _run_systemctl(self, action: str) -> ServerStatus:
        import asyncio as _aio

        cmd = ["systemctl", action, self.profile.systemd_unit or "odoo"]
        if action == "start":
            self._set_status("Starting")
        elif action == "stop":
            self._set_status("Stopped")
        else:
            self._set_status("Running")
        try:
            proc = await _aio.create_subprocess_exec(
                *cmd, stdout=_aio.subprocess.PIPE, stderr=_aio.subprocess.STDOUT,
            )
            out, _ = await _aio.wait_for(proc.communicate(), 60)
        except (OSError, NotImplementedError) as exc:
            self._feed(f"ERROR ocode: systemctl failed: {exc}")
            self._set_status("Crashed")
            return self.status
        except TimeoutError:
            self._feed("ERROR ocode: systemctl timed out (sudo prompt? run it manually)")
            self._set_status("Crashed")
            return self.status
        for ln in out.decode("utf-8", errors="ignore").splitlines():
            if ln.strip():
                self._feed(f"INFO ocode[systemctl]: {ln.strip()}")
        if proc.returncode not in (0, None):
            self._feed(f"ERROR ocode: systemctl {action} exited {proc.returncode}")
            self._set_status("Crashed")
            return self.status
        self._set_status("Running" if action in ("start", "restart") else "Stopped")
        return self.status

    async def _docker_start_stream(self) -> None:
        proj = self.compose_project()
        if proj is None:
            return
        await self._docker_stop_stream()
        stream = LogStream(proj)
        self._log_stream = stream
        await stream.start(self._feed)

    async def _docker_stop_stream(self) -> None:
        if self._log_stream is not None:
            await self._log_stream.stop()
            self._log_stream = None

    def docker_preview(self, action: str) -> str:
        proj = self.compose_project()
        base = ["docker", "compose"] + (["-f", str(proj.file)] if proj else [])
        if action == "up":
            args: list[str] = ["up", "-d", self.profile.docker_service or "odoo"]
        else:
            args = [action, self.profile.docker_service or "odoo"]
        return preview_command(base[0], base[1:] + args)

    async def start_debug(self, debug_port: int = 5678) -> ServerStatus:
        """Start under debugpy (DAP). Requires python + odoo_bin in profile."""
        if not self.profile.python or not self.profile.odoo_bin:
            self._feed("ERROR ocode: debug needs python + odoo-bin in profile")
            self._set_status("Crashed")
            return self.status
        prog, argv = self.command_for()
        dbg = [self.profile.python, "-m", "debugpy", "--listen",
               f"127.0.0.1:{debug_port}", *argv]
        _ = prog
        self._set_status("Starting")
        try:
            await self.proc.start(dbg[0], dbg[1:], env=dict(self.profile.env) or None)
        except OSError as exc:
            self._feed(f"ERROR ocode: debug start failed: {exc}")
            self._set_status("Crashed")
            return self.status
        self.started_at = time.time()
        self._set_status("Running")
        return self.status

    async def start(self) -> ServerStatus:
        if self.profile.mode == "systemd":
            return await self._run_systemctl("start")
        if self.profile.mode == "docker":
            proj = self.compose_project()
            if proj is None:
                self._feed("ERROR ocode: no compose file (set docker_compose in profile)")
                self._set_status("Crashed")
                return self.status
            self._set_status("Starting")
            code, out, err = await service_action(proj, "up")
            for ln in (out + "\n" + err).splitlines():
                if ln.strip():
                    self._feed(f"INFO ocode[compose]: {ln.strip()}")
            if code != 0:
                self._set_status("Crashed")
                return self.status
            await self._docker_start_stream()
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
        if self.profile.mode == "systemd":
            return await self._run_systemctl("stop")
        if self.profile.mode == "docker":
            await self._docker_stop_stream()
            proj = self.compose_project()
            if proj is not None:
                code, out, err = await service_action(proj, "stop")
                for ln in (out + "\n" + err).splitlines():
                    if ln.strip():
                        self._feed(f"INFO ocode[compose]: {ln.strip()}")
            self._set_status("Stopped")
            return self.status
        if not self.proc.running:
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
        if self.profile.mode == "docker":
            return await self._docker_update(modules)
        if self.profile.mode == "systemd" and not self.profile.odoo_bin:
            self._set_status("Updating")
            mods = ",".join(modules)
            self._feed(f"INFO ocode: update {mods} (mode=systemd, no odoo-bin for one-shot)")
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
        if self.profile.mode == "systemd":
            return await self._run_systemctl("restart")
        return await self.start()

    async def _docker_update(self, modules: list[str]) -> ServerStatus:
        proj = self.compose_project()
        if proj is None:
            self._feed("ERROR ocode: no compose file (set docker_compose in profile)")
            self._set_status("Crashed")
            return self.status
        self._set_status("Updating")
        container_bin = self.profile.docker_odoo_bin or "odoo"
        argv = [container_bin]
        if self.profile.db:
            argv += ["-d", self.profile.db]
        argv += ["-u", ",".join(modules), "--stop-after-init"]
        code, out, err = await exec_update(proj, argv)
        for ln in (out + "\n" + err).splitlines():
            if ln.strip():
                self._feed(ln.rstrip("\n"))
        if code != 0:
            hint = detect_failure(out + "\n" + err)
            self.snapshot_hint = hint
            self._set_status("Crashed")
            return self.status
        code, _out, _err = await service_action(proj, "restart")
        if code != 0:
            self._set_status("Crashed")
            return self.status
        await self._docker_start_stream()
        self._set_status("Running")
        return self.status

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
