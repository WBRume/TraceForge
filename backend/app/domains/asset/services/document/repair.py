"""DOCX 版本内容修复：检测损坏/二进制残留的历史版本并重建。"""

from __future__ import annotations

import os
from typing import List

from sqlalchemy.orm import Session

from app.domains.asset.models.asset import SddAsset, SddAssetVersion
from app.domains.asset.services.document.docx import build_docx_bytes, looks_like_docx_bytes
from app.domains.asset.services.document.payload import parse_document_payload


def _looks_like_binary_docx_dump(text: str) -> bool:
    """历史版本正文若为二进制 docx 直接解码的产物，则视为损坏。"""
    if not text:
        return False
    if text.startswith("PK") and ("word/" in text or "[Content_Types].xml" in text):
        return True
    control_count = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\r\t")
    return control_count > max(8, len(text) // 200)


def repair_docx_version_if_needed(db: Session, asset: SddAsset, version: SddAssetVersion) -> bool:
    """修复内容损坏的 DOCX 版本；成功重建时同步资产激活快照。"""
    ext = (version.original_ext or asset.source_ext or "").lower()
    if ext != ".docx":
        return False

    markdown = version.normalized_markdown or ""
    blocks: List = list(version.blocks_json or []) if isinstance(version.blocks_json, list) else []
    render = version.render_json or {}
    render_format = str(render.get("format") or "").strip().lower()
    has_docx_comment_payload = isinstance(render.get("docx_comments"), list)
    needs_repair = (
        (not blocks)
        or _looks_like_binary_docx_dump(markdown)
        or render_format != "rich_doc"
        or (has_docx_comment_payload is False)
    )

    original_path = (version.original_path or "").strip()
    if not original_path or not os.path.isfile(original_path):
        return False

    try:
        with open(original_path, "rb") as f:
            raw = f.read()
    except Exception:
        return False

    original_docx_valid = looks_like_docx_bytes(raw)
    needs_repair = needs_repair or (not original_docx_valid)
    if not needs_repair:
        return False

    if not original_docx_valid:
        rebuilt = build_docx_bytes(blocks, markdown)
        if rebuilt:
            try:
                with open(original_path, "wb") as f:
                    f.write(rebuilt)
                raw = rebuilt
                original_docx_valid = True
            except Exception:
                pass

    repaired_payload = parse_document_payload(
        version.original_path or asset.source_file_name or "document.docx",
        raw,
    )
    repaired_markdown = str(repaired_payload.get("normalized_markdown") or "")
    repaired_blocks = list(repaired_payload.get("blocks_json") or [])
    repaired_render = dict(repaired_payload.get("render_json") or {})
    if not repaired_markdown and not repaired_blocks:
        return False

    version.normalized_markdown = repaired_markdown
    version.blocks_json = repaired_blocks
    version.render_json = repaired_render or {
        "format": "rich_doc",
        "block_count": len(repaired_blocks),
        "docx_comments": [],
    }

    if asset.active_version_id == version.id:
        asset.content_text = repaired_markdown
        asset.content_json = {
            "active_version_no": version.version_no,
            "block_count": len(repaired_blocks),
        }

    db.flush()
    return True
