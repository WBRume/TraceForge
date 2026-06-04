"""Context-window token attribution persistence and aggregation.

The tables in this service are a lightweight attribution ledger: they store
usage numbers, source references, content hashes, counts, and short previews.
They deliberately do not persist full prompt, tool result, or document bodies.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domains.ai.models.ai_job import SddAiJob
from app.domains.asset.models.asset import AssetType, SddAsset, SddAssetVersion
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.context_token import (
    ContextTokenCategory,
    SddContextTokenSegment,
    SddContextTokenSnapshot,
)
from app.domains.skill.models.skill import SddSkillRuntimeEvent, SkillRuntimeEventType
from app.domains.task.models.task import SddTask
from app.domains.task.services import context_compaction_service


logger = get_logger(__name__, category="task_execution")

PREVIEW_LIMIT = 500
SEGMENT_PAGE_LIMIT = 100
HISTORY_LIMIT = 200
SOURCE_KIND_LIMIT = 80
SOURCE_REF_LIMIT = 120
TITLE_LIMIT = 300
TOOL_USE_ID_LIMIT = 200

PROVIDER_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "thinking_tokens",
    "tool_io_tokens",
    "total_tokens",
)

SUPERPOWERS_DOC_ROOT_CANDIDATES = (
    ("docs", "superpowers"),
    ("superpowers", "docs", "superpowers"),
)
SUPERPOWERS_EXTENSIONS = {".md", ".markdown"}


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def _coerce_category(value: Any) -> ContextTokenCategory:
    if isinstance(value, ContextTokenCategory):
        return value
    normalized = str(value or "").strip().upper()
    try:
        return ContextTokenCategory(normalized)
    except ValueError as exc:
        raise ValueError(f"Unsupported context token category: {value}") from exc


def _clip(value: Any, limit: int) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:limit]


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
    except Exception:
        return str(value)


def _preview(text: str) -> str:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) <= PREVIEW_LIMIT:
        return normalized
    return f"{normalized[:PREVIEW_LIMIT]}..."


def _content_hash(text: str) -> Optional[str]:
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _text_stats(content: Any) -> Tuple[str, int, int, Optional[str], Optional[str]]:
    text = _json_text(content)
    char_count = len(text)
    byte_count = len(text.encode("utf-8", errors="ignore"))
    return text, char_count, byte_count, _content_hash(text), _preview(text)


def _json_safe_metadata(value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    safe: Dict[str, Any] = {}
    for key, child in value.items():
        if child is None or isinstance(child, (bool, int, float)):
            safe[str(key)] = child
            continue
        if isinstance(child, str):
            safe[str(key)] = child[:300]
            continue
        if isinstance(child, list):
            safe[str(key)] = [
                item if item is None or isinstance(item, (bool, int, float)) else str(item)[:160]
                for item in child[:40]
            ]
            continue
        if isinstance(child, dict):
            safe[str(key)] = {
                str(k): (v if v is None or isinstance(v, (bool, int, float)) else str(v)[:160])
                for k, v in list(child.items())[:40]
            }
            continue
        safe[str(key)] = str(child)[:160]
    return safe


def _safe_locator(value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return _json_safe_metadata(value)


def _token_value(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _snapshot_status(status: Any) -> str:
    text = _enum_value(status).strip()
    return text[:40] if text else "PENDING"


def ensure_snapshot(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    ai_job_id: Optional[str] = None,
    session_id: Optional[str] = None,
    model: Optional[str] = None,
    status: Optional[str] = None,
) -> SddContextTokenSnapshot:
    normalized_job_id = str(ai_job_id or "").strip() or None
    snapshot = None
    if normalized_job_id:
        snapshot = (
            db.query(SddContextTokenSnapshot)
            .filter(SddContextTokenSnapshot.ai_job_id == normalized_job_id)
            .first()
        )
    if snapshot is None and session_id:
        snapshot = (
            db.query(SddContextTokenSnapshot)
            .filter(
                SddContextTokenSnapshot.task_id == task_id,
                SddContextTokenSnapshot.session_id == str(session_id).strip(),
            )
            .order_by(SddContextTokenSnapshot.created_at.desc(), SddContextTokenSnapshot.id.desc())
            .first()
        )
    if snapshot is None:
        snapshot = SddContextTokenSnapshot(
            workspace_id=workspace_id,
            task_id=task_id,
            ai_job_id=normalized_job_id,
            session_id=_clip(session_id, 120),
            model=_clip(model, 120),
            status=_snapshot_status(status),
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)
        return snapshot

    dirty = False
    if normalized_job_id and not snapshot.ai_job_id:
        snapshot.ai_job_id = normalized_job_id
        dirty = True
    if session_id and snapshot.session_id != str(session_id).strip():
        snapshot.session_id = _clip(session_id, 120)
        dirty = True
    if model and snapshot.model != str(model).strip():
        snapshot.model = _clip(model, 120)
        dirty = True
    if status and snapshot.status != _snapshot_status(status):
        snapshot.status = _snapshot_status(status)
        dirty = True
    if dirty:
        db.commit()
        db.refresh(snapshot)
    return snapshot


def ensure_snapshot_for_job(
    db: Session,
    job: SddAiJob,
    *,
    model: Optional[str] = None,
    status: Optional[str] = None,
) -> SddContextTokenSnapshot:
    return ensure_snapshot(
        db,
        workspace_id=job.workspace_id,
        task_id=str(job.task_id or ""),
        ai_job_id=job.id,
        session_id=job.session_id,
        model=model,
        status=status or _enum_value(job.status),
    )


def find_snapshot(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    ai_job_id: Optional[str] = None,
) -> Optional[SddContextTokenSnapshot]:
    query = db.query(SddContextTokenSnapshot).filter(
        SddContextTokenSnapshot.workspace_id == workspace_id,
        SddContextTokenSnapshot.task_id == task_id,
    )
    normalized_job_id = str(ai_job_id or "").strip()
    if normalized_job_id:
        query = query.filter(SddContextTokenSnapshot.ai_job_id == normalized_job_id)
    return query.order_by(SddContextTokenSnapshot.created_at.desc(), SddContextTokenSnapshot.id.desc()).first()


def _existing_segment(
    db: Session,
    *,
    snapshot_id: str,
    category: ContextTokenCategory,
    source_kind: str,
    source_ref_id: Optional[str] = None,
    tool_use_id: Optional[str] = None,
    content_hash: Optional[str] = None,
) -> Optional[SddContextTokenSegment]:
    query = db.query(SddContextTokenSegment).filter(
        SddContextTokenSegment.snapshot_id == snapshot_id,
        SddContextTokenSegment.category == category,
        SddContextTokenSegment.source_kind == source_kind,
    )
    if source_ref_id:
        query = query.filter(SddContextTokenSegment.source_ref_id == source_ref_id)
    if tool_use_id:
        query = query.filter(SddContextTokenSegment.tool_use_id == tool_use_id)
    if content_hash:
        query = query.filter(SddContextTokenSegment.content_hash == content_hash)
    return query.first()


def record_segment(
    db: Session,
    *,
    snapshot: SddContextTokenSnapshot,
    category: Any,
    source_kind: str,
    content: Any = None,
    provider_tokens: Optional[int] = None,
    attribution_units: Optional[int] = None,
    source_ref_id: Optional[str] = None,
    chat_message_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    asset_version_id: Optional[str] = None,
    skill_runtime_event_id: Optional[str] = None,
    tool_use_id: Optional[str] = None,
    locator_json: Optional[Dict[str, Any]] = None,
    title: Optional[str] = None,
    preview: Optional[str] = None,
    metadata_json: Optional[Dict[str, Any]] = None,
    dedupe: bool = False,
) -> SddContextTokenSegment:
    category_value = _coerce_category(category)
    text, char_count, byte_count, content_hash, generated_preview = _text_stats(content)
    final_preview = _preview(preview if preview is not None else generated_preview)
    if preview is None and not final_preview and title:
        final_preview = _preview(str(title))
    units = _token_value(attribution_units)
    if units is None:
        units = char_count

    normalized_source_kind = _clip(source_kind, SOURCE_KIND_LIMIT) or "unknown"
    normalized_source_ref_id = _clip(source_ref_id, SOURCE_REF_LIMIT)
    normalized_tool_use_id = _clip(tool_use_id, TOOL_USE_ID_LIMIT)

    if dedupe:
        existing = _existing_segment(
            db,
            snapshot_id=snapshot.id,
            category=category_value,
            source_kind=normalized_source_kind,
            source_ref_id=normalized_source_ref_id,
            tool_use_id=normalized_tool_use_id,
            content_hash=content_hash,
        )
        if existing:
            return existing

    row = SddContextTokenSegment(
        snapshot_id=snapshot.id,
        workspace_id=snapshot.workspace_id,
        task_id=snapshot.task_id,
        ai_job_id=snapshot.ai_job_id,
        category=category_value,
        provider_tokens=_token_value(provider_tokens),
        attribution_units=int(units or 0),
        char_count=int(char_count or 0),
        byte_count=int(byte_count or 0),
        source_kind=normalized_source_kind,
        source_ref_id=normalized_source_ref_id,
        chat_message_id=_clip(chat_message_id, 36),
        asset_id=_clip(asset_id, 36),
        asset_version_id=_clip(asset_version_id, 36),
        skill_runtime_event_id=_clip(skill_runtime_event_id, 36),
        tool_use_id=normalized_tool_use_id,
        content_hash=content_hash,
        locator_json=_safe_locator(locator_json),
        title=_clip(title, TITLE_LIMIT),
        preview=final_preview[:600] if final_preview else None,
        metadata_json=_json_safe_metadata(metadata_json),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_snapshot_usage(
    db: Session,
    *,
    snapshot: Optional[SddContextTokenSnapshot] = None,
    workspace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    ai_job_id: Optional[str] = None,
    session_id: Optional[str] = None,
    usage: Optional[Dict[str, Any]] = None,
    model: Optional[str] = None,
    status: Optional[str] = None,
    duration_ms: Optional[int] = None,
    total_cost_usd: Optional[float] = None,
    raw_usage_json: Any = None,
) -> Optional[SddContextTokenSnapshot]:
    if snapshot is None:
        if not workspace_id or not task_id:
            return None
        snapshot = ensure_snapshot(
            db,
            workspace_id=workspace_id,
            task_id=task_id,
            ai_job_id=ai_job_id,
            session_id=session_id,
            model=model,
            status=status,
        )

    normalized_usage = usage if isinstance(usage, dict) else {}
    has_provider_usage = any(_token_value(normalized_usage.get(field)) is not None for field in PROVIDER_TOKEN_FIELDS)
    for field in PROVIDER_TOKEN_FIELDS:
        value = _token_value(normalized_usage.get(field))
        if value is not None:
            setattr(snapshot, field, value)

    if snapshot.total_tokens is None and has_provider_usage:
        parts = [
            snapshot.input_tokens,
            snapshot.output_tokens,
            snapshot.cache_read_tokens,
            snapshot.cache_creation_tokens,
            snapshot.thinking_tokens,
            snapshot.tool_io_tokens,
        ]
        known = [int(value) for value in parts if value is not None]
        if known:
            snapshot.total_tokens = sum(known)

    if model:
        snapshot.model = _clip(model, 120)
    if status:
        snapshot.status = _snapshot_status(status)
    if duration_ms is not None:
        snapshot.duration_ms = _token_value(duration_ms)
    if total_cost_usd is not None:
        try:
            snapshot.total_cost_usd = float(total_cost_usd)
        except (TypeError, ValueError):
            pass
    if raw_usage_json is not None:
        snapshot.raw_usage_json = raw_usage_json
    elif normalized_usage.get("raw_usage") is not None:
        snapshot.raw_usage_json = normalized_usage.get("raw_usage")

    db.commit()
    db.refresh(snapshot)
    return snapshot


def record_task_prompt(
    db: Session,
    *,
    snapshot: SddContextTokenSnapshot,
    prompt_text: str,
    chat_message_id: Optional[str] = None,
) -> SddContextTokenSegment:
    return record_segment(
        db,
        snapshot=snapshot,
        category=ContextTokenCategory.TASK_PROMPT,
        source_kind="task_prompt",
        source_ref_id=chat_message_id or snapshot.ai_job_id,
        chat_message_id=chat_message_id,
        content=prompt_text,
        title="Task Prompt",
        metadata_json={"ai_job_id": snapshot.ai_job_id},
        dedupe=True,
    )


def record_existing_history(
    db: Session,
    *,
    snapshot: SddContextTokenSnapshot,
    exclude_chat_message_id: Optional[str] = None,
) -> None:
    rows = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.workspace_id == snapshot.workspace_id,
            ChatMessage.task_id == snapshot.task_id,
        )
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(HISTORY_LIMIT)
        .all()
    )
    for message in reversed(rows):
        if exclude_chat_message_id and message.id == exclude_chat_message_id:
            continue
        record_chat_message(
            db,
            snapshot=snapshot,
            message=message,
            category=ContextTokenCategory.HISTORY,
        )


def record_chat_message(
    db: Session,
    *,
    snapshot: SddContextTokenSnapshot,
    message: ChatMessage,
    category: ContextTokenCategory = ContextTokenCategory.HISTORY,
) -> SddContextTokenSegment:
    role = _enum_value(message.role)
    msg_type = _enum_value(message.message_type)
    return record_segment(
        db,
        snapshot=snapshot,
        category=category,
        source_kind="chat_message",
        source_ref_id=message.id,
        chat_message_id=message.id,
        content=message.content,
        title=f"{role or 'chat'} / {msg_type or 'text'}",
        metadata_json={
            "role": role,
            "message_type": msg_type,
            "creator_id": message.creator_id,
        },
        dedupe=True,
    )


def _latest_asset_version(db: Session, asset: SddAsset) -> Optional[SddAssetVersion]:
    if asset.active_version_id:
        version = db.query(SddAssetVersion).filter(SddAssetVersion.id == asset.active_version_id).first()
        if version:
            return version
    return (
        db.query(SddAssetVersion)
        .filter(SddAssetVersion.asset_id == asset.id)
        .order_by(SddAssetVersion.version_no.desc(), SddAssetVersion.created_at.desc())
        .first()
    )


def record_spec_docs_from_task(db: Session, *, snapshot: SddContextTokenSnapshot, task: SddTask) -> None:
    assets = (
        db.query(SddAsset)
        .filter(
            SddAsset.workspace_id == task.workspace_id,
            SddAsset.task_id == task.id,
            SddAsset.asset_type == AssetType.SPEC,
        )
        .order_by(SddAsset.created_at.desc())
        .limit(20)
        .all()
    )
    for asset in assets:
        version = _latest_asset_version(db, asset)
        content = asset.content_text or (version.normalized_markdown if version else "") or ""
        record_segment(
            db,
            snapshot=snapshot,
            category=ContextTokenCategory.SPEC_DOCS,
            source_kind="asset",
            source_ref_id=asset.id,
            asset_id=asset.id,
            asset_version_id=version.id if version else None,
            content=content,
            title=asset.name,
            locator_json={
                "asset_type": _enum_value(asset.asset_type),
                "source_file_name": asset.source_file_name,
                "version_no": version.version_no if version else None,
            },
            metadata_json={"active_version_id": asset.active_version_id},
            dedupe=True,
        )
    if not assets and task.spec_doc_path:
        record_segment(
            db,
            snapshot=snapshot,
            category=ContextTokenCategory.SPEC_DOCS,
            source_kind="spec_path",
            source_ref_id=task.spec_doc_path,
            content="",
            attribution_units=0,
            title=os.path.basename(task.spec_doc_path),
            preview=task.spec_doc_path,
            locator_json={"path": task.spec_doc_path},
            dedupe=True,
        )


def _iter_superpowers_docs(task: SddTask) -> Iterable[Path]:
    project_path = Path(str(task.project_path or ".")).resolve()
    candidates = [project_path / "CLAUDE.md", project_path / ".claude" / "CLAUDE.md"]
    for root_parts in SUPERPOWERS_DOC_ROOT_CANDIDATES:
        root = project_path.joinpath(*root_parts)
        if root.exists() and root.is_dir():
            for path in root.rglob("*"):
                if path.is_file() and path.suffix.lower() in SUPERPOWERS_EXTENSIONS:
                    candidates.append(path)
    seen: set[str] = set()
    for path in candidates:
        try:
            resolved = str(path.resolve())
        except OSError:
            continue
        if resolved in seen or not path.exists() or not path.is_file():
            continue
        seen.add(resolved)
        yield path


def record_superpowers_rules_from_task(db: Session, *, snapshot: SddContextTokenSnapshot, task: SddTask) -> None:
    project_path = Path(str(task.project_path or ".")).resolve()
    for path in _iter_superpowers_docs(task):
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            content = ""
        try:
            relative_path = str(path.resolve().relative_to(project_path)).replace("\\", "/")
        except (OSError, ValueError):
            relative_path = str(path)
        record_segment(
            db,
            snapshot=snapshot,
            category=ContextTokenCategory.SUPERPOWERS_RULES,
            source_kind="project_rule_file",
            source_ref_id=relative_path,
            content=content,
            title=relative_path,
            locator_json={"path": relative_path},
            dedupe=True,
        )


def seed_snapshot_for_job(
    db: Session,
    *,
    job: SddAiJob,
    prompt_text: str,
    chat_message_id: Optional[str] = None,
) -> SddContextTokenSnapshot:
    snapshot = ensure_snapshot_for_job(db, job)
    task = db.query(SddTask).filter(SddTask.id == job.task_id, SddTask.workspace_id == job.workspace_id).first()
    record_task_prompt(db, snapshot=snapshot, prompt_text=prompt_text, chat_message_id=chat_message_id)
    record_existing_history(db, snapshot=snapshot, exclude_chat_message_id=chat_message_id)
    if task:
        record_spec_docs_from_task(db, snapshot=snapshot, task=task)
        record_superpowers_rules_from_task(db, snapshot=snapshot, task=task)
    return snapshot


def record_tool_input(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    ai_job_id: Optional[str],
    session_id: Optional[str],
    tool_name: str,
    tool_input: Any,
    tool_use_id: str,
) -> Optional[SddContextTokenSegment]:
    snapshot = ensure_snapshot(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        ai_job_id=ai_job_id,
        session_id=session_id,
        status="RUNNING",
    )
    input_text = _json_text(tool_input)
    input_keys = list(tool_input.keys())[:50] if isinstance(tool_input, dict) else None
    return record_segment(
        db,
        snapshot=snapshot,
        category=ContextTokenCategory.TOOL_INPUT,
        source_kind="tool_use",
        source_ref_id=tool_use_id,
        tool_use_id=tool_use_id,
        content=input_text,
        title=str(tool_name or "tool"),
        metadata_json={"tool_name": tool_name, "input_keys": input_keys},
        dedupe=True,
    )


def record_tool_result(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    ai_job_id: Optional[str],
    session_id: Optional[str],
    tool_use_id: str,
    output: Any,
    is_error: bool = False,
) -> Optional[SddContextTokenSegment]:
    snapshot = ensure_snapshot(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        ai_job_id=ai_job_id,
        session_id=session_id,
        status="RUNNING",
    )
    has_runtime_skill_evidence = (
        db.query(SddSkillRuntimeEvent.id)
        .filter(
            SddSkillRuntimeEvent.task_id == task_id,
            SddSkillRuntimeEvent.tool_use_id == str(tool_use_id or "").strip(),
            SddSkillRuntimeEvent.event_type != SkillRuntimeEventType.TOOL_RESULT,
        )
        .first()
        is not None
    )
    return record_segment(
        db,
        snapshot=snapshot,
        category=ContextTokenCategory.RUNTIME_SKILLS if has_runtime_skill_evidence else ContextTokenCategory.TOOL_RESULT,
        source_kind="runtime_skill_tool_result" if has_runtime_skill_evidence else "tool_result",
        source_ref_id=tool_use_id,
        tool_use_id=tool_use_id,
        content=output,
        title="Tool Result",
        metadata_json={"is_error": bool(is_error)},
        dedupe=False,
    )


def record_thinking(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    ai_job_id: Optional[str],
    session_id: Optional[str],
    content: str,
) -> Optional[SddContextTokenSegment]:
    snapshot = ensure_snapshot(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        ai_job_id=ai_job_id,
        session_id=session_id,
        status="RUNNING",
    )
    return record_segment(
        db,
        snapshot=snapshot,
        category=ContextTokenCategory.THINKING,
        source_kind="assistant_thinking",
        source_ref_id=ai_job_id,
        content=content,
        title="Thinking",
        dedupe=False,
    )


def record_hitl(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    ai_job_id: Optional[str],
    session_id: Optional[str],
    prompt: str,
    response: Optional[str] = None,
    source_kind: str = "hitl_prompt",
) -> Optional[SddContextTokenSegment]:
    snapshot = ensure_snapshot(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        ai_job_id=ai_job_id,
        session_id=session_id,
        status="WAITING_HITL" if response is None else "RUNNING",
    )
    content = prompt if response is None else f"{prompt}\n{response}"
    return record_segment(
        db,
        snapshot=snapshot,
        category=ContextTokenCategory.HITL,
        source_kind=source_kind,
        source_ref_id=ai_job_id,
        content=content,
        title="HITL",
        metadata_json={"has_response": response is not None},
        dedupe=False,
    )


def record_runtime_skill_event(
    db: Session,
    event: SddSkillRuntimeEvent,
    *,
    content: Any = None,
) -> Optional[SddContextTokenSegment]:
    snapshot = ensure_snapshot(
        db,
        workspace_id=event.workspace_id,
        task_id=event.task_id,
        ai_job_id=event.ai_job_id,
        status="RUNNING",
    )
    event_type = _enum_value(event.event_type)
    source_ref = event.id
    content_value = content
    if content_value is None:
        content_value = event.tool_result_preview or event.matched_path or event.relative_path or event.materialized_dir or ""
    return record_segment(
        db,
        snapshot=snapshot,
        category=ContextTokenCategory.RUNTIME_SKILLS,
        source_kind="runtime_skill_event",
        source_ref_id=source_ref,
        skill_runtime_event_id=event.id,
        tool_use_id=event.tool_use_id,
        content=content_value,
        title=event.relative_path or event.materialized_dir or event_type,
        locator_json={
            "event_type": event_type,
            "materialized_dir": event.materialized_dir,
            "relative_path": event.relative_path,
            "matched_path": event.matched_path,
        },
        metadata_json={"skill_id": event.skill_id, "tool_name": event.tool_name},
        dedupe=True,
    )


def promote_tool_result_to_runtime_skill(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    ai_job_id: Optional[str],
    tool_use_id: str,
    runtime_event_ids: Optional[List[str]] = None,
    preview: Optional[str] = None,
) -> None:
    normalized_tool_use_id = str(tool_use_id or "").strip()
    if not normalized_tool_use_id:
        return
    snapshot = find_snapshot(db, workspace_id=workspace_id, task_id=task_id, ai_job_id=ai_job_id)
    if not snapshot:
        snapshot = ensure_snapshot(
            db,
            workspace_id=workspace_id,
            task_id=task_id,
            ai_job_id=ai_job_id,
            status="RUNNING",
        )
    runtime_ids = [str(value) for value in (runtime_event_ids or []) if str(value or "").strip()]
    segment = (
        db.query(SddContextTokenSegment)
        .filter(
            SddContextTokenSegment.snapshot_id == snapshot.id,
            SddContextTokenSegment.tool_use_id == normalized_tool_use_id,
            SddContextTokenSegment.category == ContextTokenCategory.TOOL_RESULT,
        )
        .order_by(SddContextTokenSegment.created_at.desc(), SddContextTokenSegment.id.desc())
        .first()
    )
    if segment:
        segment.category = ContextTokenCategory.RUNTIME_SKILLS
        segment.source_kind = "runtime_skill_tool_result"
        if runtime_ids:
            segment.skill_runtime_event_id = runtime_ids[0]
        meta = segment.metadata_json if isinstance(segment.metadata_json, dict) else {}
        segment.metadata_json = {**meta, "runtime_event_ids": runtime_ids}
        db.commit()
        return

    if preview:
        record_segment(
            db,
            snapshot=snapshot,
            category=ContextTokenCategory.RUNTIME_SKILLS,
            source_kind="runtime_skill_tool_result",
            source_ref_id=normalized_tool_use_id,
            skill_runtime_event_id=runtime_ids[0] if runtime_ids else None,
            tool_use_id=normalized_tool_use_id,
            content=preview,
            title="Runtime Skill Tool Result",
            metadata_json={"runtime_event_ids": runtime_ids},
            dedupe=False,
        )


def _provider_tokens_payload(snapshot: Optional[SddContextTokenSnapshot]) -> Dict[str, Any]:
    payload = {field: (getattr(snapshot, field) if snapshot else None) for field in PROVIDER_TOKEN_FIELDS}
    payload["available"] = any(payload[field] is not None for field in PROVIDER_TOKEN_FIELDS)
    payload["status"] = "available" if payload["available"] else "unavailable"
    return payload


def _serialize_snapshot(snapshot: Optional[SddContextTokenSnapshot]) -> Optional[Dict[str, Any]]:
    if snapshot is None:
        return None
    return {
        "id": snapshot.id,
        "workspace_id": snapshot.workspace_id,
        "task_id": snapshot.task_id,
        "ai_job_id": snapshot.ai_job_id,
        "session_id": snapshot.session_id,
        "model": snapshot.model,
        "status": snapshot.status,
        "total_cost_usd": snapshot.total_cost_usd,
        "duration_ms": snapshot.duration_ms,
        "created_at": snapshot.created_at,
        "updated_at": snapshot.updated_at,
    }


def _serialize_segment(row: SddContextTokenSegment) -> Dict[str, Any]:
    return {
        "id": row.id,
        "snapshot_id": row.snapshot_id,
        "category": _enum_value(row.category),
        "provider_tokens": row.provider_tokens,
        "attribution_units": int(row.attribution_units or 0),
        "char_count": int(row.char_count or 0),
        "byte_count": int(row.byte_count or 0),
        "source_kind": row.source_kind,
        "source_ref_id": row.source_ref_id,
        "chat_message_id": row.chat_message_id,
        "asset_id": row.asset_id,
        "asset_version_id": row.asset_version_id,
        "skill_runtime_event_id": row.skill_runtime_event_id,
        "tool_use_id": row.tool_use_id,
        "content_hash": row.content_hash,
        "locator_json": row.locator_json,
        "title": row.title,
        "preview": row.preview,
        "metadata_json": row.metadata_json,
        "created_at": row.created_at,
    }


def get_context_window(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    ai_job_id: Optional[str] = None,
    category: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    snapshot = find_snapshot(db, workspace_id=workspace_id, task_id=task_id, ai_job_id=ai_job_id)
    safe_page = max(1, int(page or 1))
    safe_page_size = max(1, min(int(page_size or 50), SEGMENT_PAGE_LIMIT))
    selected_category = _coerce_category(category) if category else None
    if snapshot is None:
        compaction = context_compaction_service.get_context_compaction(
            db,
            workspace_id=workspace_id,
            task_id=task_id,
            snapshot=None,
        )
        return {
            "task_id": task_id,
            "workspace_id": workspace_id,
            "snapshot": None,
            "provider_tokens": _provider_tokens_payload(None),
            "categories": [],
            "segments": [],
            "segments_total": 0,
            "segments_page": safe_page,
            "segments_page_size": safe_page_size,
            "selected_category": _enum_value(selected_category) if selected_category else None,
            "empty_reason": "NO_SNAPSHOT",
            "compaction": compaction,
        }

    rows = (
        db.query(
            SddContextTokenSegment.category.label("category"),
            sqlfunc.count(SddContextTokenSegment.id).label("segment_count"),
            sqlfunc.coalesce(sqlfunc.sum(SddContextTokenSegment.attribution_units), 0).label("attribution_units"),
            sqlfunc.coalesce(sqlfunc.sum(SddContextTokenSegment.char_count), 0).label("char_count"),
            sqlfunc.coalesce(sqlfunc.sum(SddContextTokenSegment.byte_count), 0).label("byte_count"),
            sqlfunc.sum(SddContextTokenSegment.provider_tokens).label("provider_tokens"),
        )
        .filter(SddContextTokenSegment.snapshot_id == snapshot.id)
        .group_by(SddContextTokenSegment.category)
        .all()
    )
    total_units = sum(int(row.attribution_units or 0) for row in rows)
    categories = []
    for row in rows:
        units = int(row.attribution_units or 0)
        categories.append(
            {
                "category": _enum_value(row.category),
                "segment_count": int(row.segment_count or 0),
                "provider_tokens": int(row.provider_tokens) if row.provider_tokens is not None else None,
                "attribution_units": units,
                "char_count": int(row.char_count or 0),
                "byte_count": int(row.byte_count or 0),
                "percentage": (units / total_units * 100.0) if total_units > 0 else 0.0,
            }
        )
    categories.sort(key=lambda item: (-int(item["attribution_units"]), str(item["category"])))

    segments: List[Dict[str, Any]] = []
    segments_total = 0
    if selected_category:
        segment_query = db.query(SddContextTokenSegment).filter(
            SddContextTokenSegment.snapshot_id == snapshot.id,
            SddContextTokenSegment.category == selected_category,
        )
        segments_total = int(segment_query.count() or 0)
        segment_rows = (
            segment_query.order_by(SddContextTokenSegment.created_at.asc(), SddContextTokenSegment.id.asc())
            .offset((safe_page - 1) * safe_page_size)
            .limit(safe_page_size)
            .all()
        )
        segments = [_serialize_segment(row) for row in segment_rows]

    compaction = context_compaction_service.get_context_compaction(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        snapshot=snapshot,
    )

    return {
        "task_id": task_id,
        "workspace_id": workspace_id,
        "snapshot": _serialize_snapshot(snapshot),
        "provider_tokens": _provider_tokens_payload(snapshot),
        "categories": categories,
        "segments": segments,
        "segments_total": segments_total,
        "segments_page": safe_page,
        "segments_page_size": safe_page_size,
        "selected_category": _enum_value(selected_category) if selected_category else None,
        "empty_reason": None,
        "compaction": compaction,
    }
