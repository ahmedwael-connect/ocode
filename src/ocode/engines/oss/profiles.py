"""Server profiles: named launch configs (FR-OSS-020), servers.toml."""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found]


@dataclass
class ServerProfile:
    name: str = "dev"
    odoo_bin: str = ""
    python: str = ""
    conf: str = ""
    db: str = ""
    mode: str = "managed"  # managed | systemd | docker
    flags: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    lint_before_restart: str = "warn"  # off | warn | block
    systemd_unit: str = "odoo"
    docker_service: str = "odoo"
    auto_update_on_save: bool = False
    stop_timeout: float = 10.0


def default_profile(
    odoo_bin: str = "", python: str = "", conf: str = "", db: str = ""
) -> ServerProfile:
    flags = ["--dev=reload,qweb,xml", "--log-level=info"]
    return ServerProfile(
        name="dev", odoo_bin=odoo_bin, python=python, conf=conf, db=db, flags=flags
    )


def servers_path(workspace: Path) -> Path:
    return workspace / ".ocode" / "servers.toml"


def load_profiles(workspace: Path) -> dict[str, ServerProfile]:
    path = servers_path(workspace)
    try:
        raw = path.read_bytes()
    except OSError:
        return {}
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (ValueError, OSError):
        return {}
    out: dict[str, ServerProfile] = {}
    profiles = data.get("profile", {})
    if not isinstance(profiles, dict):
        return {}
    for name, cfg in profiles.items():
        if not isinstance(cfg, dict):
            continue
        try:
            out[name] = ServerProfile(
                name=name,
                odoo_bin=str(cfg.get("odoo_bin", "")),
                python=str(cfg.get("python", "")),
                conf=str(cfg.get("conf", "")),
                db=str(cfg.get("db", "")),
                mode=str(cfg.get("mode", "managed")),
                flags=[str(x) for x in cfg.get("flags", []) if isinstance(x, str)],
                env={str(k): str(v) for k, v in cfg.get("env", {}).items()},
                lint_before_restart=str(cfg.get("lint_before_restart", "warn")),
                systemd_unit=str(cfg.get("systemd_unit", "odoo")),
                docker_service=str(cfg.get("docker_service", "odoo")),
                auto_update_on_save=bool(cfg.get("auto_update_on_save", False)),
            )
        except (TypeError, ValueError, AttributeError):
            continue
    return out


def save_profiles(workspace: Path, profiles: dict[str, ServerProfile]) -> Path:
    path = servers_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# ocode server profiles (FR-OSS-020)\n"]
    for name in sorted(profiles):
        p = profiles[name]
        d = asdict(p)
        d.pop("name", None)
        lines.append(f"[profile.{name}]\n")
        for key in ("odoo_bin", "python", "conf", "db", "mode", "lint_before_restart"):
            lines.append(f'{key} = "{d.get(key, "")}"\n')
        lines.append(f'systemd_unit = "{d.get("systemd_unit", "odoo")}"\n')
        lines.append(f'docker_service = "{d.get("docker_service", "odoo")}"\n')
        flags = ", ".join(f'"{f}"' for f in d.get("flags", []))
        lines.append(f"flags = [{flags}]\n")
        env = d.get("env", {})
        if env:
            lines.append(f"[profile.{name}.env]\n")
            for k, v in env.items():
                lines.append(f'{k} = "{v}"\n')
        auto = "true" if d.get("auto_update_on_save") else "false"
        lines.append(f"auto_update_on_save = {auto}\n")
        lines.append("\n")
    path.write_text("".join(lines), encoding="utf-8")
    return path
