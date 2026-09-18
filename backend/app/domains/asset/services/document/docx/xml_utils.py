"""DOCX (OOXML) XML 基础工具：命名空间常量、标签处理与安全取值。"""

from __future__ import annotations

from typing import Any

DOCX_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DOCX_NS_ATTR = f"{{{DOCX_NS}}}"
DOCX_NS_MAP = {"w": DOCX_NS}


def xml_attr(name: str) -> str:
    return f"{DOCX_NS_ATTR}{name}"


def local_name(tag: str) -> str:
    if not tag:
        return ""
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def decode_symbol(char_hex: str) -> str:
    """解码 w:sym 的 char 属性（含私有区符号映射）。"""
    raw = (char_hex or "").strip().upper()
    if not raw:
        return ""
    common = {
        "F0B7": "•",
        "00B7": "•",
        "F0A7": "§",
        "F0D8": "°",
        "F0FC": "✓",
        "F0A8": "→",
        "F0E8": "➢",
    }
    if raw in common:
        return common[raw]
    try:
        value = int(raw, 16)
    except Exception:
        return ""
    if value < 0 or value > 0x10FFFF:
        return ""
    try:
        return chr(value)
    except Exception:
        return ""
