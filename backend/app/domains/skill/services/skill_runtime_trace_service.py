"""Runtime Skill evidence trace capture.

Only observable Claude CLI tool_use / tool_result payloads are considered. The
matcher attributes events to a Skill when a path explicitly enters
.claude/skills/<materialized_dir>/... for the current task.
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.database import SessionLocal
from app.domains.skill.models.skill import (
    SddSkillRuntimeEvent,
    SkillRuntimeEventStatus,
    SkillRuntimeEventType,
    SkillRuntimeEvidenceLevel,
)
from app.domains.task.models.task import SddTask
from app.domains.ai.schemas.websocket import WSMessage
from app.domains.skill.services import task_skill_runtime_service
from app.domains.task.services import context_token_service
from app.domains.skill.services.skill import storage_service
from app.domains.websocket.ws.manager import manager as ws_manager


RESULT_PREVIEW_LIMIT = 2000
TRACE_EVENT_LIMIT = 500
logger = get_logger(__name__, category="task_execution")


@dataclass(frozen=True)
class RuntimeSkillIndexItem:
    skill_id: Optional[str]
    skill_name: str
    materialized_dir: str
    runtime_root_abs: str
    runtime_root_rel: str


_writer_queue: Optional[asyncio.Queue[Dict[str, Any]]] = None
_writer_task: Optional[asyncio.Task[None]] = None


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def serialize_runtime_event(event: SddSkillRuntimeEvent) -> Dict[str, Any]:
    return {
        "id": event.id,
        "workspace_id": event.workspace_id,
        "task_id": event.task_id,
        "skill_id": event.skill_id,
        "ai_job_id": event.ai_job_id,
        "tool_use_id": event.tool_use_id,
        "event_type": _enum_value(event.event_type),
        "evidence_level": _enum_value(event.evidence_level),
        "materialized_dir": event.materialized_dir,
        "matched_path": event.matched_path,
        "relative_path": event.relative_path,
        "tool_name": event.tool_name,
        "tool_input_json": event.tool_input_json,
        "tool_result_preview": event.tool_result_preview,
        "status": _enum_value(event.status),
        "confidence": float(event.confidence or 0),
        "created_at": event.created_at,
    }


def build_runtime_skill_index(db: Session, task: SddTask) -> List[RuntimeSkillIndexItem]:
    records = task_skill_runtime_service.get_task_runtime_skill_records(db, task)
    project_path = os.path.abspath(str(task.project_path or "."))
    items: List[RuntimeSkillIndexItem] = []
    for record in records:
        folder = str(record.materialized_dir or "").strip()
        if not folder:
            continue
        items.append(
            RuntimeSkillIndexItem(
                skill_id=record.skill_id if record.skill is not None and not record.config_deleted else None,
                skill_name=record.name,
                materialized_dir=folder,
                runtime_root_abs=os.path.abspath(os.path.join(project_path, ".claude", "skills", folder)),
                runtime_root_rel=storage_service.normalize_path(os.path.join(".claude", "skills", folder)),
            )
        )
    return items


def _slash(value: Any) -> str:
    text = str(value or "").strip().strip("\"'")
    text = text.replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text


def _norm_abs(value: str) -> str:
    return _slash(os.path.normcase(os.path.abspath(str(value or ""))))


def _norm_rel(value: str) -> str:
    text = _slash(value).strip()
    while text.startswith("./"):
        text = text[2:]
    return text.strip("/")


def _is_abs_path(value: str) -> bool:
    text = str(value or "").strip()
    return bool(os.path.isabs(text) or re.match(r"^[A-Za-z]:[\\/]", text) or text.startswith("\\\\"))


def _path_under_root(candidate: str, item: RuntimeSkillIndexItem) -> Optional[Tuple[str, str]]:
    raw = _slash(candidate)
    if not raw:
        return None

    root_abs = _norm_abs(item.runtime_root_abs)
    if _is_abs_path(raw):
        candidate_abs = _norm_abs(raw)
        if candidate_abs == root_abs:
            return raw, ""
        prefix = root_abs.rstrip("/") + "/"
        if candidate_abs.startswith(prefix):
            return raw, _norm_rel(candidate_abs[len(prefix) :])

    candidate_rel = _norm_rel(raw)
    root_rel = _norm_rel(item.runtime_root_rel)
    if candidate_rel == root_rel:
        return raw, ""
    prefix = root_rel.rstrip("/") + "/"
    marker = f".claude/skills/{item.materialized_dir}".replace("\\", "/")
    marker_lc = marker.lower()
    candidate_lc = candidate_rel.lower()
    if candidate_lc.startswith(prefix.lower()):
        return raw, _norm_rel(candidate_rel[len(prefix) :])
    idx = candidate_lc.find(marker_lc + "/")
    if idx >= 0:
        rel_start = idx + len(marker_lc) + 1
        return raw, _norm_rel(candidate_rel[rel_start:])
    return None


def _command_match(command: str, item: RuntimeSkillIndexItem) -> Optional[Tuple[str, str]]:
    raw = _slash(command)
    if not raw:
        return None
    lowered = raw.lower()
    roots = [
        _slash(os.path.normcase(item.runtime_root_abs)).lower(),
        _norm_rel(item.runtime_root_rel).lower(),
        f".claude/skills/{item.materialized_dir}".lower(),
    ]
    for root in roots:
        idx = lowered.find(root)
        if idx < 0:
            continue
        end = idx + len(root)
        if end < len(lowered) and lowered[end] not in {"/", " ", "\t", "\r", "\n", "\"", "'", "`", ")", "(", ";"}:
            continue
        rel = ""
        if end < len(raw) and raw[end] == "/":
            tail = raw[end + 1 :]
            rel = re.split(r"[\s\"'`;|&<>)]", tail, maxsplit=1)[0]
        return root, _norm_rel(rel)
    return None


def _iter_tool_paths(tool_input: Any, *, include_pattern: bool = False) -> Iterable[str]:
    path_keys = {"file_path", "path", "directory", "dir", "cwd"}
    if include_pattern:
        path_keys.update({"pattern", "glob"})

    def walk(value: Any, key: str = "") -> Iterable[str]:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                yield from walk(child_value, str(child_key))
            return
        if isinstance(value, list):
            for child in value:
                yield from walk(child, key)
            return
        if key in path_keys and value is not None:
            yield str(value)

    yield from walk(tool_input)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_json_safe(item) for item in value[:200]]
    if isinstance(value, dict):
        return {str(key): _json_safe(child) for key, child in list(value.items())[:200]}
    return str(value)


def _event_type_for_tool(tool_name: str, relative_path: str) -> Optional[SkillRuntimeEventType]:
    normalized = str(tool_name or "").strip().lower()
    rel = _norm_rel(relative_path)
    if normalized == "skill":
        return SkillRuntimeEventType.USAGE_CONFIRMED
    if normalized == "read":
        return SkillRuntimeEventType.ENTRY_READ if rel.lower() == "skill.md" else SkillRuntimeEventType.FILE_READ
    if normalized == "ls":
        return SkillRuntimeEventType.DIR_LIST
    if normalized in {"grep", "glob"}:
        return SkillRuntimeEventType.FILE_SEARCH
    if normalized == "bash":
        return SkillRuntimeEventType.SCRIPT_EXEC
    if normalized in {"edit", "write", "multiedit"}:
        return SkillRuntimeEventType.FILE_WRITE
    return None


def _skill_tool_ref(tool_input: Any) -> str:
    if isinstance(tool_input, dict):
        for key in ("skill", "name", "skill_name", "materialized_dir"):
            value = str(tool_input.get(key) or "").strip()
            if value:
                return value
    return str(tool_input or "").strip()


def _matches_skill_tool_ref(skill_ref: str, item: RuntimeSkillIndexItem, *, allow_skill_name: bool) -> bool:
    normalized_ref = _norm_rel(skill_ref).lower()
    if not normalized_ref:
        return False
    if normalized_ref == _norm_rel(item.materialized_dir).lower():
        return True
    return allow_skill_name and normalized_ref == _norm_rel(item.skill_name).lower()


def detect_tool_use_events(
    *,
    workspace_id: str,
    task_id: str,
    ai_job_id: Optional[str],
    runtime_index: List[RuntimeSkillIndexItem],
    tool_name: str,
    tool_input: Any,
    tool_use_id: str,
) -> List[Dict[str, Any]]:
    event_type_probe = _event_type_for_tool(tool_name, "")
    if not event_type_probe or not runtime_index:
        return []

    normalized_tool = str(tool_name or "").strip()
    include_pattern = normalized_tool.lower() in {"grep", "glob"}
    matches: Dict[Tuple[Optional[str], str, str], Dict[str, Any]] = {}

    if normalized_tool.lower() == "skill":
        skill_ref = _skill_tool_ref(tool_input)
        normalized_ref = _norm_rel(skill_ref).lower()
        materialized_matches = [
            item for item in runtime_index
            if normalized_ref and normalized_ref == _norm_rel(item.materialized_dir).lower()
        ]
        name_matches = []
        if not materialized_matches:
            name_matches = [
                item for item in runtime_index
                if normalized_ref and normalized_ref == _norm_rel(item.skill_name).lower()
            ]
        matched_items = materialized_matches or (name_matches if len(name_matches) == 1 else [])
        for item in runtime_index:
            if item not in matched_items or not _matches_skill_tool_ref(
                skill_ref,
                item,
                allow_skill_name=not materialized_matches and len(name_matches) == 1,
            ):
                continue
            event_type = SkillRuntimeEventType.USAGE_CONFIRMED
            matched_path = _norm_rel(item.runtime_root_rel)
            key = (item.skill_id, event_type.value, matched_path)
            matches[key] = _build_event_payload(
                workspace_id=workspace_id,
                task_id=task_id,
                ai_job_id=ai_job_id,
                item=item,
                tool_use_id=tool_use_id,
                event_type=event_type,
                evidence_level=SkillRuntimeEvidenceLevel.EXACT_PATH,
                matched_path=matched_path,
                relative_path="",
                tool_name=normalized_tool,
                tool_input=tool_input,
                confidence=1.0,
            )
        return list(matches.values())

    if normalized_tool.lower() == "bash":
        command = ""
        if isinstance(tool_input, dict):
            command = str(tool_input.get("command") or "")
        elif isinstance(tool_input, str):
            command = tool_input
        for item in runtime_index:
            matched = _command_match(command, item)
            if not matched:
                continue
            matched_path, relative_path = matched
            event_type = _event_type_for_tool(normalized_tool, relative_path)
            if not event_type:
                continue
            key = (item.skill_id, event_type.value, relative_path)
            matches[key] = _build_event_payload(
                workspace_id=workspace_id,
                task_id=task_id,
                ai_job_id=ai_job_id,
                item=item,
                tool_use_id=tool_use_id,
                event_type=event_type,
                evidence_level=SkillRuntimeEvidenceLevel.COMMAND_PATH,
                matched_path=matched_path,
                relative_path=relative_path,
                tool_name=normalized_tool,
                tool_input=tool_input,
                confidence=0.9,
            )
        return list(matches.values())

    for path_value in _iter_tool_paths(tool_input, include_pattern=include_pattern):
        for item in runtime_index:
            matched = _path_under_root(path_value, item)
            if not matched:
                continue
            matched_path, relative_path = matched
            event_type = _event_type_for_tool(normalized_tool, relative_path)
            if not event_type:
                continue
            key = (item.skill_id, event_type.value, relative_path)
            if key in matches:
                continue
            matches[key] = _build_event_payload(
                workspace_id=workspace_id,
                task_id=task_id,
                ai_job_id=ai_job_id,
                item=item,
                tool_use_id=tool_use_id,
                event_type=event_type,
                evidence_level=SkillRuntimeEvidenceLevel.EXACT_PATH,
                matched_path=matched_path,
                relative_path=relative_path,
                tool_name=normalized_tool,
                tool_input=tool_input,
                confidence=1.0,
            )
    return list(matches.values())


def _build_event_payload(
    *,
    workspace_id: str,
    task_id: str,
    ai_job_id: Optional[str],
    item: RuntimeSkillIndexItem,
    tool_use_id: str,
    event_type: SkillRuntimeEventType,
    evidence_level: SkillRuntimeEvidenceLevel,
    matched_path: str,
    relative_path: str,
    tool_name: str,
    tool_input: Any,
    confidence: float,
) -> Dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "workspace_id": workspace_id,
        "task_id": task_id,
        "skill_id": item.skill_id,
        "ai_job_id": ai_job_id,
        "tool_use_id": str(tool_use_id or "").strip() or None,
        "event_type": event_type,
        "evidence_level": evidence_level,
        "materialized_dir": item.materialized_dir,
        "matched_path": matched_path,
        "relative_path": _norm_rel(relative_path) or None,
        "tool_name": tool_name,
        "tool_input_json": _json_safe(tool_input),
        "status": SkillRuntimeEventStatus.PENDING,
        "confidence": confidence,
    }


def enqueue_tool_use_trace(
    *,
    workspace_id: str,
    task_id: str,
    ai_job_id: Optional[str],
    runtime_index: List[RuntimeSkillIndexItem],
    tool_name: str,
    tool_input: Any,
    tool_use_id: str,
) -> None:
    try:
        events = detect_tool_use_events(
            workspace_id=workspace_id,
            task_id=task_id,
            ai_job_id=ai_job_id,
            runtime_index=runtime_index,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_use_id=tool_use_id,
        )
        if not events:
            return
        _enqueue_or_thread({"kind": "tool_use", "task_id": task_id, "events": events})
    except Exception as exc:
        logger.warning(f"Runtime skill trace tool_use detection failed: {exc}")
        return


def enqueue_tool_result_trace(
    *,
    workspace_id: str,
    task_id: str,
    ai_job_id: Optional[str],
    tool_use_id: str,
    output: Any,
    is_error: bool = False,
) -> None:
    try:
        normalized_tool_use_id = str(tool_use_id or "").strip()
        if not normalized_tool_use_id:
            return
        preview = str(output or "")[:RESULT_PREVIEW_LIMIT]
        _enqueue_or_thread(
            {
                "kind": "tool_result",
                "workspace_id": workspace_id,
                "task_id": task_id,
                "ai_job_id": ai_job_id,
                "tool_use_id": normalized_tool_use_id,
                "tool_result_preview": preview,
                "is_error": bool(is_error),
            }
        )
    except Exception as exc:
        logger.warning(f"Runtime skill trace tool_result enqueue failed: {exc}")
        return


def _enqueue_or_thread(payload: Dict[str, Any]) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        thread = threading.Thread(target=_write_payload_thread, args=(payload,), daemon=True)
        thread.start()
        return
    _ensure_writer(loop)
    if _writer_queue is not None:
        _writer_queue.put_nowait(payload)


def _ensure_writer(loop: asyncio.AbstractEventLoop) -> None:
    global _writer_queue, _writer_task
    if _writer_queue is None:
        _writer_queue = asyncio.Queue()
    if _writer_task is None or _writer_task.done():
        _writer_task = loop.create_task(_writer_loop())


async def _writer_loop() -> None:
    assert _writer_queue is not None
    while True:
        payload = await _writer_queue.get()
        try:
            events = await asyncio.to_thread(_write_payload_sync, payload)
            for event_payload in events:
                await ws_manager.send_message_to_room(
                    str(event_payload.get("task_id") or payload.get("task_id") or ""),
                    WSMessage(type="skill_runtime_event", payload=event_payload),
                )
        except Exception as exc:
            logger.warning(f"Runtime skill trace writer failed: {exc}")
        finally:
            _writer_queue.task_done()


def _write_payload_thread(payload: Dict[str, Any]) -> None:
    try:
        _write_payload_sync(payload)
    except Exception as exc:
        logger.warning(f"Runtime skill trace thread writer failed: {exc}")
        return


def _write_payload_sync(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    kind = str(payload.get("kind") or "")
    if kind == "tool_use":
        return _write_tool_use_events_sync(payload)
    if kind == "tool_result":
        return _write_tool_result_sync(payload)
    return []


def _write_tool_use_events_sync(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    events = [event for event in payload.get("events") or [] if isinstance(event, dict)]
    if not events:
        return []
    db = SessionLocal()
    try:
        rows: List[SddSkillRuntimeEvent] = []
        for event in events:
            row = SddSkillRuntimeEvent(
                id=event.get("id") or str(uuid.uuid4()),
                workspace_id=event.get("workspace_id"),
                task_id=event.get("task_id"),
                skill_id=event.get("skill_id"),
                ai_job_id=event.get("ai_job_id"),
                tool_use_id=event.get("tool_use_id"),
                event_type=event.get("event_type"),
                evidence_level=event.get("evidence_level"),
                materialized_dir=event.get("materialized_dir"),
                matched_path=event.get("matched_path"),
                relative_path=event.get("relative_path"),
                tool_name=event.get("tool_name"),
                tool_input_json=event.get("tool_input_json"),
                status=event.get("status") or SkillRuntimeEventStatus.PENDING,
                confidence=float(event.get("confidence") or 1.0),
            )
            db.add(row)
            rows.append(row)
        db.commit()
        for row in rows:
            db.refresh(row)
            try:
                context_token_service.record_runtime_skill_event(db, row)
            except Exception as exc:
                logger.warning(f"Persist runtime skill context segment failed: {exc}")
        return [serialize_runtime_event(row) for row in rows]
    except Exception as exc:
        logger.warning(f"Persist runtime skill trace events failed: {exc}")
        db.rollback()
        return []
    finally:
        db.close()


def _write_tool_result_sync(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    task_id = str(payload.get("task_id") or "").strip()
    tool_use_id = str(payload.get("tool_use_id") or "").strip()
    if not task_id or not tool_use_id:
        return []
    db = SessionLocal()
    try:
        existing = (
            db.query(SddSkillRuntimeEvent)
            .filter(
                SddSkillRuntimeEvent.task_id == task_id,
                SddSkillRuntimeEvent.tool_use_id == tool_use_id,
                SddSkillRuntimeEvent.event_type != SkillRuntimeEventType.TOOL_RESULT,
            )
            .order_by(SddSkillRuntimeEvent.created_at.asc(), SddSkillRuntimeEvent.id.asc())
            .all()
        )
        if not existing:
            return []

        preview = str(payload.get("tool_result_preview") or "")[:RESULT_PREVIEW_LIMIT]
        changed: List[SddSkillRuntimeEvent] = []
        for row in existing:
            row.tool_result_preview = preview
            row.status = SkillRuntimeEventStatus.FAILED if payload.get("is_error") else SkillRuntimeEventStatus.RESULT_RETURNED
            changed.append(row)

        result_rows: List[SddSkillRuntimeEvent] = []
        seen: set[Tuple[Optional[str], Optional[str]]] = set()
        for row in existing:
            key = (row.skill_id, row.materialized_dir)
            if key in seen:
                continue
            seen.add(key)
            result_row = SddSkillRuntimeEvent(
                id=str(uuid.uuid4()),
                workspace_id=row.workspace_id,
                task_id=row.task_id,
                skill_id=row.skill_id,
                ai_job_id=payload.get("ai_job_id") or row.ai_job_id,
                tool_use_id=tool_use_id,
                event_type=SkillRuntimeEventType.TOOL_RESULT,
                evidence_level=SkillRuntimeEvidenceLevel.RESULT_LINKED,
                materialized_dir=row.materialized_dir,
                matched_path=row.matched_path,
                relative_path=row.relative_path,
                tool_name=row.tool_name,
                tool_input_json=None,
                tool_result_preview=preview,
                status=SkillRuntimeEventStatus.FAILED if payload.get("is_error") else SkillRuntimeEventStatus.RESULT_RETURNED,
                confidence=0.8,
            )
            db.add(result_row)
            result_rows.append(result_row)

        db.commit()
        for row in [*changed, *result_rows]:
            db.refresh(row)
        try:
            context_token_service.promote_tool_result_to_runtime_skill(
                db,
                workspace_id=str(payload.get("workspace_id") or existing[0].workspace_id),
                task_id=task_id,
                ai_job_id=payload.get("ai_job_id") or existing[0].ai_job_id,
                tool_use_id=tool_use_id,
                runtime_event_ids=[row.id for row in result_rows] or [row.id for row in changed],
                preview=preview,
            )
        except Exception as exc:
            logger.warning(f"Promote tool result context segment failed: {exc}")
        return [serialize_runtime_event(row) for row in [*changed, *result_rows]]
    except Exception as exc:
        logger.warning(f"Persist runtime skill trace result failed: {exc}")
        db.rollback()
        return []
    finally:
        db.close()


def list_task_runtime_events(
    db: Session,
    task: SddTask,
    *,
    skill_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 100,
    group_by_skill: bool = False,
) -> Dict[str, Any]:
    query = db.query(SddSkillRuntimeEvent).filter(
        SddSkillRuntimeEvent.task_id == task.id,
        SddSkillRuntimeEvent.workspace_id == task.workspace_id,
    )
    skill_id_norm = str(skill_id or "").strip()
    if skill_id_norm:
        query = query.filter(SddSkillRuntimeEvent.skill_id == skill_id_norm)
    event_type_norm = str(event_type or "").strip().upper()
    if event_type_norm:
        query = query.filter(SddSkillRuntimeEvent.event_type == event_type_norm)

    safe_limit = max(1, min(int(limit or 100), TRACE_EVENT_LIMIT))
    rows = (
        query.order_by(SddSkillRuntimeEvent.created_at.desc(), SddSkillRuntimeEvent.id.desc())
        .limit(safe_limit)
        .all()
    )
    rows = list(reversed(rows))
    items = [serialize_runtime_event(row) for row in rows]
    grouped = None
    if group_by_skill:
        grouped = {}
        for item in items:
            key = str(item.get("skill_id") or item.get("materialized_dir") or "unattributed")
            bucket = grouped.setdefault(
                key,
                {
                    "skill_id": item.get("skill_id"),
                    "materialized_dir": item.get("materialized_dir"),
                    "events": [],
                },
            )
            bucket["events"].append(item)
    return {
        "task_id": task.id,
        "items": items,
        "grouped_by_skill": grouped,
        "total": len(items),
    }
