"""XML static parser: records, views, menus, refs (stdlib ElementTree)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


@dataclass
class XmlIdInfo:
    xmlid: str  # bare id (module resolved by caller)
    kind: str  # record|template|menu|action|view|data|unknown
    model: str = ""  # record @model
    lineno: int = 0


@dataclass
class ViewInfo:
    xmlid: str
    model: str = ""
    inherit_id: str = ""  # ref value
    fields: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)  # ref= values in arch
    groups: list[str] = field(default_factory=list)


@dataclass
class XmlFileInfo:
    xmlids: list[XmlIdInfo] = field(default_factory=list)
    views: list[ViewInfo] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)  # all ref-like values
    wellformed: bool = True
    error: str = ""


REF_ATTRS = ("ref", "inherit_id", "action", "parent", "view_id")
GROUP_SPLIT_RE = re.compile(r"\s*,\s*")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _kind_for_record(model: str, rec_id: str) -> str:
    if model == "ir.ui.view":
        return "view"
    if "template" in rec_id or model in ("ir.ui.view",):
        return "view"
    if model.startswith("ir.actions"):
        return "action"
    return "record"


def parse_xml(source: str) -> XmlFileInfo:
    info = XmlFileInfo()
    try:
        root = ET.fromstring(source)
    except ET.ParseError as exc:
        info.wellformed = False
        info.error = str(exc)[:300]
        return info
    # walk with line info unavailable in ET → lineno 0 (lxml upgrade later)
    for el in root.iter():
        tag = _local(el.tag)
        attrib = el.attrib
        if tag == "record" and attrib.get("id"):
            rid = attrib["id"]
            model = attrib.get("model", "")
            info.xmlids.append(XmlIdInfo(rid, _kind_for_record(model, rid), model))
            if model == "ir.ui.view":
                arch_fields: list[str] = []
                refs: list[str] = []
                groups: list[str] = []
                inherit = ""
                view_model = ""
                for sub in el.iter():
                    stag = _local(sub.tag)
                    if stag == "field":
                        fname = sub.attrib.get("name", "")
                        if fname == "model" and (sub.text or "").strip():
                            view_model = (sub.text or "").strip()
                        elif fname == "inherit_id" and sub.attrib.get("ref"):
                            inherit = sub.attrib["ref"]
                        elif fname == "arch":
                            for f in sub.iter():
                                if f is sub:
                                    continue
                                if _local(f.tag) == "field" and f.attrib.get("name"):
                                    arch_fields.append(f.attrib["name"])
                                for attr in REF_ATTRS:
                                    if f.attrib.get(attr):
                                        refs.append(f.attrib[attr])
                                if f.attrib.get("groups"):
                                    groups.extend(GROUP_SPLIT_RE.split(f.attrib["groups"]))
                    for attr in REF_ATTRS:
                        if sub is not el and sub.attrib.get(attr):
                            refs.append(sub.attrib[attr])
                info.views.append(
                    ViewInfo(
                        rid, view_model, inherit, arch_fields,
                        sorted(set(refs)), sorted(g for g in set(groups) if g),
                    )
                )
        elif tag in ("template",) and attrib.get("id"):
            info.xmlids.append(XmlIdInfo(attrib["id"], "template"))
            tname = attrib.get("t-name")
            if tname and "." in tname:
                info.refs.append(tname)
        elif tag == "menuitem" and attrib.get("id"):
            info.xmlids.append(XmlIdInfo(attrib["id"], "menu"))
        elif tag in ("act_window", "action") and attrib.get("id"):
            info.xmlids.append(XmlIdInfo(attrib["id"], "action"))
        # generic ref collection
        for attr in REF_ATTRS:
            if el.attrib.get(attr):
                info.refs.append(el.attrib[attr])
        if el.attrib.get("groups"):
            info.refs.extend(g for g in GROUP_SPLIT_RE.split(el.attrib["groups"]) if g)
        tcall = el.attrib.get("t-call", "")
        if tcall:
            info.refs.append(tcall)
    info.refs = sorted(set(info.refs))
    return info
