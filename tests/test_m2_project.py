"""M2 tests: OPD detection, SMN models/related/search, SES session."""

from __future__ import annotations

from pathlib import Path

from ocode.engines.opd.detector import (
    classify_module,
    detect_project,
    detect_version,
    find_conf,
    find_odoo_root,
    parse_odoo_conf,
    scan_modules,
)
from ocode.engines.opd.module import is_module_dir, read_manifest
from ocode.engines.ses import CursorPos, SessionData, SessionManager
from ocode.engines.smn.model import build_module_nodes, iter_files, should_ignore
from ocode.engines.smn.related import cycle_related, find_module_dir, key_file, related_files
from ocode.engines.smn.search import (
    content_search_sync,
    parse_quickopen_query,
    quick_open,
)


def make_odoo_root(base: Path) -> Path:
    root = base / "odoo17"
    (root / "odoo").mkdir(parents=True)
    (root / "odoo" / "release.py").write_text(
        'version_info = (17, 0, 0, "final", 0)\n', encoding="utf-8"
    )
    (root / "odoo-bin").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    (root / "odoo" / "addons").mkdir(parents=True)
    (root / "addons").mkdir(exist_ok=True)
    # core module stub
    sale = root / "odoo" / "addons" / "sale"
    (sale / "models").mkdir(parents=True)
    manifest_txt = "{'name': 'Sale', 'version': '17.0.1.0'}"
    (sale / "__manifest__.py").write_text(manifest_txt, encoding="utf-8")
    # custom addons path with demo module
    custom = base / "my_addons"
    mod = custom / "sale_custom"
    (mod / "models").mkdir(parents=True)
    (mod / "views").mkdir(parents=True)
    (mod / "security").mkdir(parents=True)
    (mod / "__init__.py").write_text("from . import models\n", encoding="utf-8")
    (mod / "__manifest__.py").write_text(
        "{'name': 'Sale Custom', 'version': '17.0.1.0', 'depends': ['sale'],"
        " 'data': ['security/ir.model.access.csv', 'views/sale_order_views.xml']}",
        encoding="utf-8",
    )
    (mod / "models" / "__init__.py").write_text("from . import sale_order\n", encoding="utf-8")
    (mod / "models" / "sale_order.py").write_text(
        "from odoo import models, fields\n", encoding="utf-8"
    )
    (mod / "views" / "sale_order_views.xml").write_text("<odoo></odoo>\n", encoding="utf-8")
    (mod / "security" / "ir.model.access.csv").write_text("id,name\n", encoding="utf-8")
    addons = f"{root / 'odoo' / 'addons'},{custom}"
    conf_txt = f"[options]\naddons_path = {addons}\ndb_name = mydb\nhttp_port = 8069\n"
    (root / "odoo.conf").write_text(conf_txt, encoding="utf-8")
    return root


def test_find_root_version_conf(tmp_path: Path) -> None:
    root = make_odoo_root(tmp_path)
    deep = root / "odoo" / "addons"
    found, obin = find_odoo_root(deep)
    assert found == root
    assert obin is not None and obin.name == "odoo-bin"
    assert detect_version(root) == "17.0"
    conf_path = find_conf(root=root)
    assert conf_path is not None
    conf = parse_odoo_conf(conf_path)
    assert conf.db_name == "mydb"
    assert len(conf.addons_path) == 2


def test_scan_classify(tmp_path: Path) -> None:
    root = make_odoo_root(tmp_path)
    conf = parse_odoo_conf(root / "odoo.conf")
    mods = scan_modules(conf.addons_path, root)
    names = {m.name for m in mods}
    assert {"sale", "sale_custom"} <= names
    by_name = {m.name: m for m in mods}
    assert by_name["sale_custom"].depends == ["sale"]
    assert classify_module(by_name["sale"].path, root, conf.addons_path) == "core"
    assert classify_module(by_name["sale_custom"].path, root, conf.addons_path) == "custom"
    assert is_module_dir(by_name["sale_custom"].path)
    assert read_manifest(by_name["sale_custom"].manifest_path)["name"] == "Sale Custom"


def test_detect_project_end_to_end(tmp_path: Path) -> None:
    root = make_odoo_root(tmp_path)
    proj = detect_project(root / "odoo" / "addons" / "sale", conf_override=root / "odoo.conf")
    assert proj.found and proj.root == root
    assert proj.version == "17.0"
    assert len(proj.modules) == 2


def test_tree_ignores_and_groups(tmp_path: Path) -> None:
    root = make_odoo_root(tmp_path)
    proj = detect_project(root, conf_override=root / "odoo.conf")
    nodes = build_module_nodes(proj.modules)
    custom = next(n for n in nodes if n.info.name == "sale_custom")
    assert custom.groups["Models"] and custom.groups["Views"] and custom.groups["Security"]
    (tmp_path / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    assert should_ignore(tmp_path / "x.pyc", tmp_path)
    files = iter_files(proj.modules[0].path)
    assert files


def test_related_cycle(tmp_path: Path) -> None:
    root = make_odoo_root(tmp_path)
    proj = detect_project(root, conf_override=root / "odoo.conf")
    custom_mod = next(m for m in proj.modules if m.name == "sale_custom")
    model = custom_mod.path / "models" / "sale_order.py"
    rel = related_files(model, proj.modules)
    assert any(p.name == "sale_order_views.xml" for p in rel)
    assert any(p.name == "__manifest__.py" for p in rel)
    nxt = cycle_related(model, proj.modules)
    assert nxt is not None and nxt != model
    mod = find_module_dir(model, proj.modules)
    assert mod is not None and mod.name == "sale_custom"
    assert key_file(mod, "manifest") is not None


def test_quick_open_ranking() -> None:
    cands = ["sale_custom/models/sale_order.py", "sale/views/sale_views.xml", "other/x.py"]
    assert quick_open(cands, "saleorder")[0].endswith("sale_order.py")
    assert quick_open(cands, "", recent=["other/x.py"])[0] == "other/x.py"
    assert quick_open(cands, "sale ext:py") == ["sale_custom/models/sale_order.py"]
    parsed = parse_quickopen_query("@myfield ext:py,xml")
    assert parsed["kind"] == "symbols" and parsed["ext"] == "py,xml"


def test_content_search_sync(tmp_path: Path) -> None:
    a = tmp_path / "a.py"
    a.write_text("hello foo\nbar foo baz\n", encoding="utf-8")
    hits = content_search_sync("foo", [tmp_path])
    assert len(hits) == 2 and hits[0].line == 1
    assert content_search_sync("nomatch_xyz", [tmp_path]) == []


def test_session_roundtrip(tmp_path: Path, monkeypatch: object) -> None:
    import ocode.engines.ses as ses

    monkeypatch.setattr(ses, "state_dir", lambda: tmp_path)
    mgr = SessionManager(tmp_path / "ws")
    data = SessionData(tabs=["/a.py", None], active=1, cursors={"/a.py": CursorPos(3, 4)})
    mgr.save(data)
    loaded = mgr.load()
    assert loaded is not None and loaded.tabs == ["/a.py", None]
    assert loaded.cursors["/a.py"].line == 3
