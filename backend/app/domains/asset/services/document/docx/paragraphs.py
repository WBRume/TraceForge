"""DOCX 段落解析：run 聚合、批注锚点定位与段落类型分类。"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from app.domains.asset.services.document.docx.runs import (
    extract_run_style,
    extract_run_text,
    merge_adjacent_runs,
    render_runs_to_text,
)
from app.domains.asset.services.document.docx.xml_utils import (
    DOCX_NS_MAP,
    local_name,
    safe_int,
    xml_attr,
)


def extract_paragraph_meta(paragraph: ET.Element) -> dict[str, Any]:
    """提取 pPr 段落属性（样式名、编号定义）。"""
    meta: dict[str, Any] = {}
    p_pr = paragraph.find("./w:pPr", DOCX_NS_MAP)
    if p_pr is None:
        return meta

    style_node = p_pr.find("./w:pStyle", DOCX_NS_MAP)
    if style_node is not None:
        style_val = str(style_node.attrib.get(xml_attr("val"), "") or "").strip()
        if style_val:
            meta["style"] = style_val

    num_pr = p_pr.find("./w:numPr", DOCX_NS_MAP)
    if num_pr is not None:
        num_id_node = num_pr.find("./w:numId", DOCX_NS_MAP)
        ilvl_node = num_pr.find("./w:ilvl", DOCX_NS_MAP)
        num_id = str(num_id_node.attrib.get(xml_attr("val"), "") if num_id_node is not None else "").strip()
        ilvl = max(0, safe_int(ilvl_node.attrib.get(xml_attr("val")) if ilvl_node is not None else 0, 0))
        if num_id:
            meta["num_id"] = num_id
        meta["level"] = ilvl

    return meta


class _ParagraphContent:
    """Own text offsets and comment ranges during one paragraph traversal."""

    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []
        self.comment_ranges: dict[str, dict[str, Any]] = {}
        self.active_comment_ids: list[str] = []
        self.cursor = 0

    def ensure_comment(self, comment_id: str) -> dict[str, Any]:
        if comment_id not in self.comment_ranges:
            self.comment_ranges[comment_id] = {"char_start": None, "char_end": None}
        return self.comment_ranges[comment_id]

    def start_comment(self, comment_id: str) -> None:
        if not comment_id:
            return
        info = self.ensure_comment(comment_id)
        if info["char_start"] is None:
            info["char_start"] = self.cursor
        if comment_id not in self.active_comment_ids:
            self.active_comment_ids.append(comment_id)

    def end_comment(self, comment_id: str) -> None:
        if not comment_id:
            return
        info = self.ensure_comment(comment_id)
        if info["char_start"] is None:
            info["char_start"] = self.cursor
        info["char_end"] = self.cursor
        if comment_id in self.active_comment_ids:
            self.active_comment_ids.remove(comment_id)

    def append_text(self, text: str, style: dict[str, Any]) -> None:
        if not text:
            return
        run = {"text": text}
        run.update(style)
        self.runs.append(run)
        next_cursor = self.cursor + len(text)
        for comment_id in list(self.active_comment_ids):
            info = self.ensure_comment(comment_id)
            if info["char_start"] is None:
                info["char_start"] = self.cursor
            info["char_end"] = next_cursor
        self.cursor = next_cursor

    def walk(self, node: ET.Element) -> None:
        for child in list(node):
            lname = local_name(child.tag)
            if lname == "commentRangeStart":
                self.start_comment(str(child.attrib.get(xml_attr("id"), "") or "").strip())
                continue
            if lname == "commentRangeEnd":
                self.end_comment(str(child.attrib.get(xml_attr("id"), "") or "").strip())
                continue
            if lname == "r":
                for ref in child.findall(".//w:commentReference", DOCX_NS_MAP):
                    ref_id = str(ref.attrib.get(xml_attr("id"), "") or "").strip()
                    if ref_id:
                        info = self.ensure_comment(ref_id)
                        if info["char_start"] is None:
                            info["char_start"] = self.cursor
                        info["char_end"] = self.cursor
                self.append_text(extract_run_text(child), extract_run_style(child))
                continue
            if lname in {"hyperlink", "smartTag", "sdt", "ins", "del", "fldSimple"}:
                self.walk(child)
                continue
            if lname == "instrText" and child.text:
                self.append_text(child.text, {})


def parse_paragraph_content(
    paragraph: ET.Element,
    comments_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """解析段落 → {text, runs, comment_anchors}，批注锚点以字符偏移表示。"""

    content = _ParagraphContent()
    content.walk(paragraph)
    for comment_id in list(content.active_comment_ids):
        content.end_comment(comment_id)

    merged_runs = merge_adjacent_runs(content.runs)
    text = render_runs_to_text(merged_runs)
    anchors: list[dict[str, Any]] = []
    for comment_id, span in content.comment_ranges.items():
        start = span.get("char_start")
        end = span.get("char_end")
        if start is None and end is None:
            continue
        selected_text = ""
        if isinstance(start, int) and isinstance(end, int) and 0 <= start <= end <= len(text):
            selected_text = text[start:end]
        elif isinstance(start, int) and 0 <= start < len(text):
            selected_text = text[start:]
        if not selected_text:
            selected_text = str(comments_by_id.get(comment_id, {}).get("content") or "").split("\n", 1)[0].strip()
        anchors.append(
            {
                "comment_id": comment_id,
                "char_start": start,
                "char_end": end,
                "selected_text": selected_text or None,
            }
        )
    return {"text": text, "runs": merged_runs, "comment_anchors": anchors}


def classify_paragraph_type(style_name: str, has_numbering: bool) -> tuple[str, dict[str, Any]]:
    """按样式名与编号状态判定段落块类型（heading/toc_entry/list_item/paragraph）。"""
    style = (style_name or "").strip()
    style_l = style.lower()
    meta: dict[str, Any] = {}
    if style:
        meta["style"] = style

    if style_l.startswith("heading"):
        level_match = re.search(r"(\d+)", style_l)
        level = min(max(safe_int(level_match.group(1) if level_match else 1, 1), 1), 6)
        meta["level"] = level
        return "heading", meta

    if style_l in {"title"}:
        meta["level"] = 1
        return "heading", meta
    if style_l in {"subtitle"}:
        meta["level"] = 2
        return "heading", meta

    if "toc" in style_l:
        level_match = re.search(r"(\d+)", style_l)
        level = min(max(safe_int(level_match.group(1) if level_match else 1, 1), 1), 6)
        meta["level"] = level
        return "toc_entry", meta

    if has_numbering or "list" in style_l:
        return "list_item", meta

    return "paragraph", meta
