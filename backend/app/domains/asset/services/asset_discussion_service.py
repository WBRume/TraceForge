"""
Asset discussion threads/messages service.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.domains.asset.models.asset import (
    AssetThreadMessageRole,
    AssetThreadStatus,
    SddAsset,
    SddAssetThreadAnchorMapping,
    SddAssetThread,
    SddAssetThreadMessage,
    SddAssetVersion,
)


def list_threads(
    db: Session,
    *,
    asset_id: str,
    version_id: Optional[str] = None,
) -> List[SddAssetThread]:
    query = (
        db.query(SddAssetThread)
        .options(
            joinedload(SddAssetThread.creator),
            joinedload(SddAssetThread.resolver),
            joinedload(SddAssetThread.messages).joinedload(SddAssetThreadMessage.creator),
            joinedload(SddAssetThread.proposals),
        )
        .filter(SddAssetThread.asset_id == asset_id)
    )
    if version_id:
        query = query.filter(SddAssetThread.version_id == version_id)
    return query.order_by(SddAssetThread.created_at.asc()).all()


def _extract_block_text(block: Any) -> str:
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


def get_thread_anchor_mapping(
    db: Session,
    *,
    thread_id: str,
    version_id: str,
) -> Optional[SddAssetThreadAnchorMapping]:
    return (
        db.query(SddAssetThreadAnchorMapping)
        .filter(
            SddAssetThreadAnchorMapping.thread_id == thread_id,
            SddAssetThreadAnchorMapping.version_id == version_id,
        )
        .first()
    )


def upsert_thread_anchor_mapping(
    db: Session,
    *,
    thread: SddAssetThread,
    version_id: str,
    block_id: str,
    selected_text: Optional[str] = None,
    char_start: Optional[int] = None,
    char_end: Optional[int] = None,
    actor_user_id: Optional[str] = None,
) -> SddAssetThreadAnchorMapping:
    resolved_block_id = str(block_id or "").strip() or str(thread.block_id or "").strip()
    if not resolved_block_id:
        version = (
            db.query(SddAssetVersion)
            .filter(SddAssetVersion.id == version_id)
            .first()
        )
        blocks = list(getattr(version, "blocks_json", []) or [])
        for item in blocks:
            if not isinstance(item, dict):
                continue
            candidate = str(item.get("id") or "").strip()
            if candidate:
                resolved_block_id = candidate
                break
    if not resolved_block_id:
        raise ValueError("Cannot upsert thread anchor mapping without block_id")

    resolved_actor_id = str(actor_user_id or "").strip() or str(thread.creator_id or "").strip() or None

    mapping = get_thread_anchor_mapping(db, thread_id=thread.id, version_id=version_id)
    if mapping is None:
        mapping = SddAssetThreadAnchorMapping(
            thread_id=thread.id,
            version_id=version_id,
            block_id=resolved_block_id,
            selected_text=(selected_text or "").strip() or None,
            char_start=char_start,
            char_end=char_end,
            created_by=resolved_actor_id,
        )
        db.add(mapping)
    else:
        mapping.block_id = resolved_block_id
        mapping.selected_text = (selected_text or "").strip() or None
        mapping.char_start = char_start
        mapping.char_end = char_end
        mapping.created_by = resolved_actor_id
    db.flush()
    return mapping


def resolve_thread_anchor_for_version(
    db: Session,
    *,
    thread: SddAssetThread,
    context_version: Optional[SddAssetVersion],
) -> Dict[str, Any]:
    anchor = {
        "block_id": str(thread.block_id or "").strip(),
        "selected_text": str(thread.selected_text or "").strip() or None,
        "char_start": thread.char_start,
        "char_end": thread.char_end,
        "source": "thread",
    }

    if context_version and str(context_version.id) != str(thread.version_id):
        mapping = get_thread_anchor_mapping(
            db,
            thread_id=thread.id,
            version_id=context_version.id,
        )
        if mapping:
            anchor = {
                "block_id": str(mapping.block_id or "").strip(),
                "selected_text": str(mapping.selected_text or "").strip() or None,
                "char_start": mapping.char_start,
                "char_end": mapping.char_end,
                "source": "mapping",
            }

    if not context_version:
        return {"anchor_status": "valid", "effective_anchor": anchor}

    block = get_block_by_id(context_version, anchor["block_id"])
    if not block:
        return {"anchor_status": "missing", "effective_anchor": anchor}

    block_text = _extract_block_text(block)
    selected_text = str(anchor.get("selected_text") or "").strip()
    if selected_text and selected_text not in block_text:
        return {"anchor_status": "missing", "effective_anchor": anchor}

    start = anchor.get("char_start")
    end = anchor.get("char_end")
    if start is not None or end is not None:
        try:
            s = int(start) if start is not None else None
            e = int(end) if end is not None else None
        except Exception:
            s = None
            e = None
        if s is None or e is None or s < 0 or e < s or e > len(block_text):
            return {"anchor_status": "missing", "effective_anchor": anchor}
        if selected_text:
            extracted = block_text[s:e].strip()
            if extracted and extracted != selected_text:
                return {"anchor_status": "missing", "effective_anchor": anchor}

    enriched_anchor = {
        **anchor,
        "block_text": block_text,
    }
    return {"anchor_status": "valid", "effective_anchor": enriched_anchor}


def list_thread_markers(
    db: Session,
    *,
    asset_id: str,
    version_id: str,
) -> List[Dict[str, Any]]:
    context_version = (
        db.query(SddAssetVersion)
        .filter(SddAssetVersion.id == version_id, SddAssetVersion.asset_id == asset_id)
        .first()
    )
    rows = (
        db.query(SddAssetThread)
        .options(joinedload(SddAssetThread.messages))
        .filter(SddAssetThread.asset_id == asset_id)
        .order_by(SddAssetThread.created_at.asc())
        .all()
    )
    markers: List[Dict[str, Any]] = []
    for row in rows:
        anchor_eval = resolve_thread_anchor_for_version(
            db,
            thread=row,
            context_version=context_version,
        )
        if anchor_eval.get("anchor_status") != "valid":
            continue
        effective_anchor = anchor_eval.get("effective_anchor") or {}
        block_id = str(effective_anchor.get("block_id") or "").strip()
        if not block_id:
            continue
        status = row.status.value if hasattr(row.status, "value") else row.status
        markers.append(
            {
                "thread_id": row.id,
                "block_id": block_id,
                "selected_text": effective_anchor.get("selected_text"),
                "char_start": effective_anchor.get("char_start"),
                "char_end": effective_anchor.get("char_end"),
                "status": status,
                "creator_id": row.creator_id,
                "created_at": row.created_at,
                "message_count": len(list(row.messages or [])),
            }
        )
    return markers


def get_thread(
    db: Session,
    *,
    asset_id: str,
    thread_id: str,
) -> Optional[SddAssetThread]:
    return (
        db.query(SddAssetThread)
        .options(
            joinedload(SddAssetThread.creator),
            joinedload(SddAssetThread.resolver),
            joinedload(SddAssetThread.messages).joinedload(SddAssetThreadMessage.creator),
            joinedload(SddAssetThread.proposals),
        )
        .filter(
            SddAssetThread.asset_id == asset_id,
            SddAssetThread.id == thread_id,
        )
        .first()
    )


def create_thread(
    db: Session,
    *,
    asset: SddAsset,
    version: SddAssetVersion,
    creator_id: str,
    block_id: str,
    body: str,
    selected_text: Optional[str] = None,
    char_start: Optional[int] = None,
    char_end: Optional[int] = None,
) -> SddAssetThread:
    normalized_body = (body or "").strip()
    if not block_id.strip():
        raise ValueError("block_id is required")
    if not normalized_body:
        raise ValueError("Thread body is required")
    if char_start is not None and char_end is not None and char_end < char_start:
        raise ValueError("char_end must be greater than or equal to char_start")

    thread = SddAssetThread(
        asset_id=asset.id,
        version_id=version.id,
        task_id=asset.task_id,
        workspace_id=asset.workspace_id,
        block_id=block_id.strip(),
        selected_text=(selected_text or None),
        char_start=char_start,
        char_end=char_end,
        status=AssetThreadStatus.OPEN,
        creator_id=creator_id,
    )
    db.add(thread)
    db.flush()

    message = SddAssetThreadMessage(
        thread_id=thread.id,
        role=AssetThreadMessageRole.USER,
        content=normalized_body,
        creator_id=creator_id,
    )
    db.add(message)
    db.flush()
    return thread


def add_thread_message(
    db: Session,
    *,
    thread: SddAssetThread,
    role: AssetThreadMessageRole,
    content: str,
    creator_id: Optional[str] = None,
    metadata_json: Optional[Dict[str, Any]] = None,
) -> SddAssetThreadMessage:
    if thread.status in {AssetThreadStatus.RESOLVED, AssetThreadStatus.CLOSED}:
        raise ValueError("Thread is not open for new messages")
    normalized_content = (content or "").strip()
    if not normalized_content:
        raise ValueError("Message content is required")
    message = SddAssetThreadMessage(
        thread_id=thread.id,
        role=role,
        content=normalized_content,
        creator_id=creator_id,
        metadata_json=metadata_json,
    )
    db.add(message)
    db.flush()
    return message


def set_thread_status(
    db: Session,
    *,
    thread: SddAssetThread,
    status: AssetThreadStatus,
    actor_user_id: Optional[str] = None,
    resolved_version_id: Optional[str] = None,
) -> SddAssetThread:
    thread.status = status
    if status in {AssetThreadStatus.RESOLVED, AssetThreadStatus.CLOSED}:
        thread.resolved_at = datetime.utcnow()
        thread.resolved_by = actor_user_id
        if resolved_version_id:
            thread.resolved_version_id = resolved_version_id
    else:
        thread.resolved_at = None
        thread.resolved_by = None
        thread.resolved_version_id = None
    db.flush()
    return thread


def set_thread_close_hint(
    db: Session,
    *,
    thread: SddAssetThread,
    state: str,
    reason: Optional[str] = None,
    version_id: Optional[str] = None,
) -> SddAssetThread:
    normalized_state = str(state or "none").strip().lower()
    if normalized_state not in {"none", "pending", "no_close_needed"}:
        normalized_state = "none"
    thread.close_hint_state = normalized_state
    thread.close_hint_reason = str(reason or "").strip() or None
    thread.close_hint_version_id = str(version_id or "").strip() or None
    db.flush()
    return thread


def get_block_by_id(version: SddAssetVersion, block_id: str) -> Optional[Dict[str, Any]]:
    blocks = version.blocks_json or []
    if not isinstance(blocks, list):
        return None
    for block in blocks:
        if isinstance(block, dict) and str(block.get("id")) == str(block_id):
            return block
    return None


def get_block_context(version: SddAssetVersion, block_id: str, window: int = 1) -> Dict[str, Any]:
    blocks = version.blocks_json or []
    if not isinstance(blocks, list):
        return {"selected": None, "neighbors": []}

    selected_index = -1
    for idx, block in enumerate(blocks):
        if isinstance(block, dict) and str(block.get("id")) == str(block_id):
            selected_index = idx
            break
    if selected_index < 0:
        return {"selected": None, "neighbors": []}

    start = max(0, selected_index - window)
    end = min(len(blocks), selected_index + window + 1)
    selected = blocks[selected_index]
    neighbors = [blocks[idx] for idx in range(start, end) if idx != selected_index]
    return {"selected": selected, "neighbors": neighbors}


def _coerce_optional_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def sync_docx_comments_to_threads(
    db: Session,
    *,
    asset: SddAsset,
    version: SddAssetVersion,
    actor_user_id: Optional[str] = None,
) -> int:
    render_json = version.render_json or {}
    raw_comments = render_json.get("docx_comments")
    if not isinstance(raw_comments, list) or not raw_comments:
        return 0

    existing_threads = list_threads(db, asset_id=asset.id, version_id=version.id)
    imported_comment_ids = set()
    for thread in existing_threads:
        for message in list(thread.messages or []):
            metadata = message.metadata_json or {}
            if not isinstance(metadata, dict):
                continue
            comment_id = str(metadata.get("docx_comment_id") or "").strip()
            if comment_id:
                imported_comment_ids.add(comment_id)

    created = 0
    creator_id = actor_user_id or asset.creator_id
    for entry in raw_comments:
        if not isinstance(entry, dict):
            continue
        comment_id = str(entry.get("comment_id") or "").strip()
        block_id = str(entry.get("block_id") or "").strip()
        if not comment_id or not block_id:
            continue
        if comment_id in imported_comment_ids:
            continue

        selected_text = str(entry.get("selected_text") or "").strip() or None
        char_start = _coerce_optional_int(entry.get("char_start"))
        char_end = _coerce_optional_int(entry.get("char_end"))
        if char_start is not None and char_end is not None and char_end < char_start:
            char_start = None
            char_end = None

        thread = SddAssetThread(
            asset_id=asset.id,
            version_id=version.id,
            task_id=asset.task_id,
            workspace_id=asset.workspace_id,
            block_id=block_id,
            selected_text=selected_text,
            char_start=char_start,
            char_end=char_end,
            status=AssetThreadStatus.OPEN,
            creator_id=creator_id,
        )
        db.add(thread)
        db.flush()

        comment_content = str(entry.get("content") or "").strip() or "（DOCX 批注为空）"
        author = str(entry.get("author") or "").strip()
        initials = str(entry.get("initials") or "").strip()
        date = str(entry.get("date") or "").strip()
        author_display = author or "未知作者"
        if initials:
            author_display = f"{author_display}({initials})"
        content = f"导入自 DOCX 批注 [{author_display}]：{comment_content}"

        metadata_json = {
            "source": "docx_comment_import",
            "docx_comment_id": comment_id,
            "author": author or None,
            "initials": initials or None,
            "date": date or None,
        }
        message = SddAssetThreadMessage(
            thread_id=thread.id,
            role=AssetThreadMessageRole.SYSTEM,
            content=content,
            creator_id=None,
            metadata_json=metadata_json,
        )
        db.add(message)
        db.flush()

        imported_comment_ids.add(comment_id)
        created += 1

    return created
