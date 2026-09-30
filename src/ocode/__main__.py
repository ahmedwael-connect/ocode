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


_SUBCOMMANDS = ("doctor", "index", "init")
_VALUE_OPTS = {"--conf", "--odoo-bin", "--db", "--log-level", "--config-dir"}


def _extract_subcommand(raw: list[str]) -> tuple[str | None, list[str]]:
    """Split off a leading subcommand without letting argparse eat paths.

    Workaround for the classic nargs='?'-positional + subparsers conflict
    (plain `ocode .` / `ocode file.py` must keep working).
    """
    skip_next = False
    for i, tok in enumerate(raw):
        if skip_next:
            skip_next = False
            continue
        if tok in _VALUE_OPTS:
            skip_next = True
            continue
        if tok.startswith("-") and tok != "-":
            if "=" not in tok:
                # boolean flags take no value; unknown long opts: be lenient
                continue
            continue
        if tok in _SUBCOMMANDS:
            return tok, raw[:i] + raw[i + 1 :]
        return None, raw
    return None, raw


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ocode", description="Odoo-aware terminal editor")
    p.add_argument("path", nargs="?", default=".", help="file or folder to open")
    p.add_argument("--conf", help="Odoo config file")
    p.add_argument("--odoo-bin", help="Path to odoo-bin")
    p.add_argument("--db", help="Database name")
    p.add_argument("--no-index", action="store_true", help="Disable background indexing")
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--config-dir", help="Override config dir")
    p.add_argument("--ascii", action="store_true", help="ASCII icons (no Nerd-Font glyphs)")
    p.add_argument("--version", action="store_true", help="Print version and exit")
    p.add_argument("subcommand", nargs="?", default=None,
                   help="doctor [keys] | index | init (also accepted as first positional)")
    return p


def cmd_doctor(check: str = "") -> int:
    import os

    print(f"ocode {__version__} — doctor")
    print(f"python: {sys.version.split()[0]} on {platform.platform()}")
    for tool in ("rg", "git", "python3"):
        print(f"{tool}: {'found' if shutil.which(tool) else 'MISSING'}")
    try:
        import textual as _t

        print(f"textual: {_t.__version__}")
    except ImportError:
        print("textual: MISSING (pip install textual)")
    term = os.environ.get("TERM", "?")
    colorterm = os.environ.get("COLORTERM", "")
    kitty = bool(os.environ.get("KITTY_KEYBOARD") or "kitty" in term)
    truecolor = colorterm.lower() in ("truecolor", "24bit") or "direct" in term or kitty
    print(f"terminal: TERM={term} COLORTERM={colorterm or '—'} "
          f"truecolor={'yes' if truecolor else 'no'} kitty-keys={'yes' if kitty else 'no'}")
    if check == "keys":
        print("keys: combos that may not reach the app without Kitty protocol:")
        for combo, alt in (("Ctrl+Shift+P/M/F/N", "remap or use F-keys"),
                           ("Alt+M / Alt+R", "Ctrl+K then M/R"),
                           ("Ctrl+`", "F7 fallback"),
                           ("Ctrl+Enter", "use shell panel input instead"),
                           ("Ctrl+Space", "may be grabbed by IME/desktop")):
            print(f"  {combo:22} → {alt}  (kitty: {'ok' if kitty else 'maybe lost'})")
        return 0
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
    import sys as _sys

    raw = list(argv) if argv is not None else _sys.argv[1:]
    # 'ocode doctor keys': keep 'doctor' from being eaten by the path positional
    sub, rest = _extract_subcommand(raw)
    parser = build_parser()
    args = parser.parse_args(rest if sub is not None else raw)

    if args.version:
        print(__version__)
        return 0

    log = setup_logging(args.log_level)

    if sub is None and args.subcommand is not None:
        parser.error(f"unexpected extra argument: {args.subcommand}")

    if sub == "doctor":
        check = args.path if args.path != "." else ""
        return cmd_doctor(check if check == "keys" else "")
    if sub == "init":
        target, _, _ = parse_position(args.path)
        return cmd_init(target.resolve())
    if sub == "index":
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
    if args.ascii and isinstance(config.data.get("ui"), dict):
        ui = config.data["ui"]
        assert isinstance(ui, dict)
        ui["ascii"] = True
    log.debug("open=%s line=%s col=%s conf=%s db=%s", start, line, col, args.conf, args.db)

    from ocode.app import OcodeApp

    app = OcodeApp(
        start_path=start, config=config, conf_override=args.conf, bin_override=args.odoo_bin
    )
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
