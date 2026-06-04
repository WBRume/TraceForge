"""
Avatar SVG utilities.

This module keeps all avatar-related logic centralized:
- generate deterministic default SVG avatars
- sanitize uploaded SVG content
- decode legacy data-url SVG avatars
"""

from __future__ import annotations

import base64
import hashlib
import html
import re
from typing import Optional
from urllib.parse import unquote_to_bytes
from xml.etree import ElementTree as ET


SVG_MAX_LENGTH = 20_000

_EVENT_ATTR_PATTERN = re.compile(r"^on[a-z]+", re.IGNORECASE)
_HEX_COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_DANGEROUS_VALUE_PATTERNS = (
    re.compile(r"javascript\s*:", re.IGNORECASE),
    re.compile(r"vbscript\s*:", re.IGNORECASE),
    re.compile(r"data\s*:\s*text/html", re.IGNORECASE),
    re.compile(r"<\s*script", re.IGNORECASE),
)

_ALLOWED_TAGS = {
    "svg",
    "g",
    "defs",
    "path",
    "rect",
    "circle",
    "ellipse",
    "line",
    "polyline",
    "polygon",
    "text",
    "tspan",
    "linearGradient",
    "radialGradient",
    "stop",
    "clipPath",
}

_COMMON_ALLOWED_ATTRS = {
    "id",
    "class",
    "x",
    "y",
    "x1",
    "x2",
    "y1",
    "y2",
    "cx",
    "cy",
    "r",
    "rx",
    "ry",
    "width",
    "height",
    "viewBox",
    "d",
    "points",
    "fill",
    "stroke",
    "stroke-width",
    "stroke-linecap",
    "stroke-linejoin",
    "stroke-miterlimit",
    "stroke-dasharray",
    "stroke-dashoffset",
    "fill-opacity",
    "stroke-opacity",
    "opacity",
    "transform",
    "font-size",
    "font-weight",
    "font-family",
    "text-anchor",
    "dominant-baseline",
    "offset",
    "stop-color",
    "stop-opacity",
    "gradientUnits",
    "gradientTransform",
    "xlink:href",
    "href",
    "clip-path",
    "preserveAspectRatio",
    "role",
    "aria-hidden",
    "xmlns",
    "xmlns:xlink",
}

_SVG_PALETTES = [
    ("#0ea5e9", "#2563eb", "#ffffff"),
    ("#14b8a6", "#0f766e", "#ffffff"),
    ("#22c55e", "#16a34a", "#ffffff"),
    ("#f59e0b", "#f97316", "#ffffff"),
    ("#ef4444", "#dc2626", "#ffffff"),
    ("#8b5cf6", "#6366f1", "#ffffff"),
    ("#06b6d4", "#0284c7", "#ffffff"),
    ("#ec4899", "#db2777", "#ffffff"),
]


def _local_name(tag_or_attr: str) -> str:
    if "}" in tag_or_attr:
        return tag_or_attr.split("}", 1)[1]
    return tag_or_attr


def _is_dangerous_value(value: str) -> bool:
    lowered = value.strip()
    return any(pattern.search(lowered) for pattern in _DANGEROUS_VALUE_PATTERNS)


def _sanitize_element(element: ET.Element) -> bool:
    local_tag = _local_name(element.tag)
    if local_tag not in _ALLOWED_TAGS:
        return False

    cleaned_attrs: dict[str, str] = {}
    for raw_attr, raw_value in list(element.attrib.items()):
        local_attr = _local_name(raw_attr)
        if _EVENT_ATTR_PATTERN.match(local_attr):
            continue
        if local_attr not in _COMMON_ALLOWED_ATTRS:
            continue
        if _is_dangerous_value(raw_value):
            continue
        cleaned_attrs[local_attr] = raw_value.strip()
    element.attrib.clear()
    element.attrib.update(cleaned_attrs)

    for child in list(element):
        if not _sanitize_element(child):
            element.remove(child)
    return True


def _strip_tag_namespace(element: ET.Element) -> None:
    element.tag = _local_name(element.tag)
    for child in list(element):
        _strip_tag_namespace(child)


def _pick_palette(seed: str, base_color: Optional[str] = None) -> tuple[str, str, str]:
    if base_color:
        normalized = normalize_hex_color(base_color, fallback="#0ea5e9")
        return (normalized, "#0f172a", "#ffffff")

    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    index = int(digest[:8], 16) % len(_SVG_PALETTES)
    return _SVG_PALETTES[index]


def _pick_initial(display_name: str, email: str, user_id: str) -> str:
    candidate = (display_name or "").strip() or (email or "").strip() or (user_id or "").strip() or "?"
    return candidate[0].upper()


def normalize_hex_color(color: str, fallback: str = "#0ea5e9") -> str:
    value = (color or "").strip()
    if not _HEX_COLOR_PATTERN.match(value):
        return fallback
    if len(value) == 4:
        return "#" + "".join(ch * 2 for ch in value[1:])
    return value.lower()


