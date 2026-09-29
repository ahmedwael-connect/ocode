"""Project tree widget: Files/Modules views over OdooProject (FR-SMN-001..006)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.message import Message
from textual.widgets import Tree

from ocode.engines.opd.detector import OdooProject
from ocode.engines.smn.model import build_module_nodes


class FilePicked(Message):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path


class OdooTree(Tree[Path | str | None]):
    def __init__(self, **kwargs: object) -> None:
        super().__init__("EXPLORER", **kwargs)  # type: ignore[arg-type]
        self.mode = "modules"
        self.project: OdooProject | None = None

    def set_project(self, project: OdooProject) -> None:
        self.project = project
        self.reload()

    def toggle_mode(self) -> str:
        self.mode = "files" if self.mode == "modules" else "modules"
        self.reload()
        return self.mode

    def reload(self) -> None:
        self.clear()
        proj = self.project
        if proj is None:
            self.root.add_leaf("no project", data=None)
            return
        base = proj.root or proj.start
        label = f"{'odoo ' + proj.version if proj.version else 'workspace'} · {base.name}"
        self.root.set_label(label)
        if self.mode == "files":
            self._build_files(base, self.root, depth=0)
        else:
            self._build_modules()

    def _build_files(self, path: Path, node: Any, depth: int) -> None:
        if depth > 3:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
        except OSError:
            return
        count = 0
        for e in entries:
            if e.name.startswith(".") or e.name == "__pycache__":
                continue
            if count >= 300:
                node.add_leaf("… (truncated)", data=None)
                break
            count += 1
            if e.is_dir():
                child = node.add(e.name, data=e)
                self._build_files(e, child, depth + 1)
            else:
                node.add_leaf(e.name, data=e)

    def _build_modules(self) -> None:
        proj = self.project
        if proj is None:
            return
        if not proj.modules:
            base = proj.root or proj.start
            self.root.add_leaf(f"no modules ({base})", data=None)
            return
        nodes = build_module_nodes(proj.modules)
        for mn in nodes[:200]:
            mod_label = f"{mn.info.name} [{mn.info.kind}]"
            mod_node = self.root.add(mod_label, data=mn.info.path)
            # key files
            for key in (mn.info.manifest_path, mn.info.path / "__init__.py"):
                if key.is_file():
                    mod_node.add_leaf(key.name, data=key)
            for group in ("Models", "Views", "Security", "Data", "Tests"):
                files = mn.groups.get(group, [])
                if not files:
                    continue
                gnode = mod_node.add(group, data=None)
                for f in files[:50]:
                    gnode.add_leaf(f.name, data=f)

    async def on_tree_node_selected(self, event: Tree.NodeSelected[Path | str | None]) -> None:
        data = event.node.data
        if isinstance(data, Path) and data.is_file():
            self.post_message(FilePicked(data))
