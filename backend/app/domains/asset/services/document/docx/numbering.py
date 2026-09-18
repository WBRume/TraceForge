"""DOCX 编号列表：numbering.xml 解析与列表 marker 渲染。"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

import xml.etree.ElementTree as ET

from app.domains.asset.services.document.docx.xml_utils import DOCX_NS_MAP, safe_int, xml_attr


def roman_numeral(value: int, uppercase: bool = True) -> str:
    if value <= 0:
        return str(value)
    numerals = [
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    ]
    out = []
    remaining = value
    for unit, symbol in numerals:
        while remaining >= unit:
            out.append(symbol)
            remaining -= unit
    rendered = "".join(out) or str(value)
    return rendered if uppercase else rendered.lower()


def alpha_numeral(value: int, uppercase: bool = False) -> str:
    if value <= 0:
        return str(value)
    chars = []
    current = value
    while current > 0:
        current -= 1
        chars.append(chr((current % 26) + (65 if uppercase else 97)))
        current //= 26
    rendered = "".join(reversed(chars))
    return rendered.upper() if uppercase else rendered.lower()


def normalize_list_marker(marker: str) -> str:
    """私有区符号（Wingdings 等）统一回落为圆点。"""
    text = (marker or "").strip()
    if not text:
        return "•"
    for ch in text:
        code = ord(ch)
        if 0xF000 <= code <= 0xF8FF:
            return "•"
    return text


def format_counter(value: int, num_fmt: str) -> str:
    fmt = (num_fmt or "decimal").lower()
    if fmt in {"decimal", "decimalzero"}:
        return str(value)
    if fmt in {"lowerletter", "loweralpha"}:
        return alpha_numeral(value, uppercase=False)
    if fmt in {"upperletter", "upperalpha"}:
        return alpha_numeral(value, uppercase=True)
    if fmt == "lowerroman":
        return roman_numeral(value, uppercase=False)
    if fmt == "upperroman":
        return roman_numeral(value, uppercase=True)
    return str(value)


def parse_numbering(numbering_root: Optional[ET.Element]) -> Dict[str, Any]:
    """解析 numbering.xml → {num_to_abs, levels}。"""
    result: Dict[str, Any] = {"num_to_abs": {}, "levels": {}}
    if numbering_root is None:
        return result

    levels_map: Dict[str, Dict[int, Dict[str, Any]]] = {}
    for abstract in numbering_root.findall(".//w:abstractNum", DOCX_NS_MAP):
        abstract_id = str(abstract.attrib.get(xml_attr("abstractNumId"), "") or "").strip()
        if not abstract_id:
            continue
        level_info: Dict[int, Dict[str, Any]] = {}
        for level_node in abstract.findall("./w:lvl", DOCX_NS_MAP):
            level = safe_int(level_node.attrib.get(xml_attr("ilvl")), 0)
            num_fmt_node = level_node.find("./w:numFmt", DOCX_NS_MAP)
            lvl_text_node = level_node.find("./w:lvlText", DOCX_NS_MAP)
            start_node = level_node.find("./w:start", DOCX_NS_MAP)
            level_info[level] = {
                "num_fmt": str(num_fmt_node.attrib.get(xml_attr("val"), "") if num_fmt_node is not None else "").strip().lower(),
                "lvl_text": str(lvl_text_node.attrib.get(xml_attr("val"), "") if lvl_text_node is not None else "").strip(),
                "start": max(1, safe_int(start_node.attrib.get(xml_attr("val")) if start_node is not None else 1, 1)),
            }
        levels_map[abstract_id] = level_info

    num_to_abs: Dict[str, str] = {}
    for num_node in numbering_root.findall(".//w:num", DOCX_NS_MAP):
        num_id = str(num_node.attrib.get(xml_attr("numId"), "") or "").strip()
        abs_node = num_node.find("./w:abstractNumId", DOCX_NS_MAP)
        abs_id = str(abs_node.attrib.get(xml_attr("val"), "") if abs_node is not None else "").strip()
        if num_id and abs_id:
            num_to_abs[num_id] = abs_id

    result["num_to_abs"] = num_to_abs
    result["levels"] = levels_map
    return result


def resolve_list_marker(
    *,
    num_id: Optional[str],
    level: int,
    numbering: Dict[str, Any],
    numbering_state: Dict[str, list],
) -> str:
    """按 numbering 定义与计数状态渲染当前列表项 marker。"""
    if not num_id:
        return "•"

    levels = numbering.get("levels") or {}
    num_to_abs = numbering.get("num_to_abs") or {}
    abstract_id = str(num_to_abs.get(num_id) or "").strip()
    level_info = (levels.get(abstract_id) or {}).get(level) or {}

    start_value = max(1, safe_int(level_info.get("start"), 1))
    counters = numbering_state[num_id]
    while len(counters) <= level:
        counters.append(0)
    if counters[level] <= 0:
        counters[level] = start_value
    else:
        counters[level] += 1
    for idx in range(level + 1, len(counters)):
        counters[idx] = 0

    num_fmt = str(level_info.get("num_fmt") or "").strip().lower()
    lvl_text = str(level_info.get("lvl_text") or "").strip()
    if num_fmt == "bullet":
        bullet = re.sub(r"%\d+", "", lvl_text).strip() or "•"
        return normalize_list_marker(bullet)

    template = lvl_text or f"%{level + 1}."

    def repl(match: re.Match) -> str:
        requested_idx = max(0, safe_int(match.group(1), level + 1) - 1)
        if requested_idx >= len(counters) or counters[requested_idx] <= 0:
            value = 1
        else:
            value = counters[requested_idx]
        if requested_idx == level:
            return format_counter(value, num_fmt)
        return str(value)

    marker = re.sub(r"%(\d+)", repl, template).strip()
    if marker:
        return normalize_list_marker(marker)
    return f"{format_counter(counters[level], num_fmt)}."