def build_default_avatar_svg(
    display_name: str,
    email: str,
    user_id: str,
    *,
    style: str = "classic",
    base_color: Optional[str] = None,
) -> str:
    initial = html.escape(_pick_initial(display_name, email, user_id))
    seed = f"{display_name}|{email}|{user_id}"
    start_color, end_color, text_color = _pick_palette(seed, base_color=base_color)

    if style == "soft":
        return (
            "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 64 64\" role=\"img\" aria-hidden=\"true\">"
            "<defs>"
            "<linearGradient id=\"bg\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\">"
            f"<stop offset=\"0%\" stop-color=\"{start_color}\" stop-opacity=\"0.92\"/>"
            f"<stop offset=\"100%\" stop-color=\"{end_color}\" stop-opacity=\"0.86\"/>"
            "</linearGradient>"
            "</defs>"
            "<rect x=\"2\" y=\"2\" width=\"60\" height=\"60\" rx=\"30\" fill=\"url(#bg)\"/>"
            "<circle cx=\"32\" cy=\"32\" r=\"27\" fill=\"#ffffff\" fill-opacity=\"0.12\"/>"
            f"<text x=\"32\" y=\"34\" text-anchor=\"middle\" dominant-baseline=\"middle\" fill=\"{text_color}\" font-size=\"28\" font-family=\"'Segoe UI', 'PingFang SC', sans-serif\" font-weight=\"700\">{initial}</text>"
            "</svg>"
        )

    if style == "split":
        return (
            "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 64 64\" role=\"img\" aria-hidden=\"true\">"
            f"<rect x=\"0\" y=\"0\" width=\"32\" height=\"64\" fill=\"{start_color}\"/>"
            f"<rect x=\"32\" y=\"0\" width=\"32\" height=\"64\" fill=\"{end_color}\"/>"
            "<circle cx=\"32\" cy=\"32\" r=\"29\" fill=\"#ffffff\" fill-opacity=\"0.16\"/>"
            f"<text x=\"32\" y=\"34\" text-anchor=\"middle\" dominant-baseline=\"middle\" fill=\"{text_color}\" font-size=\"28\" font-family=\"'Segoe UI', 'PingFang SC', sans-serif\" font-weight=\"700\">{initial}</text>"
            "</svg>"
        )

    return (
        "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 64 64\" role=\"img\" aria-hidden=\"true\">"
        "<defs>"
        "<linearGradient id=\"bg\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\">"
        f"<stop offset=\"0%\" stop-color=\"{start_color}\"/>"
        f"<stop offset=\"100%\" stop-color=\"{end_color}\"/>"
        "</linearGradient>"
        "</defs>"
        "<rect x=\"0\" y=\"0\" width=\"64\" height=\"64\" rx=\"32\" fill=\"url(#bg)\"/>"
        "<circle cx=\"32\" cy=\"32\" r=\"28\" fill=\"#ffffff\" fill-opacity=\"0.1\"/>"
        f"<text x=\"32\" y=\"34\" text-anchor=\"middle\" dominant-baseline=\"middle\" fill=\"{text_color}\" font-size=\"28\" font-family=\"'Segoe UI', 'PingFang SC', sans-serif\" font-weight=\"700\">{initial}</text>"
        "</svg>"
    )


def sanitize_avatar_svg(raw_svg: str) -> str:
    svg_text = (raw_svg or "").strip()
    if not svg_text:
        raise ValueError("Avatar SVG cannot be empty")
    if len(svg_text) > SVG_MAX_LENGTH:
        raise ValueError("Avatar SVG is too large")

    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as exc:
        raise ValueError("Invalid SVG format") from exc

    if _local_name(root.tag).lower() != "svg":
        raise ValueError("Avatar must be a valid <svg> root element")
    if not _sanitize_element(root):
        raise ValueError("Invalid SVG content")

    # Ensure serialized output keeps standard <svg> tags (no ns0 prefixes),
    # so frontend v-html can render it reliably.
    _strip_tag_namespace(root)

    root.attrib["xmlns"] = "http://www.w3.org/2000/svg"
    if "viewBox" not in root.attrib:
        root.attrib["viewBox"] = "0 0 64 64"
    if "role" not in root.attrib:
        root.attrib["role"] = "img"
    if "aria-hidden" not in root.attrib:
        root.attrib["aria-hidden"] = "true"

    sanitized = ET.tostring(root, encoding="unicode", method="xml")
    if len(sanitized) > SVG_MAX_LENGTH:
        raise ValueError("Avatar SVG is too large")
    return sanitized


def svg_from_data_url(data_url: str) -> Optional[str]:
    raw = (data_url or "").strip()
    if not raw.lower().startswith("data:image/svg+xml"):
        return None

    if "," not in raw:
        return None
    header, payload = raw.split(",", 1)
    is_base64 = ";base64" in header.lower()

    try:
        if is_base64:
            decoded = base64.b64decode(payload, validate=True)
        else:
            decoded = unquote_to_bytes(payload)
        text = decoded.decode("utf-8")
        return sanitize_avatar_svg(text)
    except Exception:
        return None


def resolve_avatar_svg(
    avatar_svg: Optional[str],
    avatar_url: Optional[str],
    *,
    display_name: str,
    email: str,
    user_id: str,
) -> str:
    if avatar_svg and avatar_svg.strip():
        try:
            return sanitize_avatar_svg(avatar_svg)
        except ValueError:
            pass

    if avatar_url and avatar_url.strip():
        decoded = svg_from_data_url(avatar_url)
        if decoded:
            return decoded

    return build_default_avatar_svg(display_name, email, user_id)
