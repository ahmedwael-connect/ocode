"""CLI entry: `ocode [path]` (FR-CLI-001/003/004, M0 subset)."""

from __future__ import annotations

import argparse
import platform
import shutil
import sys
from pathlib import Path

from ocode import __version__
from ocode.core.config import default_config_dir, load_config
from ocode.core.logging import setup_logging


def parse_position(target: str) -> tuple[Path, int | None, int | None]:
    """Parse `file[:line[:col]]` (FR-CLI-002)."""
    parts = target.split(":")
    path = Path(parts[0]).expanduser()
    line = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    col = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    return path, line, col


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ocode", description="Odoo-aware terminal editor")
    p.add_argument("path", nargs="?", default=".", help="file or folder to open")
    p.add_argument("--conf", help="Odoo config file")
    p.add_argument("--odoo-bin", help="Path to odoo-bin")
    p.add_argument("--db", help="Database name")
    p.add_argument("--no-index", action="store_true", help="Disable background indexing")
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--config-dir", help="Override config dir")
    p.add_argument("--version", action="store_true", help="Print version and exit")
    sub = p.add_subparsers(dest="subcommand")
    sub.add_parser("doctor", help="Environment diagnostics (FR-CLI-004)")
    sub.add_parser("index", help="Rebuild index (stub until M4)")
    sub.add_parser("init", help="Create workspace config (FR-CLI-004)")
    return p


def cmd_doctor() -> int:
    print(f"ocode {__version__} — doctor")
    print(f"python: {sys.version.split()[0]} on {platform.platform()}")
    for tool in ("rg", "git", "python3"):
        print(f"{tool}: {'found' if shutil.which(tool) else 'MISSING'}")
    try:
        import textual as _t

        print(f"textual: {_t.__version__}")
    except ImportError:
        print("textual: MISSING (pip install textual)")
    try:
        from ocode.engines.opd.detector import detect_project

        proj = detect_project(Path.cwd())
        if proj.found:
            print(f"odoo: root={proj.root} version={proj.version or '?'}")
            print(f"odoo: {len(proj.modules)} modules, {len(proj.addons_paths)} addons paths")
            if proj.conf and proj.conf.path:
                print(f"odoo: conf={proj.conf.path} db={proj.conf.db_name or '—'}")
            if proj.odoo_bin:
                print(f"odoo: bin={proj.odoo_bin}")
        else:
            print("odoo: no installation detected here")
    except OSError as exc:
        print(f"odoo: detection failed ({exc})")
    return 0


def cmd_init(path: Path) -> int:
    d = path if path.is_dir() else path.parent
    cfgdir = d / ".ocode"
    cfgdir.mkdir(parents=True, exist_ok=True)
    cfg = cfgdir / "config.toml"
    if not cfg.exists():
        cfg.write_text(f'[workspace]\nname = "{d.name}"\n', encoding="utf-8")
        print(f"created: {cfg}")
    else:
        print(f"exists: {cfg}")
    servers = cfgdir / "servers.toml"
    if not servers.exists():
        servers.write_text(
            "[profile.dev]\n"
            'odoo_bin = ""\npython = ""\nconf = ""\ndb = ""\nmode = "managed"\n'
            'flags = ["--dev=reload,qweb,xml", "--log-level=info"]\n'
            'lint_before_restart = "warn"\n',
            encoding="utf-8",
        )
        print(f"created: {servers}")
    else:
        print(f"exists: {servers}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0

    log = setup_logging(args.log_level)

    if args.subcommand == "doctor":
        return cmd_doctor()
    if args.subcommand == "init":
        target, _, _ = parse_position(args.path)
        return cmd_init(target.resolve())
    if args.subcommand == "index":
        from ocode.engines.oki.db import OkiDb, index_path_for
        from ocode.engines.oki.indexer import Indexer
        from ocode.engines.oki.query import OkiQuery
        from ocode.engines.opd.detector import detect_project

        proj = detect_project(Path.cwd(), args.conf, args.odoo_bin)
        if not proj.found or not proj.modules:
            print("index: no Odoo project/modules detected here")
            return 1
        ws = proj.root or Path.cwd()
        db = OkiDb(index_path_for(ws))
        try:
            stats = Indexer(db, list(proj.modules)).build(
                progress=lambda i, n: print(f"\rindex: {i}/{n} files", end="", flush=True)
            )
            q = OkiQuery(db)
            s = q.stats()
        finally:
            db.close()
        print(f"\rindex: {stats.files} files, {s.get('models', 0)} models, "
              f"{s.get('fields', 0)} fields, {s.get('xmlids', 0)} xml ids "
              f"({stats.elapsed:.1f}s)")
        return 0

    target, line, col = parse_position(args.path)
    start = target.resolve() if target.exists() else Path.cwd()

    config_dir = Path(args.config_dir).expanduser() if args.config_dir else default_config_dir()
    workspace = start if start.is_dir() else start.parent
    config = load_config(workspace=workspace, config_dir=config_dir)
    log.debug("open=%s line=%s col=%s conf=%s db=%s", start, line, col, args.conf, args.db)

    from ocode.app import OcodeApp

    app = OcodeApp(
        start_path=start, config=config, conf_override=args.conf, bin_override=args.odoo_bin
    )
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
