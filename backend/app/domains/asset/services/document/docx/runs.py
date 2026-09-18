"""DOCX run 级解析：文本提取、字符样式提取与相邻 run 合并。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import xml.etree.ElementTree as ET

from app.domains.asset.services.document.docx.xml_utils import (
    DOCX_NS_MAP,
    decode_symbol,
    local_name,
    safe_int,
    xml_attr,
)


def _word_bool(node: Optional[ET.Element]) -> bool:
    if node is None:
        return False
    raw = str(node.attrib.get(xml_attr("val"), "") or "").strip().lower()
    if raw in {"0", "false", "off", "none"}:
        return False
    return True


def _word_highlight_to_hex(name: str) -> Optional[str]:
    palette = {
        "yellow": "#fef08a",
        "green": "#86efac",
        "cyan": "#67e8f9",
        "magenta": "#f9a8d4",
        "blue": "#93c5fd",
        "red": "#fca5a5",
        "darkblue": "#1d4ed8",
        "darkred": "#b91c1c",
        "darkyellow": "#ca8a04",
        "darkgreen": "#15803d",
        "darkcyan": "#0e7490",
        "darkmagenta": "#a21caf",
        "lightgray": "#e5e7eb",
        "darkgray": "#6b7280",
        "black": "#111827",
    }
    return palette.get(name.strip().lower())


def _hex_color(raw: str) -> Optional[str]:
    normalized = raw.strip().replace("#", "").upper()
    if not normalized or normalized in {"AUTO", "NONE"}:
        return None
    if re.fullmatch(r"[0-9A-F]{6}", normalized):
        return f"#{normalized}"
    return None


def extract_run_style(run: ET.Element) -> Dict[str, Any]:
    """提取 rPr 字符样式（粗体/斜体/下划线/颜色/字号/字体等）。"""
    style: Dict[str, Any] = {}
    r_pr = run.find("./w:rPr", DOCX_NS_MAP)
    if r_pr is None:
        return style

    if _word_bool(r_pr.find("./w:b", DOCX_NS_MAP)):
        style["bold"] = True
    if _word_bool(r_pr.find("./w:i", DOCX_NS_MAP)):
        style["italic"] = True

    underline = r_pr.find("./w:u", DOCX_NS_MAP)
    if underline is not None:
        raw = str(underline.attrib.get(xml_attr("val"), "") or "").strip().lower()
        if raw not in {"none", "0", "false", "off"}:
            style["underline"] = True

    if _word_bool(r_pr.find("./w:strike", DOCX_NS_MAP)) or _word_bool(r_pr.find("./w:dstrike", DOCX_NS_MAP)):
        style["strike"] = True

    vert_align = r_pr.find("./w:vertAlign", DOCX_NS_MAP)
    if vert_align is not None:
        align = str(vert_align.attrib.get(xml_attr("val"), "") or "").strip().lower()
        if align in {"superscript", "subscript"}:
            style[align] = True

    color_node = r_pr.find("./w:color", DOCX_NS_MAP)
    if color_node is not None:
        color = _hex_color(str(color_node.attrib.get(xml_attr("val"), "") or ""))
        if color:
            style["color"] = color

    highlight_node = r_pr.find("./w:highlight", DOCX_NS_MAP)
    if highlight_node is not None:
        highlight = _word_highlight_to_hex(str(highlight_node.attrib.get(xml_attr("val"), "") or ""))
        if highlight:
            style["highlight"] = highlight

    size_node = r_pr.find("./w:sz", DOCX_NS_MAP)
    if size_node is not None:
        half_points = safe_int(size_node.attrib.get(xml_attr("val")), 0)
        if half_points > 0:
            style["font_size"] = round(half_points / 2, 2)

    font_node = r_pr.find("./w:rFonts", DOCX_NS_MAP)
    if font_node is not None:
        font_name = (
            str(font_node.attrib.get(xml_attr("ascii"), "") or "").strip()
            or str(font_node.attrib.get(xml_attr("hAnsi"), "") or "").strip()
            or str(font_node.attrib.get(xml_attr("eastAsia"), "") or "").strip()
        )
        if font_name:
            style["font_name"] = font_name

    return style


def extract_run_text(run: ET.Element) -> str:
    """提取 run 内的可见文本（w:t/tab/br/sym/instrText 等）。"""
    parts: List[str] = []
    for node in list(run):
        lname = local_name(node.tag)
        if lname == "t" and node.text:
            parts.append(node.text)
        elif lname in {"tab", "ptab"}:
            parts.append("\t")
        elif lname in {"br", "cr"}:
            parts.append("\n")
        elif lname in {"noBreakHyphen", "softHyphen"}:
            parts.append("-")
        elif lname == "sym":
            parts.append(decode_symbol(node.attrib.get(xml_attr("char"), "")))
        elif lname == "instrText" and node.text:
            parts.append(node.text)
    return "".join(parts)


def merge_adjacent_runs(runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """合并样式相同的相邻 run，跳过空文本。"""
    if not runs:
        return []
    merged: List[Dict[str, Any]] = []
    for run in runs:
        text = str(run.get("text") or "")
        if not text:
            continue
        style = {k: v for k, v in run.items() if k != "text"}
        if merged:
            prev = merged[-1]
            prev_style = {k: v for k, v in prev.items() if k != "text"}
            if prev_style == style:
                prev["text"] = str(prev.get("text") or "") + text
                continue
        merged.append({"text": text, **style})
    return merged


def render_runs_to_text(runs: List[Dict[str, Any]]) -> str:
    return "".join(str(item.get("text") or "") for item in runs)
