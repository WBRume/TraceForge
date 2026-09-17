"""资产讨论线程的 prompt 构建工具。

纯函数集合：从文档块/线程消息中提取锚点与上下文文本，并把模型返回的
改写结果解析回结构化 payload。不含 DB 写入与 IO（``_resolve_context_version``
只读查询版本行）。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.domains.ai.services.jobs.constants import as_status
from app.domains.asset.models.asset import (
    AssetThreadMessageRole,
    SddAssetThread,
    SddAssetVersion,
)


def extract_block_text(block: Any) -> str:
    if not isinstance(block, dict):
        return ""
    text = str(block.get("text") or "").strip()
    if text:
        return text
    runs = block.get("runs")
    if isinstance(runs, list):
        merged = "".join(str(item.get("text") or "") for item in runs if isinstance(item, dict)).strip()
        if merged:
            return merged
    cells = block.get("cells")
    if isinstance(cells, list):
        chunks: List[str] = []
        for row in cells:
            if not isinstance(row, list):
                continue
            for cell in row:
                if isinstance(cell, dict):
                    cell_text = str(cell.get("text") or "").strip()
                    if cell_text:
                        chunks.append(cell_text)
        if chunks:
            return " | ".join(chunks)
    return ""


def resolve_thread_anchor_text(
    thread: SddAssetThread,
    block: Any,
    *,
    selected_text: Optional[str] = None,
    char_start: Optional[int] = None,
    char_end: Optional[int] = None,
) -> Dict[str, str]:
    block_text = extract_block_text(block).strip()
    selected_text = str(selected_text if selected_text is not None else thread.selected_text or "").strip()
    start_candidate = char_start if char_start is not None else thread.char_start
    end_candidate = char_end if char_end is not None else thread.char_end
    if block_text and start_candidate is not None and end_candidate is not None:
        try:
            start = int(start_candidate)
            end = int(end_candidate)
        except Exception:
            start, end = -1, -1
        if 0 <= start < end <= len(block_text):
            range_selected_text = block_text[start:end].strip()
            if range_selected_text and (not selected_text or selected_text == block_text):
                selected_text = range_selected_text
    anchor_text = selected_text or block_text
    return {
        "anchor_text": anchor_text,
        "block_text": block_text,
        "selected_text": selected_text,
    }


def thread_history_lines(thread: SddAssetThread, limit: int = 18) -> List[str]:
    messages = sorted(list(thread.messages or []), key=lambda item: item.created_at)
    lines: List[str] = []
    for message in messages[-limit:]:
        role = as_status(message.role)
        if role == AssetThreadMessageRole.AI.value:
            continue
        content = str(message.content or "").strip()
        if content:
            lines.append(f"[{role}] {content}")
    return lines


def proposal_discussion_lines(thread: SddAssetThread, limit: int = 28) -> List[str]:
    messages = sorted(list(thread.messages or []), key=lambda item: item.created_at)
    lines: List[str] = []
    for message in messages:
        role = as_status(message.role)
        if role not in {AssetThreadMessageRole.USER.value, AssetThreadMessageRole.AI.value}:
            continue
        content = str(message.content or "").strip()
        if not content:
            continue
        label = "成员" if role == AssetThreadMessageRole.USER.value else "AI"
        lines.append(f"[{label}] {content}")
    if len(lines) > limit:
        return lines[-limit:]
    return lines


def proposal_source_message_ids(thread: SddAssetThread) -> List[str]:
    messages = sorted(list(thread.messages or []), key=lambda item: item.created_at)
    return [
        item.id
        for item in messages
        if as_status(item.role) in {AssetThreadMessageRole.USER.value, AssetThreadMessageRole.AI.value}
        and str(item.content or "").strip()
    ]


def resolve_context_version(
    db: Session,
    *,
    thread: SddAssetThread,
    requested_version_id: Optional[str],
):
    version_id = str(requested_version_id or "").strip()
    if version_id:
        version = (
            db.query(SddAssetVersion)
            .filter(
                SddAssetVersion.id == version_id,
                SddAssetVersion.asset_id == thread.asset_id,
            )
            .first()
        )
        if version:
            return version
    if thread.asset and thread.asset.active_version_id:
        active_version = (
            db.query(SddAssetVersion)
            .filter(
                SddAssetVersion.id == thread.asset.active_version_id,
                SddAssetVersion.asset_id == thread.asset_id,
            )
            .first()
        )
        if active_version:
            return active_version
    return thread.version


def normalize_relocated_anchor(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    block_id = str(raw.get("block_id") or "").strip()
    if not block_id:
        return None
    selected_text = str(raw.get("selected_text") or "").strip() or None
    char_start = raw.get("char_start")
    char_end = raw.get("char_end")
    try:
        char_start = int(char_start) if char_start is not None else None
    except Exception:
        char_start = None
    try:
        char_end = int(char_end) if char_end is not None else None
    except Exception:
        char_end = None
    return {
        "block_id": block_id,
        "selected_text": selected_text,
        "char_start": char_start,
        "char_end": char_end,
    }


def serialize_proposal_for_ws(proposal: Any) -> Dict[str, Any]:
    status = proposal.status.value if hasattr(proposal.status, "value") else str(proposal.status)
    return {
        "id": proposal.id,
        "thread_id": proposal.thread_id,
        "base_version_id": proposal.base_version_id,
        "proposed_patch_json": proposal.proposed_patch_json,
        "diff_text": proposal.diff_text,
        "status": status,
        "creator_id": proposal.creator_id,
        "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
        "updated_at": proposal.updated_at.isoformat() if proposal.updated_at else None,
    }


def clean_rewrite_text(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].rstrip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def parse_rewrite_payload(raw: str) -> Dict[str, str]:
    text = str(raw or "").strip()
    if not text:
        return {"scope": "anchor", "anchor_text": ""}

    candidate = text
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].rstrip().startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()

    json_text = candidate
    if not (json_text.startswith("{") and json_text.endswith("}")):
        match = re.search(r"\{[\s\S]*\}", candidate)
        if match:
            json_text = match.group(0).strip()

    try:
        parsed = json.loads(json_text)
    except Exception:
        return {"scope": "anchor", "anchor_text": clean_rewrite_text(text)}

    if not isinstance(parsed, dict):
        return {"scope": "anchor", "anchor_text": clean_rewrite_text(text)}

    scope = str(parsed.get("scope") or parsed.get("rewrite_scope") or "anchor").strip().lower()
    if scope == "document":
        markdown = str(
            parsed.get("document_markdown")
            or parsed.get("markdown")
            or parsed.get("document")
            or ""
        ).strip()
        if markdown:
            return {"scope": "document", "document_markdown": markdown}

    anchor_text = str(
        parsed.get("anchor_text")
        or parsed.get("text")
        or parsed.get("rewritten_text")
        or ""
    ).strip()
    return {"scope": "anchor", "anchor_text": clean_rewrite_text(anchor_text or text)}
