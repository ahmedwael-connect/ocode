"""OPD engine: Odoo project detection (PRD §4.2, M2). Static only, no imports of Odoo code."""

from ocode.engines.opd.detector import (
    OdooConf,
    OdooProject,
    classify_module,
    detect_project,
    detect_venv,
    detect_version,
    find_conf,
    find_odoo_root,
    parse_odoo_conf,
    scan_modules,
)
from ocode.engines.opd.module import ModuleInfo, read_manifest

__all__ = [
    "ModuleInfo",
    "OdooConf",
    "OdooProject",
    "classify_module",
    "detect_project",
    "detect_version",
    "detect_venv",
    "find_conf",
    "find_odoo_root",
    "parse_odoo_conf",
    "read_manifest",
    "scan_modules",
]
