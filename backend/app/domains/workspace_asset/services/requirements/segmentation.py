"""Requirement 文档解析：Markdown 分段、验收标准抽取、标题推断。

纯文本逻辑，不依赖 DB；被直接导入、AI preview prompt 构建与确认落地共用。
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from app.domains.asset.services.document.payload import parse_document_payload
from app.domains.workspace_asset.services.common.errors import WorkspaceAssetError
from app.domains.workspace_asset.services.common.primitives import clean_optional, normalize_list

_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
_SPLIT_LIST_RE = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+(.+?)\s*$")
_AC_HEADING_RE = re.compile(r"(acceptance\s+criteria|验收标准|验收条件)", re.IGNORECASE)
_CHECKBOX_RE = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+(.+?)\s*$")


def strip_marker(text: str) -> str:
    stripped = text.strip()
    checkbox = _CHECKBOX_RE.match(stripped)
    if checkbox:
        return checkbox.group(1).strip()
    return re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", stripped).strip()


def extract_acceptance_criteria(lines: List[str]) -> List[str]:
    criteria: List[str] = []
    in_acceptance = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _AC_HEADING_RE.search(stripped):
            in_acceptance = True
            continue
        if in_acceptance and _HEADING_RE.match(stripped):
            break
        checkbox = _CHECKBOX_RE.match(stripped)
        if checkbox:
            criteria.append(checkbox.group(1).strip())
            continue
        if in_acceptance and re.match(r"^\s*(?:[-*]|\d+[.)])\s+", stripped):
            criteria.append(strip_marker(stripped))
    return normalize_list(criteria)


def segment_requirements(markdown: str) -> List[Dict[str, Any]]:
    """把 Markdown 需求文档切成 Requirement 候选项（heading > 列表项 > 整文档）。"""
    lines = [line.rstrip() for line in str(markdown or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    non_empty = [line.strip() for line in lines if line.strip()]
    if not non_empty:
        return []

    heading_positions = [(idx, match.group(2).strip()) for idx, line in enumerate(lines) if (match := _HEADING_RE.match(line))]
    segments: List[tuple[str, List[str], str]] = []
    if heading_positions:
        for offset, (start, title) in enumerate(heading_positions):
            end = heading_positions[offset + 1][0] if offset + 1 < len(heading_positions) else len(lines)
            body_lines = lines[start + 1:end]
            segments.append((title, body_lines, f"heading:{offset + 1}"))
    else:
        item_positions = [(idx, match.group(1).strip()) for idx, line in enumerate(lines) if (match := _SPLIT_LIST_RE.match(line))]
        if len(item_positions) > 1:
            for offset, (start, title) in enumerate(item_positions):
                end = item_positions[offset + 1][0] if offset + 1 < len(item_positions) else len(lines)
                body_lines = lines[start:end]
                segments.append((title, body_lines, f"item:{offset + 1}"))
        else:
            first = non_empty[0]
            title = strip_marker(first)
            segments.append((title, lines, "document:1"))

    items: List[Dict[str, Any]] = []
    for index, (title, body_lines, source_ref) in enumerate(segments):
        normalized_title = clean_optional(strip_marker(title), limit=300) or f"Requirement {index + 1}"
        body = "\n".join(line for line in body_lines).strip() or None
        items.append(
            {
                "title": normalized_title,
                "body": body,
                "acceptance_criteria": extract_acceptance_criteria(body_lines),
                "source_ref": source_ref,
                "source_metadata": {"segment_index": index, "segment_title": normalized_title},
                "order_index": index,
            }
        )
    return items


def looks_like_single_requirement(markdown: str) -> bool:
    """判断输入是否已经是一条短小、可独立追踪的需求（避免为拆而拆）。"""
    text = re.sub(r"\s+", " ", str(markdown or "")).strip()
    if not text or len(text) > 900:
        return False
    headings = [
        line for line in str(markdown or "").splitlines()
        if _HEADING_RE.match(line.strip())
    ]
    if len(headings) > 1:
        return False
    explicit_requirement_markers = re.findall(
        r"(?im)^\s*(?:REQ(?:UIREMENT)?[-_\s]*\d+|需求\s*\d+)[:：\.\)]",
        str(markdown or ""),
    )
    numbered_items = re.findall(r"(?m)^\s*\d+[\.\)]\s+\S", str(markdown or ""))
    return len(explicit_requirement_markers) <= 1 and len(numbered_items) <= 1


def direct_import_title(file_name: str, markdown: str) -> str:
    for line in str(markdown or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        heading = _HEADING_RE.match(stripped)
        if heading:
            return (clean_optional(heading.group(2), limit=300) or "Imported Requirement")
        return (clean_optional(strip_marker(stripped), limit=300) or "Imported Requirement")
    base = os.path.splitext(os.path.basename(file_name or ""))[0]
    return clean_optional(base, limit=300) or "Imported Requirement"


# ---------------------------------------------------------------------------
# 上传文档 → Markdown（直接导入与 import preview 作业共用）
# ---------------------------------------------------------------------------


def parse_requirement_document(file_name: str, raw: bytes) -> Dict[str, Any]:
    if not file_name.lower().endswith((".docx", ".md", ".markdown", ".txt")):
        raise WorkspaceAssetError("Requirement import supports DOCX, Markdown and Text files only.", status_code=415)
    parsed = parse_document_payload(file_name, raw)
    markdown = str(parsed.get("normalized_markdown") or "").strip()
    if not markdown:
        raise WorkspaceAssetError("No requirement content could be parsed from the provided document.", status_code=422)
    return parsed


def document_metadata(parsed: Dict[str, Any], *, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "source_ext": parsed.get("source_ext"),
        "source_mime": parsed.get("source_mime"),
        "render": parsed.get("render_json"),
        **(extra or {}),
    }
