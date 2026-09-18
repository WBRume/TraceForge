"""DOCX 主解析管线：document.xml → 统一 payload（含 python-docx 回退）。"""

from __future__ import annotations

import io
import re
import zipfile
from collections import defaultdict
from typing import Any, Dict, List, Tuple

import xml.etree.ElementTree as ET

try:
    from docx import Document as DocxDocument  # type: ignore
except Exception:
    DocxDocument = None

from app.domains.asset.services.document.docx.comments import parse_comments
from app.domains.asset.services.document.docx.numbering import parse_numbering, resolve_list_marker
from app.domains.asset.services.document.docx.paragraphs import (
    classify_paragraph_type,
    extract_paragraph_meta,
    parse_paragraph_content,
)
from app.domains.asset.services.document.docx.tables import parse_table_block, table_to_markdown
from app.domains.asset.services.document.docx.xml_utils import DOCX_NS_MAP, local_name, safe_int


def looks_like_docx_bytes(raw) -> bool:
    """判断字节内容是否为合法的 DOCX（zip + word/ 部件）。"""
    raw = raw or b""
    if len(raw) < 4 or not raw.startswith(b"PK"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = set(zf.namelist())
    except Exception:
        return False
    if "[Content_Types].xml" not in names:
        return False
    return any(name.startswith("word/") for name in names)


def empty_payload() -> Dict[str, Any]:
    return {
        "normalized_markdown": "",
        "blocks_json": [],
        "render_json": {
            "format": "rich_doc",
            "block_count": 0,
            "docx_comments": [],
            "features": {
                "runs": False,
                "tables": False,
                "toc": False,
                "comments": False,
            },
        },
    }


def _block_to_markdown_line(block: Dict[str, Any]) -> str:
    block_type = str(block.get("type") or "paragraph")
    text = str(block.get("text") or "")
    stripped = text.strip()
    meta = block.get("meta") or {}

    if block_type == "heading":
        level = min(max(safe_int(meta.get("level"), 1), 1), 6)
        return f"{'#' * level} {stripped}".strip()

    if block_type == "list_item":
        marker = str(meta.get("marker") or "•").strip() or "•"
        level = max(0, safe_int(meta.get("level"), 0))
        indent = "  " * level
        return f"{indent}{marker} {stripped}".rstrip()

    if block_type == "table":
        return table_to_markdown(list(block.get("table", {}).get("rows") or []))

    return stripped


def parse_docx_payload_via_xml(raw: bytes) -> Dict[str, Any]:
    """基于 OOXML 直接解析（保留 runs/表格/批注等富文档特征）。"""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            document_xml = zf.read("word/document.xml")
            comments_xml = zf.read("word/comments.xml") if "word/comments.xml" in zf.namelist() else b""
            numbering_xml = zf.read("word/numbering.xml") if "word/numbering.xml" in zf.namelist() else b""
    except Exception:
        return empty_payload()

    try:
        document_root = ET.fromstring(document_xml)
    except Exception:
        return empty_payload()

    comments_root = None
    if comments_xml:
        try:
            comments_root = ET.fromstring(comments_xml)
        except Exception:
            comments_root = None

    numbering_root = None
    if numbering_xml:
        try:
            numbering_root = ET.fromstring(numbering_xml)
        except Exception:
            numbering_root = None

    comments_by_id = parse_comments(comments_root)
    numbering = parse_numbering(numbering_root)
    numbering_state: Dict[str, List[int]] = defaultdict(list)

    body = document_root.find("./w:body", DOCX_NS_MAP)
    if body is None:
        return empty_payload()

    blocks: List[Dict[str, Any]] = []
    markdown_lines: List[str] = []
    anchor_items: List[Dict[str, Any]] = []
    order = 0

    def append_block(block: Dict[str, Any], anchors: List[Dict[str, Any]]) -> None:
        nonlocal order
        order += 1
        block_id = f"blk-{order}"
        block["id"] = block_id
        block["order"] = order
        blocks.append(block)
        markdown_line = _block_to_markdown_line(block)
        if markdown_line:
            markdown_lines.append(markdown_line)
        for item in anchors:
            item["block_id"] = block_id
            anchor_items.append(item)

    for child in list(body):
        tag = local_name(child.tag)
        if tag == "p":
            paragraph_data = parse_paragraph_content(child, comments_by_id)
            text = str(paragraph_data.get("text") or "")
            if not text.strip():
                continue

            para_meta = extract_paragraph_meta(child)
            style_name = str(para_meta.get("style") or "")
            has_numbering = bool(para_meta.get("num_id"))
            block_type, block_meta = classify_paragraph_type(style_name, has_numbering)
            block_meta.update({k: v for k, v in para_meta.items() if k in {"style", "level"}})

            if block_type == "list_item":
                level = max(0, safe_int(para_meta.get("level"), 0))
                num_id = str(para_meta.get("num_id") or "").strip() or None
                marker = resolve_list_marker(
                    num_id=num_id,
                    level=level,
                    numbering=numbering,
                    numbering_state=numbering_state,
                )
                block_meta["level"] = level
                block_meta["marker"] = marker
                if num_id:
                    block_meta["num_id"] = num_id

            append_block(
                {
                    "type": block_type,
                    "text": text,
                    "runs": paragraph_data.get("runs") or [],
                    "meta": block_meta,
                },
                list(paragraph_data.get("comment_anchors") or []),
            )
            continue

        if tag == "tbl":
            table_block, table_anchors = parse_table_block(child, comments_by_id)
            if not table_block["text"] and not table_block["table"]["rows"]:
                continue
            append_block(table_block, table_anchors)

    markdown = "\n\n".join(line for line in markdown_lines if line).strip()
    block_text_by_id = {str(block.get("id")): str(block.get("text") or "") for block in blocks}

    docx_comments: List[Dict[str, Any]] = []
    seen_comment_keys = set()
    for anchor in anchor_items:
        comment_id = str(anchor.get("comment_id") or "").strip()
        block_id = str(anchor.get("block_id") or "").strip()
        if not comment_id or not block_id:
            continue
        key = (comment_id, block_id)
        if key in seen_comment_keys:
            continue
        seen_comment_keys.add(key)

        comment_data = comments_by_id.get(comment_id, {})
        char_start = anchor.get("char_start")
        char_end = anchor.get("char_end")
        selected_text = str(anchor.get("selected_text") or "").strip()
        block_text = block_text_by_id.get(block_id, "")
        if (
            not selected_text
            and isinstance(char_start, int)
            and isinstance(char_end, int)
            and 0 <= char_start <= char_end <= len(block_text)
        ):
            selected_text = block_text[char_start:char_end].strip()

        docx_comments.append(
            {
                "comment_id": comment_id,
                "block_id": block_id,
                "char_start": char_start if isinstance(char_start, int) else None,
                "char_end": char_end if isinstance(char_end, int) else None,
                "selected_text": selected_text or None,
                "author": str(comment_data.get("author") or "").strip() or None,
                "initials": str(comment_data.get("initials") or "").strip() or None,
                "date": str(comment_data.get("date") or "").strip() or None,
                "content": str(comment_data.get("content") or "").strip() or "",
            }
        )

    return {
        "normalized_markdown": markdown,
        "blocks_json": blocks,
        "render_json": {
            "format": "rich_doc",
            "block_count": len(blocks),
            "docx_comments": docx_comments,
            "features": {
                "runs": True,
                "tables": True,
                "toc": True,
                "comments": bool(docx_comments),
            },
        },
    }


def parse_docx_via_python_docx(raw: bytes) -> Tuple[str, List[Dict[str, Any]]]:
    """python-docx 兜底解析（仅保留段落文本与基础样式分类）。"""
    if DocxDocument is None:
        return "", []
    doc = DocxDocument(io.BytesIO(raw))  # type: ignore[misc]

    lines: List[str] = []
    blocks: List[Dict[str, Any]] = []
    order = 0
    for paragraph in doc.paragraphs:
        text = (paragraph.text or "").strip()
        if not text:
            continue
        style_name = (getattr(paragraph.style, "name", "") or "").strip()
        style_name_l = style_name.lower()

        block_type = "paragraph"
        meta: Dict[str, Any] = {"style": style_name}
        markdown_line = text

        if style_name_l.startswith("heading"):
            level_match = re.search(r"(\d+)", style_name_l)
            level = int(level_match.group(1)) if level_match else 1
            level = min(max(level, 1), 6)
            markdown_line = f"{'#' * level} {text}"
            block_type = "heading"
            meta["level"] = level
        elif "list bullet" in style_name_l or "list paragraph" in style_name_l:
            markdown_line = f"- {text}"
            block_type = "list_item"
            meta["marker"] = "-"
        elif "list number" in style_name_l:
            markdown_line = f"1. {text}"
            block_type = "list_item"
            meta["marker"] = "1."

        lines.append(markdown_line)
        order += 1
        blocks.append(
            {
                "id": f"blk-{order}",
                "type": block_type,
                "text": text,
                "order": order,
                "meta": meta,
            }
        )

    markdown = "\n\n".join(lines).strip()
    if not blocks:
        return "", []
    return markdown, blocks


def parse_docx_payload(raw: bytes) -> Dict[str, Any]:
    """DOCX → 统一 payload：优先 XML 管线，失败时回退 python-docx。"""
    parsed = parse_docx_payload_via_xml(raw)
    if parsed.get("blocks_json") or parsed.get("normalized_markdown"):
        return parsed

    markdown = ""
    blocks: List[Dict[str, Any]] = []
    try:
        markdown, blocks = parse_docx_via_python_docx(raw)
    except Exception:
        markdown = ""
        blocks = []

    return {
        "normalized_markdown": markdown,
        "blocks_json": blocks,
        "render_json": {
            "format": "rich_doc",
            "block_count": len(blocks),
            "docx_comments": [],
            "features": {
                "runs": bool(blocks),
                "tables": False,
                "toc": False,
                "comments": False,
            },
        },
    }
