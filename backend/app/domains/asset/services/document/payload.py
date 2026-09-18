"""文档解析统一入口：按扩展名分发，产出统一 payload 结构。"""

from __future__ import annotations

import mimetypes
import os
from typing import Any, Dict, Optional, Tuple

from app.domains.asset.services.document import markdown_blocks
from app.domains.asset.services.document.docx import parse_docx_payload

SUPPORTED_INLINE_REVIEW_EXTENSIONS = {".md", ".markdown", ".txt", ".docx"}


def can_inline_review(ext: Optional[str]) -> bool:
    return (ext or "").lower() in SUPPORTED_INLINE_REVIEW_EXTENSIONS


def guess_ext_and_mime(file_name: Optional[str]) -> Tuple[str, str]:
    name = file_name or ""
    ext = os.path.splitext(name)[1].lower()
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    if ext == ".md" or ext == ".markdown":
        mime = "text/markdown"
    elif ext == ".txt":
        mime = "text/plain"
    elif ext == ".docx":
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif ext == ".pdf":
        mime = "application/pdf"
    return ext, mime


def decode_text_bytes(raw: bytes) -> str:
    if not raw:
        return ""
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return raw.decode(encoding)
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def parse_document_payload(file_name: str, raw: bytes) -> Dict[str, Any]:
    """任意上传文件 → {source_*, normalized_markdown, blocks_json, render_json}。"""
    ext, mime = guess_ext_and_mime(file_name)
    render_json: Dict[str, Any]
    if ext in {".md", ".markdown"}:
        markdown = decode_text_bytes(raw)
        blocks = markdown_blocks.markdown_to_blocks(markdown)
        render_json = {
            "format": "markdown",
            "block_count": len(blocks),
        }
    elif ext == ".txt":
        markdown = markdown_blocks.plain_text_to_markdown(decode_text_bytes(raw))
        blocks = markdown_blocks.markdown_to_blocks(markdown)
        render_json = {
            "format": "markdown",
            "block_count": len(blocks),
        }
    elif ext == ".docx":
        docx_payload = parse_docx_payload(raw)
        markdown = str(docx_payload.get("normalized_markdown") or "")
        blocks = list(docx_payload.get("blocks_json") or [])
        render_json = dict(docx_payload.get("render_json") or {})
    elif ext == ".pdf":
        markdown = ""
        blocks = []
        render_json = {
            "format": "markdown",
            "block_count": 0,
        }
    else:
        markdown = markdown_blocks.plain_text_to_markdown(decode_text_bytes(raw))
        blocks = markdown_blocks.markdown_to_blocks(markdown)
        render_json = {
            "format": "markdown",
            "block_count": len(blocks),
        }

    return {
        "source_file_name": file_name,
        "source_ext": ext,
        "source_mime": mime,
        "normalized_markdown": markdown,
        "blocks_json": blocks,
        "render_json": render_json,
    }
