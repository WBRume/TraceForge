"""
Unified AI async job orchestration service.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import ExitStack
from datetime import datetime
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.core.distributed_lock import LockAcquireTimeout, lock_ai_queue
from app.core.logging import bind_ai_context, bind_task_context, get_logger
from app.database import SessionLocal
from app.engine.claude_bridge import create_cli_bridge
from app.engine.workflow_engine import WorkflowEngine, get_engine
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.asset.models.asset import (
    AssetThreadMessageRole,
    SddAssetResolutionProposal,
    SddAssetThread,
    SddAssetThreadMessage,
    SddAssetVersion,
)
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.ai.schemas.websocket import WSMessage
from app.domains.asset.services import asset_discussion_service, asset_resolution_service
from app.domains.task.services import context_token_service, task_cli_state_service
from app.domains.task.services import diagnosis_result_service
from app.domains.task.services.ai_context_service import (
    build_asset_thread_prompt,
    build_resolution_proposal_prompt,
    build_resolution_rewrite_prompt,
)
from app.domains.asset.ws.asset_discussion_manager import asset_discussion_ws_manager
from app.domains.websocket.ws.manager import manager as task_ws_manager

logger = get_logger(__name__, category="ai_session")


ACTIVE_STATUSES = {
    AiJobStatus.PENDING,
    AiJobStatus.RUNNING,
    AiJobStatus.WAITING_HITL,
    AiJobStatus.INTERRUPTED,
}
FINAL_STATUSES = {AiJobStatus.SUCCESS, AiJobStatus.FAILED, AiJobStatus.CANCELLED}
BLOCKING_STATUSES = {AiJobStatus.RUNNING, AiJobStatus.WAITING_HITL, AiJobStatus.INTERRUPTED}
TASK_QUEUE_PAUSED_STATUSES = {TaskStatus.INTERRUPTED, TaskStatus.FAILED}
JOB_KIND_THREAD_AI_REPLY = "THREAD_AI_REPLY"
JOB_KIND_RESOLUTION_PROPOSAL = "RESOLUTION_PROPOSAL"
JOB_KIND_RESOLUTION_REWRITE = "RESOLUTION_REWRITE"

_QUEUE_LOCKS: Dict[str, asyncio.Lock] = {}
_QUEUE_RUNNERS: Dict[str, asyncio.Task] = {}
_JOB_CANCEL_EVENTS: Dict[str, asyncio.Event] = {}

_RUNNING_STALE_MINUTES = 10

_TIMEOUT_TEXT_MARKERS = (
    "request timed out",
    "timed out",
    "timeout",
    "etimedout",
    "network timeout",
    "连接超时",
    "请求超时",
)


def _queue_key_for_task(task_id: str) -> str:
    return f"TASK_CHAT:{task_id}"


def _queue_key_for_thread(thread_id: str) -> str:
    return f"ASSET_THREAD:{thread_id}"


def _get_queue_lock(queue_key: str) -> asyncio.Lock:
    lock = _QUEUE_LOCKS.get(queue_key)
    if lock is None:
        lock = asyncio.Lock()
        _QUEUE_LOCKS[queue_key] = lock
    return lock


def _get_or_create_cancel_event(job_id: str) -> asyncio.Event:
    event = _JOB_CANCEL_EVENTS.get(job_id)
    if event is None:
        event = asyncio.Event()
        _JOB_CANCEL_EVENTS[job_id] = event
    return event


def _request_job_cancel(job_id: str) -> None:
    _get_or_create_cancel_event(job_id).set()


def _is_cancel_requested(job_id: str) -> bool:
    event = _JOB_CANCEL_EVENTS.get(job_id)
    return bool(event and event.is_set())


def _clear_cancel_event(job_id: str) -> None:
    _JOB_CANCEL_EVENTS.pop(job_id, None)


def _as_status(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _looks_like_timeout_text(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    return any(marker in normalized for marker in _TIMEOUT_TEXT_MARKERS)


def _normalize_job_kind(value: Optional[str]) -> str:
    normalized = str(value or "").strip().upper()
    if normalized == JOB_KIND_RESOLUTION_PROPOSAL:
        return JOB_KIND_RESOLUTION_PROPOSAL
    if normalized == JOB_KIND_RESOLUTION_REWRITE:
        return JOB_KIND_RESOLUTION_REWRITE
    return JOB_KIND_THREAD_AI_REPLY


def _job_kind_from_job(job: SddAiJob) -> str:
    context = job.context_json if isinstance(job.context_json, dict) else {}
    return _normalize_job_kind(str(context.get("job_kind") or ""))


def serialize_job(job: SddAiJob) -> Dict[str, Any]:
    return {
        "id": job.id,
        "workspace_id": job.workspace_id,
        "task_id": job.task_id,
        "asset_id": job.asset_id,
        "thread_id": job.thread_id,
        "channel": _as_status(job.channel),
        "queue_key": job.queue_key,
        "status": _as_status(job.status),
        "progress": int(job.progress or 0),
        "message": job.message,
        "prompt_text": job.prompt_text,
        "context_json": job.context_json if isinstance(job.context_json, dict) else {},
        "result_json": job.result_json if isinstance(job.result_json, dict) else {},
        "error_message": job.error_message,
        "session_id": job.session_id,
        "interrupt_reason": job.interrupt_reason,
        "interrupted_by_id": job.interrupted_by_id,
        "interrupted_at": job.interrupted_at.isoformat() if job.interrupted_at else None,
        "creator_id": job.creator_id,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def _merge_json(original: Any, patch: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(original) if isinstance(original, dict) else {}
    if patch:
        merged.update(patch)
    return merged


async def _broadcast_job_payload(payload: Dict[str, Any], *, final: bool = False) -> None:
    channel = str(payload.get("channel") or "")
    if channel == AiJobChannel.ASSET_THREAD.value:
        asset_id = str(payload.get("asset_id") or "")
        if not asset_id:
            return
        await asset_discussion_ws_manager.broadcast(
            asset_id,
            {
                "type": "ai_job_update",
                "asset_id": asset_id,
                "thread_id": payload.get("thread_id"),
                "job": payload,
            },
        )
        if final:
            status = str(payload.get("status") or "")
            done_type = "ai_job_done" if status == AiJobStatus.SUCCESS.value else "ai_job_failed"
            await asset_discussion_ws_manager.broadcast(
                asset_id,
                {
                    "type": done_type,
                    "asset_id": asset_id,
                    "thread_id": payload.get("thread_id"),
                    "job": payload,
                    "error": payload.get("error_message"),
                },
            )
        return

    if channel == AiJobChannel.TASK_CHAT.value:
        task_id = str(payload.get("task_id") or "")
        if not task_id:
            return
        await task_ws_manager.send_message_to_room(
            task_id,
            WSMessage(
                type="chat_job_update",
                payload={"task_id": task_id, "job": payload},
            ),
        )
        if final:
            status = str(payload.get("status") or "")
            done_type = "chat_job_done" if status == AiJobStatus.SUCCESS.value else "chat_job_failed"
            await task_ws_manager.send_message_to_room(
                task_id,
                WSMessage(
                    type=done_type,
                    payload={
                        "task_id": task_id,
                        "job": payload,
                        "error": payload.get("error_message"),
                    },
                ),
            )


async def _load_job_payload(job_id: str) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job:
            return None
        return serialize_job(job)
    finally:
        db.close()


async def _publish_job_state(job_id: str, *, final: bool = False) -> None:
    payload = await _load_job_payload(job_id)
    if not payload:
        return
    await _broadcast_job_payload(payload, final=final)


async def _update_job_state(
    job_id: str,
    *,
    status: Optional[AiJobStatus] = None,
    progress: Optional[int] = None,
    message: Optional[str] = None,
    context_patch: Optional[Dict[str, Any]] = None,
    result_patch: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
    session_id: Optional[str] = None,
    finalize: bool = False,
) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job:
            return None
        current_status = job.status
        requested_status = status
        if current_status in FINAL_STATUSES:
            if requested_status is None or requested_status != current_status:
                payload = serialize_job(job)
                return payload
        if status is not None:
            job.status = status
        if progress is not None:
            job.progress = max(0, min(100, int(progress)))
        if message is not None:
            job.message = message
        if context_patch:
            job.context_json = _merge_json(job.context_json, context_patch)
        if result_patch:
            job.result_json = _merge_json(job.result_json, result_patch)
        if error_message is not None:
            job.error_message = error_message
        if session_id is not None:
            job.session_id = session_id
        if status == AiJobStatus.RUNNING and job.started_at is None:
            job.started_at = datetime.utcnow()
        if finalize or (status in FINAL_STATUSES):
            job.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(job)
        payload = serialize_job(job)
    finally:
        db.close()
    is_final = finalize or (status in FINAL_STATUSES)
    await _broadcast_job_payload(payload, final=is_final)
    if is_final:
        _clear_cancel_event(job_id)
        queue_key = str(payload.get("queue_key") or "")
        if queue_key:
            schedule_queue(queue_key)
    return payload


def list_thread_jobs(
    db: Session,
    *,
    thread_id: str,
    active_only: bool = True,
) -> List[SddAiJob]:
    _cleanup_stale_running_jobs(db, thread_id=thread_id)
    query = db.query(SddAiJob).filter(
        SddAiJob.thread_id == thread_id,
        SddAiJob.channel == AiJobChannel.ASSET_THREAD,
    )
    if active_only:
        query = query.filter(SddAiJob.status.in_(list(ACTIVE_STATUSES)))
    return query.order_by(SddAiJob.created_at.desc()).all()


def list_task_jobs(
    db: Session,
    *,
    task_id: str,
    active_only: bool = True,
) -> List[SddAiJob]:
    _cleanup_stale_running_jobs(db, task_id=task_id)
    query = db.query(SddAiJob).filter(
        SddAiJob.task_id == task_id,
        SddAiJob.channel == AiJobChannel.TASK_CHAT,
    )
    if active_only:
        query = query.filter(SddAiJob.status.in_(list(ACTIVE_STATUSES)))
    return query.order_by(SddAiJob.created_at.desc()).all()


def get_job(db: Session, *, job_id: str) -> Optional[SddAiJob]:
    return db.query(SddAiJob).filter(SddAiJob.id == job_id).first()


def _cleanup_stale_running_jobs(
    db: Session,
    *,
    thread_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> None:
    cutoff = datetime.utcnow() - timedelta(minutes=_RUNNING_STALE_MINUTES)
    query = db.query(SddAiJob).filter(
        SddAiJob.status == AiJobStatus.RUNNING,
    )
    if thread_id:
        query = query.filter(
            SddAiJob.thread_id == thread_id,
            SddAiJob.channel == AiJobChannel.ASSET_THREAD,
        )
    if task_id:
        query = query.filter(
            SddAiJob.task_id == task_id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
        )
    jobs = query.all()
    dirty = False
    for job in jobs:
        heartbeat = job.updated_at or job.started_at or job.created_at
        if heartbeat and heartbeat >= cutoff:
            continue
        job.status = AiJobStatus.FAILED
        job.progress = 100
        job.message = "Job interrupted unexpectedly"
        job.error_message = "AI job was interrupted unexpectedly (restart/crash). Please retry."
        job.finished_at = datetime.utcnow()
        _clear_cancel_event(job.id)
        dirty = True
    if dirty:
        db.commit()


def create_asset_thread_job(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    asset_id: str,
    thread_id: str,
    creator_id: str,
    prompt_text: Optional[str],
    job_kind: str = JOB_KIND_THREAD_AI_REPLY,
    context_json: Optional[Dict[str, Any]] = None,
) -> SddAiJob:
    normalized_kind = _normalize_job_kind(job_kind)
    payload_context = {
        "job_kind": normalized_kind,
    }
    if isinstance(context_json, dict):
        payload_context.update(context_json)
    job = SddAiJob(
        workspace_id=workspace_id,
        task_id=task_id,
        asset_id=asset_id,
        thread_id=thread_id,
        channel=AiJobChannel.ASSET_THREAD,
        queue_key=_queue_key_for_thread(thread_id),
        status=AiJobStatus.PENDING,
        progress=0,
        message="Job queued",
        prompt_text=(prompt_text or "").strip() or None,
        context_json=payload_context,
        creator_id=creator_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def create_task_chat_job(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    creator_id: str,
    prompt_text: str,
    context_json: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
    chat_message_id: Optional[str] = None,
) -> SddAiJob:
    payload_context = {"source": "task_chat"}
    if isinstance(context_json, dict):
        payload_context.update(context_json)
    job = SddAiJob(
        workspace_id=workspace_id,
        task_id=task_id,
        asset_id=None,
        thread_id=None,
        channel=AiJobChannel.TASK_CHAT,
        queue_key=_queue_key_for_task(task_id),
        status=AiJobStatus.PENDING,
        progress=0,
        message="Job queued",
        prompt_text=(prompt_text or "").strip(),
        session_id=(str(session_id or "").strip() or None),
        creator_id=creator_id,
        context_json=payload_context,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        context_token_service.seed_snapshot_for_job(
            db,
            job=job,
            prompt_text=prompt_text,
            chat_message_id=chat_message_id,
        )
    except Exception as exc:
        logger.warning(f"Failed to seed context token snapshot for job {job.id}: {exc}")
    return job


def schedule_queue(queue_key: str) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    running = _QUEUE_RUNNERS.get(queue_key)
    if running and not running.done():
        return
    _QUEUE_RUNNERS[queue_key] = loop.create_task(_run_queue(queue_key))


def _task_id_from_queue_key(queue_key: str) -> Optional[str]:
    prefix = f"{AiJobChannel.TASK_CHAT.value}:"
    if not str(queue_key or "").startswith(prefix):
        return None
    task_id = str(queue_key or "")[len(prefix):].strip()
    return task_id or None


def _is_task_queue_paused(db: Session, queue_key: str) -> bool:
    task_id = _task_id_from_queue_key(queue_key)
    if not task_id:
        return False
    row = db.query(SddTask.status).filter(SddTask.id == task_id).first()
    if not row:
        return False
    return row[0] in TASK_QUEUE_PAUSED_STATUSES


def _take_next_pending_job_id_sync(queue_key: str) -> Optional[str]:
    db = SessionLocal()
    try:
        if _is_task_queue_paused(db, queue_key):
            return None
        active = (
            db.query(SddAiJob)
            .filter(
                SddAiJob.queue_key == queue_key,
                SddAiJob.status.in_(list(BLOCKING_STATUSES)),
            )
            .order_by(SddAiJob.created_at.asc())
            .first()
        )
        if active:
            return None
        candidate = (
            db.query(SddAiJob.id)
            .filter(
                SddAiJob.queue_key == queue_key,
                SddAiJob.status == AiJobStatus.PENDING,
            )
            .order_by(SddAiJob.created_at.asc())
            .first()
        )
        if not candidate:
            return None
        job_id = str(candidate[0] or "").strip()
        if not job_id:
            return None

        now = datetime.utcnow()
        affected_rows = (
            db.query(SddAiJob)
            .filter(
                SddAiJob.id == job_id,
                SddAiJob.status == AiJobStatus.PENDING,
            )
            .update(
                {
                    SddAiJob.status: AiJobStatus.RUNNING,
                    SddAiJob.started_at: now,
                    SddAiJob.progress: 5,
                    SddAiJob.message: "Job running",
                },
                synchronize_session=False,
            )
        )
        if int(affected_rows or 0) != 1:
            db.rollback()
            return None
        db.commit()
        return job_id
    finally:
        db.close()


async def _take_next_pending_job_id(queue_key: str) -> Optional[str]:
    try:
        async with lock_ai_queue(queue_key):
            return _take_next_pending_job_id_sync(queue_key)
    except LockAcquireTimeout as exc:
        logger.warning(
            "AI queue lock timeout: queue_key={}, resource_type={}, resource_id={}, lock_key={}, backend={}",
            queue_key,
            exc.resource_type,
            exc.resource_id,
            exc.lock_key,
            exc.backend,
        )
        return None


def _get_job_status(job_id: str) -> Optional[AiJobStatus]:
    db = SessionLocal()
    try:
        job = db.query(SddAiJob.status).filter(SddAiJob.id == job_id).first()
        if not job:
            return None
        return job[0]
    finally:
        db.close()


async def _run_queue(queue_key: str) -> None:
    lock = _get_queue_lock(queue_key)
    async with lock:
        while True:
            job_id = await _take_next_pending_job_id(queue_key)
            if not job_id:
                return
            await _publish_job_state(job_id)
            await _execute_job(job_id)
            status = _get_job_status(job_id)
            if status in {AiJobStatus.WAITING_HITL, AiJobStatus.INTERRUPTED}:
                return


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


def _resolve_thread_anchor_text(
    thread: SddAssetThread,
    block: Any,
    *,
    selected_text: Optional[str] = None,
    char_start: Optional[int] = None,
    char_end: Optional[int] = None,
) -> Dict[str, str]:
    block_text = _extract_block_text(block).strip()
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


def _thread_history_lines(thread: SddAssetThread, limit: int = 18) -> List[str]:
    messages = sorted(list(thread.messages or []), key=lambda item: item.created_at)
    lines: List[str] = []
    for message in messages[-limit:]:
        role = _as_status(message.role)
        if role == AssetThreadMessageRole.AI.value:
            continue
        content = str(message.content or "").strip()
        if content:
            lines.append(f"[{role}] {content}")
    return lines


def _proposal_discussion_lines(thread: SddAssetThread, limit: int = 28) -> List[str]:
    messages = sorted(list(thread.messages or []), key=lambda item: item.created_at)
    lines: List[str] = []
    for message in messages:
        role = _as_status(message.role)
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


def _proposal_source_message_ids(thread: SddAssetThread) -> List[str]:
    messages = sorted(list(thread.messages or []), key=lambda item: item.created_at)
    return [
        item.id
        for item in messages
        if _as_status(item.role) in {AssetThreadMessageRole.USER.value, AssetThreadMessageRole.AI.value}
        and str(item.content or "").strip()
    ]


def _resolve_context_version(
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


def _normalize_relocated_anchor(raw: Any) -> Optional[Dict[str, Any]]:
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


def _serialize_proposal_for_ws(proposal: Any) -> Dict[str, Any]:
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


def _clean_rewrite_text(raw: str) -> str:
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


def _parse_rewrite_payload(raw: str) -> Dict[str, str]:
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
        return {"scope": "anchor", "anchor_text": _clean_rewrite_text(text)}

    if not isinstance(parsed, dict):
        return {"scope": "anchor", "anchor_text": _clean_rewrite_text(text)}

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
    return {"scope": "anchor", "anchor_text": _clean_rewrite_text(anchor_text or text)}


async def run_cli_single_turn(
    prompt: str,
    project_path: str,
    *,
    session_id: Optional[str] = None,
    max_attempts: int = 2,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Dict[str, Optional[str]]:
    attempts = max(1, int(max_attempts or 1))
    next_session_id = session_id
    last_error: Optional[Exception] = None

    for attempt in range(1, attempts + 1):
        bridge = create_cli_bridge()
        text_parts: List[str] = []
        result_text = ""
        result_is_error = False
        cancelled = False

        async def on_event(event: dict):
            nonlocal result_text, result_is_error
            event_type = str(event.get("type") or "")
            if event_type == "assistant":
                message = event.get("message") or {}
                blocks = message.get("content") if isinstance(message, dict) else []
                if not isinstance(blocks, list):
                    return
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    if str(block.get("type") or "") == "text":
                        text = str(block.get("text") or "").strip()
                        if text:
                            text_parts.append(text)
            elif event_type == "result":
                subtype = str(event.get("subtype") or "").lower()
                result_is_error = bool(event.get("is_error")) or subtype == "error"
                text = str(event.get("result") or "").strip()
                if text:
                    result_text = text

        resumed_session_id = await bridge.start_session(
            prompt=prompt,
            project_path=project_path,
            event_callback=on_event,
            session_id=next_session_id,
        )
        monitor_task: Optional[asyncio.Task] = None
        if should_cancel:
            async def _cancel_monitor() -> None:
                nonlocal cancelled
                while True:
                    if should_cancel():
                        cancelled = True
                        await bridge.cancel()
                        return
                    await asyncio.sleep(0.2)

            monitor_task = asyncio.create_task(_cancel_monitor())

        # 文档讨论是异步作业，允许更长执行时长，避免误超时。
        wait_seconds = max(600, int(settings.CLAUDE_CLI_TIMEOUT or 300))
        try:
            if hasattr(bridge, "wait"):
                await asyncio.wait_for(bridge.wait(), timeout=wait_seconds)
        except asyncio.TimeoutError as exc:
            await bridge.cancel()
            last_error = TimeoutError("AI reply timed out")
            logger.warning(
                "Asset AI single-turn wait timeout (attempt {}/{})",
                attempt,
                attempts,
            )
            if attempt < attempts:
                next_session_id = None
                continue
            raise last_error from exc
        finally:
            if monitor_task:
                monitor_task.cancel()

        if cancelled:
            raise RuntimeError("AI job cancelled by user")

        merged = "\n\n".join(part for part in text_parts if part.strip()).strip()
        final_text = merged or result_text or "AI 暂时没有返回有效内容，请稍后重试。"
        final_session_id = getattr(bridge, "session_id", None) or resumed_session_id

        if result_is_error or _looks_like_timeout_text(final_text):
            last_error = RuntimeError(final_text or "AI provider returned timeout/error")
            logger.warning(
                "Asset AI single-turn got timeout/error text (attempt {}/{}): {}",
                attempt,
                attempts,
                final_text[:160],
            )
            if attempt < attempts:
                next_session_id = None
                continue
            raise last_error

        return {"text": final_text, "session_id": final_session_id}

    if last_error:
        raise last_error
    raise RuntimeError("AI reply failed with unknown reason")


async def _execute_asset_thread_job(job_id: str) -> None:
    db = SessionLocal()
    context_stack = ExitStack()
    job_kind = JOB_KIND_THREAD_AI_REPLY
    try:
        job = (
            db.query(SddAiJob)
            .options(
                joinedload(SddAiJob.thread)
                .joinedload(SddAssetThread.messages)
                .joinedload(SddAssetThreadMessage.creator),
                joinedload(SddAiJob.thread).joinedload(SddAssetThread.version),
                joinedload(SddAiJob.thread).joinedload(SddAssetThread.task),
                joinedload(SddAiJob.thread).joinedload(SddAssetThread.asset),
            )
            .filter(SddAiJob.id == job_id)
            .first()
        )
        if not job or job.channel != AiJobChannel.ASSET_THREAD:
            return
        thread = job.thread
        if not thread:
            raise ValueError("Thread not found for AI job")
        job_kind = _job_kind_from_job(job)
        context_stack.enter_context(
            bind_task_context(
                task_id=thread.task_id,
                workspace_id=thread.workspace_id,
                user_id=job.creator_id,
            )
        )
        context_stack.enter_context(
            bind_ai_context(
                job_id=job_id,
                task_id=thread.task_id,
                session_id=job.session_id,
                event_type=job_kind,
            )
        )

        await _update_job_state(job_id, progress=12, message="Building discussion context")

        version = thread.version
        task = thread.task
        if not thread.task_id or not task:
            raise ValueError("Thread task is required for AI job")

        bootstrap = task_cli_state_service.ensure_bootstrap_ready(
            db,
            workspace_id=thread.workspace_id,
            task_id=thread.task_id,
        )

        await _update_job_state(
            job_id,
            progress=18,
            message="Preparing isolated thread workspace",
            context_patch={
                "bootstrap_status": _as_status(bootstrap.status),
                "bootstrap_version_id": bootstrap.spec_version_id,
                "job_kind": job_kind,
            },
        )
        thread_workspace_path = await task_cli_state_service.ensure_thread_workspace(
            thread.id,
            require_ready=True,
        )
        resume_session_id = task_cli_state_service.get_latest_thread_session_id(db, thread.id)
        if not resume_session_id:
            resume_session_id = task_cli_state_service.get_bootstrap_session_id(db, thread.task_id)

        if job_kind == JOB_KIND_RESOLUTION_PROPOSAL:
            context_json = job.context_json if isinstance(job.context_json, dict) else {}
            overwrite_existing_draft = bool(context_json.get("overwrite_existing_draft"))
            context_version = _resolve_context_version(
                db,
                thread=thread,
                requested_version_id=str(context_json.get("context_version_id") or "").strip() or None,
            )
            anchor_eval = asset_discussion_service.resolve_thread_anchor_for_version(
                db,
                thread=thread,
                context_version=context_version,
            )
            effective_anchor = anchor_eval.get("effective_anchor") if isinstance(anchor_eval, dict) else {}
            effective_block_id = str(
                (effective_anchor or {}).get("block_id")
                or thread.block_id
                or ""
            ).strip() or thread.block_id
            selected_block = (
                asset_discussion_service.get_block_by_id(context_version, effective_block_id)
                if context_version
                else None
            )
            if not selected_block and version:
                selected_block = asset_discussion_service.get_block_by_id(version, thread.block_id)
                effective_block_id = thread.block_id
                effective_anchor = {
                    "block_id": thread.block_id,
                    "selected_text": thread.selected_text,
                    "char_start": thread.char_start,
                    "char_end": thread.char_end,
                }
            anchor_meta = _resolve_thread_anchor_text(
                thread,
                selected_block,
                selected_text=(effective_anchor or {}).get("selected_text"),
                char_start=(effective_anchor or {}).get("char_start"),
                char_end=(effective_anchor or {}).get("char_end"),
            )
            discussion_lines = _proposal_discussion_lines(thread)
            source_message_ids = _proposal_source_message_ids(thread)
            prompt = build_resolution_proposal_prompt(
                task_name=task.name if task else "",
                document_name=thread.asset.name if thread.asset else "",
                document_version_label=(f"v{context_version.version_no}" if context_version else "unknown"),
                block_id=effective_block_id or "",
                thread_id=thread.id or "",
                anchor_text=anchor_meta["anchor_text"],
                block_context_text=anchor_meta["block_text"],
                discussion_lines=discussion_lines,
            )
            await _update_job_state(
                job_id,
                progress=46,
                message="Generating resolution proposal",
                context_patch={
                    "thread_workspace": thread_workspace_path,
                    "discussion_lines": discussion_lines[-12:],
                    "anchor_text": anchor_meta["anchor_text"],
                    "block_text": anchor_meta["block_text"],
                    "context_version_id": context_version.id if context_version else None,
                    "effective_anchor": effective_anchor,
                },
            )
            result = await run_cli_single_turn(
                prompt,
                thread_workspace_path,
                session_id=resume_session_id,
                should_cancel=lambda: _is_cancel_requested(job_id),
            )
            proposal_text = str(result.get("text") or "").strip()
            final_session_id = str(result.get("session_id") or "").strip()
            if not proposal_text:
                raise ValueError("Resolution proposal text is empty")

            thread = asset_discussion_service.get_thread(db, asset_id=thread.asset_id, thread_id=thread.id)
            if not thread:
                raise ValueError("Thread disappeared during proposal generation")

            proposal = asset_resolution_service.create_resolution_proposal(
                db,
                thread=thread,
                creator_id=job.creator_id,
                proposed_text=proposal_text,
                overwrite_existing_draft=overwrite_existing_draft,
                source_message_ids=source_message_ids,
                version=context_version,
                effective_anchor=effective_anchor if isinstance(effective_anchor, dict) else None,
            )
            db.commit()
            db.refresh(proposal)

            await asset_discussion_ws_manager.broadcast(
                thread.asset_id,
                {
                    "type": "proposal_created",
                    "asset_id": thread.asset_id,
                    "thread_id": thread.id,
                    "proposal": _serialize_proposal_for_ws(proposal),
                },
            )
            await _update_job_state(
                job_id,
                status=AiJobStatus.SUCCESS,
                progress=100,
                message="Resolution proposal generated",
                result_patch={
                    "proposal_id": proposal.id,
                    "proposal_excerpt": proposal_text[:1200],
                },
                session_id=final_session_id or None,
                finalize=True,
            )
            return

        if job_kind == JOB_KIND_RESOLUTION_REWRITE:
            context_json = job.context_json if isinstance(job.context_json, dict) else {}
            proposal_id = str(context_json.get("proposal_id") or "").strip()
            if not proposal_id:
                raise ValueError("proposal_id is required for rewrite job")

            proposal = (
                db.query(SddAssetResolutionProposal)
                .filter(
                    SddAssetResolutionProposal.id == proposal_id,
                    SddAssetResolutionProposal.thread_id == thread.id,
                )
                .first()
            )
            if not proposal:
                raise ValueError("Resolution proposal not found for rewrite")

            proposal_text = str(context_json.get("proposal_text") or "").strip()
            if not proposal_text:
                patch = proposal.proposed_patch_json if isinstance(proposal.proposed_patch_json, dict) else {}
                proposal_text = str(patch.get("proposal_text") or "").strip()
            if not proposal_text:
                raise ValueError("proposal_text is required for rewrite")
            requested_scope = str(context_json.get("rewrite_scope") or "").strip().lower()
            if requested_scope not in {"anchor", "document"}:
                requested_scope = "anchor"
            context_version = _resolve_context_version(
                db,
                thread=thread,
                requested_version_id=str(context_json.get("context_version_id") or "").strip() or proposal.base_version_id,
            )
            anchor_eval = asset_discussion_service.resolve_thread_anchor_for_version(
                db,
                thread=thread,
                context_version=context_version,
            )
            effective_anchor = anchor_eval.get("effective_anchor") if isinstance(anchor_eval, dict) else {}
            relocated_anchor = _normalize_relocated_anchor(context_json.get("relocated_anchor"))
            if relocated_anchor:
                effective_anchor = relocated_anchor
            effective_block_id = str(
                (effective_anchor or {}).get("block_id")
                or thread.block_id
                or ""
            ).strip() or thread.block_id
            selected_block = (
                asset_discussion_service.get_block_by_id(context_version, effective_block_id)
                if context_version
                else None
            )
            if not selected_block:
                raise ValueError("Anchor block not found for rewrite context")
            anchor_meta = _resolve_thread_anchor_text(
                thread,
                selected_block,
                selected_text=(effective_anchor or {}).get("selected_text"),
                char_start=(effective_anchor or {}).get("char_start"),
                char_end=(effective_anchor or {}).get("char_end"),
            )
            selection_mode = bool(anchor_meta["selected_text"])
            prompt = build_resolution_rewrite_prompt(
                task_name=task.name if task else "",
                document_name=thread.asset.name if thread.asset else "",
                document_version_label=(f"v{context_version.version_no}" if context_version else "unknown"),
                block_id=effective_block_id or "",
                thread_id=thread.id or "",
                anchor_text=anchor_meta["anchor_text"],
                block_context_text=anchor_meta["block_text"],
                proposal_text=proposal_text,
                rewrite_scope=requested_scope,
                selection_mode=selection_mode,
            )
            await _update_job_state(
                job_id,
                progress=48,
                message="Rewriting document from proposal",
                context_patch={
                    "proposal_id": proposal.id,
                    "thread_workspace": thread_workspace_path,
                    "rewrite_scope": requested_scope,
                    "selection_mode": selection_mode,
                    "anchor_text": anchor_meta["anchor_text"],
                    "block_text": anchor_meta["block_text"],
                    "context_version_id": context_version.id if context_version else None,
                    "effective_anchor": effective_anchor,
                },
            )
            result = await run_cli_single_turn(
                prompt,
                thread_workspace_path,
                session_id=resume_session_id,
                should_cancel=lambda: _is_cancel_requested(job_id),
            )
            rewrite_payload = _parse_rewrite_payload(str(result.get("text") or ""))
            rewrite_scope = requested_scope or str(rewrite_payload.get("scope") or "anchor").strip().lower()
            rewritten_text = str(rewrite_payload.get("anchor_text") or "").strip()
            rewritten_markdown = str(rewrite_payload.get("document_markdown") or "").strip()
            final_session_id = str(result.get("session_id") or "").strip()
            if rewrite_scope == "document" and not rewritten_markdown:
                raise ValueError("Rewritten document markdown is empty")
            if rewrite_scope != "document" and not rewritten_text:
                raise ValueError("Rewritten block text is empty")

            thread = asset_discussion_service.get_thread(db, asset_id=thread.asset_id, thread_id=thread.id)
            if not thread:
                raise ValueError("Thread disappeared during proposal rewrite")
            proposal = (
                db.query(SddAssetResolutionProposal)
                .filter(
                    SddAssetResolutionProposal.id == proposal_id,
                    SddAssetResolutionProposal.thread_id == thread.id,
                )
                .first()
            )
            if not proposal:
                raise ValueError("Resolution proposal not found after rewrite")

            proposal = asset_resolution_service.update_resolution_proposal_rewrite(
                db,
                thread=thread,
                proposal=proposal,
                proposal_text=proposal_text,
                rewritten_text=rewritten_text,
                rewrite_scope=rewrite_scope,
                rewritten_markdown=rewritten_markdown or None,
                selection_mode=selection_mode,
                context_version_id=context_version.id if context_version else None,
                relocated_anchor=effective_anchor if isinstance(effective_anchor, dict) else None,
            )
            db.commit()
            db.refresh(proposal)
            proposal_patch = proposal.proposed_patch_json if isinstance(proposal.proposed_patch_json, dict) else {}
            rewrite_ready = str(proposal_patch.get("rewrite_status") or "").strip().lower() == "ready"
            has_merged = bool(
                (isinstance(proposal_patch.get("merged_block_ast"), dict) and proposal_patch.get("merged_block_ast"))
                or (
                    isinstance(proposal_patch.get("merged_blocks_ast"), list)
                    and len(proposal_patch.get("merged_blocks_ast") or []) > 0
                )
            )
            if not rewrite_ready or not has_merged:
                raise ValueError(
                    "Resolution rewrite persisted without merged AST payload"
                )

            await asset_discussion_ws_manager.broadcast(
                thread.asset_id,
                {
                    "type": "proposal_created",
                    "asset_id": thread.asset_id,
                    "thread_id": thread.id,
                    "proposal": _serialize_proposal_for_ws(proposal),
                },
            )
            await _update_job_state(
                job_id,
                status=AiJobStatus.SUCCESS,
                progress=100,
                message="Resolution proposal rewrite completed",
                result_patch={
                    "proposal_id": proposal.id,
                    "rewrite_excerpt": (rewritten_text or rewritten_markdown)[:1200],
                },
                session_id=final_session_id or None,
                finalize=True,
            )
            return

        context = (
            asset_discussion_service.get_block_context(version, thread.block_id)
            if version else {"selected": None, "neighbors": []}
        )
        selected_block = context.get("selected") if isinstance(context, dict) else None
        neighbor_blocks = context.get("neighbors") if isinstance(context, dict) else []
        anchor_meta = _resolve_thread_anchor_text(thread, selected_block)
        selected_text = anchor_meta["anchor_text"]
        anchor_block_text = anchor_meta["block_text"]
        neighbor_text = "\n".join(
            f"- {_extract_block_text(item)}"
            for item in (neighbor_blocks or [])
            if _extract_block_text(item)
        ).strip()
        history_lines = _thread_history_lines(thread)
        from app.domains.task.services import task_service as task_service_module

        project_path = (
            task_service_module.resolve_task_cli_dir(db, task)
            if task
            else "."
        )
        if not os.path.isdir(project_path):
            project_path = (task.project_path if task and task.project_path else ".").strip() or "."
        if not os.path.isdir(project_path):
            project_path = "."
        await _update_job_state(job_id, progress=24, message="Preparing AI prompt")

        prompt = build_asset_thread_prompt(
            task_name=task.name if task else "",
            document_name=thread.asset.name if thread.asset else "",
            document_version_label=(f"v{version.version_no}" if version else "unknown"),
            block_id=thread.block_id or "",
            thread_id=thread.id or "",
            project_path=project_path,
            selected_text=selected_text or (thread.selected_text or ""),
            anchor_block_text=anchor_block_text,
            neighbor_text=neighbor_text,
            history_lines=history_lines,
            manual_prompt=job.prompt_text,
        )

        await _update_job_state(
            job_id,
            progress=46,
            message="Calling AI engine",
            context_patch={
                "selected_text": selected_text or (thread.selected_text or ""),
                "anchor_block_text": anchor_block_text,
                "neighbor_text": neighbor_text,
                "history_lines": history_lines[-10:],
                "project_path": project_path,
                "thread_workspace": thread_workspace_path,
            },
        )

        result = await run_cli_single_turn(
            prompt,
            thread_workspace_path,
            session_id=resume_session_id,
            should_cancel=lambda: _is_cancel_requested(job_id),
        )
        reply = str(result.get("text") or "").strip()
        final_session_id = str(result.get("session_id") or "").strip()

        thread = asset_discussion_service.get_thread(db, asset_id=thread.asset_id, thread_id=thread.id)
        if not thread:
            raise ValueError("Thread disappeared during AI execution")

        ai_message = asset_discussion_service.add_thread_message(
            db,
            thread=thread,
            role=AssetThreadMessageRole.AI,
            content=reply,
            creator_id=None,
            metadata_json={"provider": "claude-cli", "job_id": job_id},
        )
        db.commit()
        db.refresh(ai_message)

        await asset_discussion_ws_manager.broadcast(
            thread.asset_id,
            {
                "type": "message_created",
                "asset_id": thread.asset_id,
                "thread_id": thread.id,
                "message": {
                    "id": ai_message.id,
                    "thread_id": ai_message.thread_id,
                    "role": _as_status(ai_message.role),
                    "content": ai_message.content,
                    "creator_id": ai_message.creator_id,
                    "creator_display_name": None,
                    "creator_avatar_svg": None,
                    "metadata_json": ai_message.metadata_json,
                    "created_at": ai_message.created_at.isoformat() if ai_message.created_at else None,
                },
            },
        )
        await _update_job_state(
            job_id,
            status=AiJobStatus.SUCCESS,
            progress=100,
            message="AI reply completed",
            result_patch={"message_id": ai_message.id},
            session_id=final_session_id or None,
            finalize=True,
        )
    except Exception as exc:
        db.rollback()
        status_after_error = _get_job_status(job_id)
        if _is_cancel_requested(job_id) or status_after_error == AiJobStatus.CANCELLED:
            _clear_cancel_event(job_id)
            return
        logger.exception(f"Asset AI job failed: {exc}")
        failed_message = "Resolution proposal failed" if job_kind == JOB_KIND_RESOLUTION_PROPOSAL else "AI reply failed"
        await _update_job_state(
            job_id,
            status=AiJobStatus.FAILED,
            progress=100,
            message=failed_message,
            error_message=str(exc),
            finalize=True,
        )
        if job_kind in {JOB_KIND_RESOLUTION_PROPOSAL, JOB_KIND_RESOLUTION_REWRITE}:
            return
        try:
            failed_job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
            if failed_job and failed_job.thread_id:
                thread = asset_discussion_service.get_thread(db, asset_id=failed_job.asset_id, thread_id=failed_job.thread_id)
                if thread:
                    failure_message = asset_discussion_service.add_thread_message(
                        db,
                        thread=thread,
                        role=AssetThreadMessageRole.SYSTEM,
                        content=f"AI 回复失败: {exc}\n\n可重试：已自动采用超时重试策略，如仍失败请稍后再次触发。",
                        creator_id=failed_job.creator_id,
                        metadata_json={"error": str(exc), "job_id": job_id},
                    )
                    db.commit()
                    db.refresh(failure_message)
                    await asset_discussion_ws_manager.broadcast(
                        thread.asset_id,
                        {
                            "type": "message_created",
                            "asset_id": thread.asset_id,
                            "thread_id": thread.id,
                            "message": {
                                "id": failure_message.id,
                                "thread_id": failure_message.thread_id,
                                "role": _as_status(failure_message.role),
                                "content": failure_message.content,
                                "creator_id": failure_message.creator_id,
                                "creator_display_name": None,
                                "creator_avatar_svg": None,
                                "metadata_json": failure_message.metadata_json,
                                "created_at": failure_message.created_at.isoformat() if failure_message.created_at else None,
                            },
                        },
                    )
        except Exception as msg_exc:
            logger.warning(f"Failed to append asset AI failure message: {msg_exc}")
    finally:
        context_stack.close()
        db.close()


async def _on_engine_session(session_id: str, job_id: str) -> None:
    if not job_id:
        return
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if job and job.task_id:
            task = db.query(SddTask).filter(SddTask.id == job.task_id).first()
            if task:
                task.session_id = session_id
                db.commit()
    finally:
        db.close()
    await _update_job_state(job_id, session_id=session_id)


async def _on_engine_hitl(
    prompt: str,
    hitl_type: str,
    options: Optional[list],
    context: Optional[str],
    job_id: str,
) -> None:
    if not job_id:
        return
    await _update_job_state(
        job_id,
        status=AiJobStatus.WAITING_HITL,
        progress=58,
        message="Waiting for human input",
        context_patch={
            "pending_hitl": {
                "prompt": prompt,
                "hitl_type": hitl_type,
                "options": options or [],
                "context": context or "",
                "requested_at": datetime.utcnow().isoformat() + "Z",
            }
        },
    )


async def _on_engine_result(
    success: bool,
    result: str,
    duration_ms: Optional[int],
    cost_usd: Optional[float],
    job_id: str,
) -> None:
    if not job_id:
        return
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job or job.status in FINAL_STATUSES:
            return
        if job.status == AiJobStatus.INTERRUPTED:
            return
        if job.status == AiJobStatus.WAITING_HITL and not success:
            db.commit()
            return
    finally:
        db.close()

    if success:
        # 问题定位任务：对话结束后从 AI 会话结果反填「定位结果」卡片
        try:
            await _extract_and_publish_diagnosis_result(job_id, result)
        except Exception:
            logger.exception("Diagnosis result extraction failed; job finalization continues")
        await _update_job_state(
            job_id,
            status=AiJobStatus.SUCCESS,
            progress=100,
            message="AI reply completed",
            result_patch={
                "result_preview": str(result or "")[:1600],
                "duration_ms": duration_ms,
                "cost_usd": cost_usd,
            },
            finalize=True,
        )
        return

    await _update_job_state(
        job_id,
        status=AiJobStatus.FAILED,
        progress=100,
        message="AI execution failed",
        error_message=str(result or "Unknown failure"),
        result_patch={
            "duration_ms": duration_ms,
            "cost_usd": cost_usd,
        },
        finalize=True,
    )


async def _extract_and_publish_diagnosis_result(job_id: str, result_text: str) -> None:
    """DIAGNOSIS 任务：从 AI 会话结果提取结构化定位结果并推送卡片消息。

    拼接该轮（job 创建后）所有 assistant 文本消息，避免 CLI result 事件只携带
    最后一段文本时丢失末尾的 JSON 结果块。
    """
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job or not job.task_id:
            return
        task = db.query(SddTask).filter(SddTask.id == job.task_id).first()
        if not task or task.task_type != "DIAGNOSIS":
            return

        from app.domains.task.models.chat import ChatMessage, MessageRole, MessageType

        turn_texts = []
        since = job.created_at
        rows = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.task_id == task.id,
                ChatMessage.role == MessageRole.ASSISTANT,
                ChatMessage.message_type == MessageType.TEXT,
            )
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            .all()
        )
        if since is not None:
            rows = [row for row in rows if row.created_at is not None and row.created_at >= since]
        for row in rows:
            content = str(row.content or "").strip()
            if content:
                turn_texts.append(content)
        combined = "\n\n".join(turn_texts).strip()
        if not combined:
            combined = str(result_text or "").strip()

        payload = diagnosis_result_service.extract_payload_from_text(combined)
        if payload is None:
            return
        result = diagnosis_result_service.upsert_diagnosis_result_from_ai(
            db,
            task=task,
            payload=payload,
            actor_user_id=str(job.creator_id or ""),
        )
        if result is None or not result.source_chat_message_id:
            return
        message = (
            db.query(ChatMessage)
            .filter(ChatMessage.id == result.source_chat_message_id)
            .first()
        )
        if not message:
            return
        await diagnosis_result_service.publish_diagnosis_result_message(
            db, task=task, message=message
        )
    except Exception:
        logger.exception("Diagnosis result extraction failed")
    finally:
        db.close()


async def _on_engine_error(error_text: str, job_id: str) -> None:
    if not job_id:
        return
    db = SessionLocal()
    try:
        job = db.query(SddAiJob.status).filter(SddAiJob.id == job_id).first()
        if not job or job[0] == AiJobStatus.INTERRUPTED:
            return
    finally:
        db.close()
    await _update_job_state(
        job_id,
        status=AiJobStatus.FAILED,
        progress=100,
        message="AI execution failed",
        error_message=error_text,
        finalize=True,
    )


async def _execute_task_chat_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job or job.channel != AiJobChannel.TASK_CHAT:
            return
        task = db.query(SddTask).filter(SddTask.id == job.task_id).first()
        if not task:
            raise ValueError("Task not found for AI job")
    finally:
        db.close()

    with bind_task_context(
        task_id=task.id,
        workspace_id=task.workspace_id,
        user_id=job.creator_id,
    ), bind_ai_context(
        job_id=job_id,
        task_id=task.id,
        session_id=job.session_id,
        event_type="execute_task_chat_job",
    ):
        prompt = str((job.prompt_text or "")).strip()
        if not prompt:
            raise ValueError("Empty task chat prompt")

        await _update_job_state(
            job_id,
            progress=45,
            message="Dispatching user prompt to AI engine",
            context_patch={"source": "task_chat_user_input"},
        )

        await _run_task_chat_turn(job_id, prompt)


async def _run_task_chat_turn(job_id: str, prompt: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job or not job.task_id:
            return
        task = db.query(SddTask).filter(SddTask.id == job.task_id).first()
        if not task:
            raise ValueError("Task not found")

        context = job.context_json if isinstance(job.context_json, dict) else {}
        fresh_session = bool(context.get("fresh_session"))
        engine = get_engine(task.id)
        if not engine:
            engine = WorkflowEngine(
                task_id=task.id,
                ws_id=task.workspace_id,
                user_id=job.creator_id,
                job_id=job_id,
                on_result=_on_engine_result,
                on_hitl=_on_engine_hitl,
                on_session=_on_engine_session,
                on_error=_on_engine_error,
            )
            if job.session_id and not fresh_session:
                engine.session_id = job.session_id
        else:
            engine.set_job_callbacks(
                job_id=job_id,
                on_result=_on_engine_result,
                on_hitl=_on_engine_hitl,
                on_session=_on_engine_session,
                on_error=_on_engine_error,
            )
            if fresh_session:
                engine.session_id = None
            elif job.session_id:
                # 恢复上次中断（或继续）的会话：总是以 DB 持久化的 session_id
                # 为准，保证下次启动使用 --resume 重新进入原会话，而不是新开会话。
                engine.session_id = job.session_id
    finally:
        db.close()

    with bind_task_context(
        task_id=task.id,
        workspace_id=task.workspace_id,
        user_id=job.creator_id,
    ), bind_ai_context(
        job_id=job_id,
        task_id=task.id,
        session_id=job.session_id,
        event_type="run_task_chat_turn",
    ):
        await _update_job_state(job_id, status=AiJobStatus.RUNNING, progress=55, message="AI is processing")

        if fresh_session:
            await engine.run(prompt, fresh_session=True)
        elif engine.session_id and not engine.running:
            await engine.send_message(prompt, job_id=job_id)
        else:
            await engine.run(prompt)

        await _finalize_task_chat_job_from_engine(job_id, engine)


async def _finalize_task_chat_job_from_engine(job_id: str, engine: WorkflowEngine) -> None:
    # Fallback for missing callback updates.
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if (
            not job
            or job.status in FINAL_STATUSES
            or job.status in {AiJobStatus.WAITING_HITL, AiJobStatus.INTERRUPTED}
        ):
            return
        if engine.last_result_success is True:
            job.status = AiJobStatus.SUCCESS
            job.progress = 100
            job.message = "AI reply completed"
            payload = _merge_json(job.result_json, {"result_preview": (engine.last_result_text or "")[:1600]})
            job.result_json = payload
            job.finished_at = datetime.utcnow()
            db.commit()
            db.refresh(job)
            payload = serialize_job(job)
        else:
            job.status = AiJobStatus.FAILED
            job.progress = 100
            job.message = "AI execution failed"
            job.error_message = (engine.last_result_text or "Unknown error")[:1600]
            job.finished_at = datetime.utcnow()
            db.commit()
            db.refresh(job)
            payload = serialize_job(job)
    finally:
        db.close()
    if engine.last_result_success is True:
        # 问题定位任务兜底：callback 未触发时仍从会话结果反填定位结果卡片
        try:
            await _extract_and_publish_diagnosis_result(job_id, engine.last_result_text)
        except Exception:
            logger.exception("Diagnosis result fallback extraction failed")
    await _broadcast_job_payload(payload, final=True)
    queue_key = str(payload.get("queue_key") or "")
    if queue_key:
        schedule_queue(queue_key)


async def _execute_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job:
            return
        channel = job.channel
    finally:
        db.close()

    with bind_ai_context(job_id=job_id, event_type="execute_job"):
        try:
            if channel == AiJobChannel.ASSET_THREAD:
                await _execute_asset_thread_job(job_id)
                return
            if channel == AiJobChannel.TASK_CHAT:
                await _execute_task_chat_job(job_id)
                return
            raise ValueError(f"Unsupported AI job channel: {channel}")
        except Exception as exc:
            logger.exception(f"AI job execution failed: job={job_id}, error={exc}")
            db = SessionLocal()
            try:
                latest = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
                if not latest or latest.status in FINAL_STATUSES or latest.status == AiJobStatus.INTERRUPTED:
                    return
            finally:
                db.close()
            await _update_job_state(
                job_id,
                status=AiJobStatus.FAILED,
                progress=100,
                message="AI execution failed",
                error_message=str(exc),
                finalize=True,
            )


async def _enqueue_job(job_id: str, expected_channel: Optional[AiJobChannel] = None) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job:
            return None
        if expected_channel and job.channel != expected_channel:
            raise ValueError(f"Job {job_id} channel mismatch")
        payload = serialize_job(job)
        queue_key = job.queue_key
    finally:
        db.close()

    await _broadcast_job_payload(payload, final=False)
    if queue_key:
        schedule_queue(queue_key)
    return payload


async def enqueue_asset_thread_job(job_id: str) -> Optional[Dict[str, Any]]:
    return await _enqueue_job(job_id, expected_channel=AiJobChannel.ASSET_THREAD)


async def enqueue_task_chat_job(job_id: str) -> Optional[Dict[str, Any]]:
    return await _enqueue_job(job_id, expected_channel=AiJobChannel.TASK_CHAT)


async def publish_job(job_id: str, *, final: bool = False) -> None:
    await _publish_job_state(job_id, final=final)


async def run_task_chat_job_now(job_id: str) -> None:
    await _execute_task_chat_job(job_id)


def mark_task_chat_jobs_cancelled(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    message: str = "Task execution stopped",
) -> List[str]:
    jobs = (
        db.query(SddAiJob)
        .filter(
            SddAiJob.workspace_id == workspace_id,
            SddAiJob.task_id == task_id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
            SddAiJob.status.notin_(list(FINAL_STATUSES)),
        )
        .all()
    )
    now = datetime.utcnow()
    job_ids: List[str] = []
    for job in jobs:
        _request_job_cancel(job.id)
        job.status = AiJobStatus.CANCELLED
        job.progress = 100
        job.message = message
        job.error_message = None
        job.finished_at = now
        _clear_cancel_event(job.id)
        job_ids.append(job.id)
    if job_ids:
        db.commit()
    return job_ids


def _merge_hitl_context(
    context_json: Any,
    response: str,
    *,
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    merged = dict(context_json) if isinstance(context_json, dict) else {}
    now_iso = datetime.utcnow().isoformat() + "Z"
    pending_hitl = merged.get("pending_hitl")
    if isinstance(pending_hitl, dict):
        last_hitl = dict(pending_hitl)
        last_hitl["answered_at"] = now_iso
        last_hitl["response"] = response
        if actor_user_id:
            last_hitl["actor_user_id"] = actor_user_id
        merged["last_hitl"] = last_hitl
        merged.pop("pending_hitl", None)

    history = merged.get("hitl_responses")
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "response": response,
            "answered_at": now_iso,
            "actor_user_id": actor_user_id,
        }
    )
    merged["hitl_responses"] = history[-20:]
    return merged


async def _resume_task_chat_job(job_id: str, response: str) -> None:
    try:
        db = SessionLocal()
        task_context: Dict[str, Optional[str]] = {
            "task_id": None,
            "workspace_id": None,
            "user_id": None,
            "session_id": None,
        }
        try:
            job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
            if not job or job.channel != AiJobChannel.TASK_CHAT or not job.task_id:
                return
            task = db.query(SddTask).filter(SddTask.id == job.task_id).first()
            if not task:
                raise ValueError("Task not found")
            task_context = {
                "task_id": task.id,
                "workspace_id": task.workspace_id,
                "user_id": job.creator_id,
                "session_id": job.session_id,
            }

            engine = get_engine(task.id)
            if not engine:
                engine = WorkflowEngine(
                    task_id=task.id,
                    ws_id=task.workspace_id,
                    user_id=job.creator_id,
                    job_id=job_id,
                    on_result=_on_engine_result,
                    on_hitl=_on_engine_hitl,
                    on_session=_on_engine_session,
                    on_error=_on_engine_error,
                )
                if job.session_id:
                    engine.session_id = job.session_id
            else:
                engine.set_job_callbacks(
                    job_id=job_id,
                    on_result=_on_engine_result,
                    on_hitl=_on_engine_hitl,
                    on_session=_on_engine_session,
                    on_error=_on_engine_error,
                )
                if job.session_id:
                    # 恢复中断/HITL 挂起会话：以 DB 持久化的 session_id 为准，
                    # 保证下一步用 --resume 回到原会话而非新开会话。
                    engine.session_id = job.session_id
        finally:
            db.close()

        with bind_task_context(
            task_id=task_context.get("task_id"),
            workspace_id=task_context.get("workspace_id"),
            user_id=task_context.get("user_id"),
        ), bind_ai_context(
            job_id=job_id,
            task_id=task_context.get("task_id"),
            session_id=task_context.get("session_id"),
            event_type="resume_waiting_hitl_job",
        ):
            await _update_job_state(
                job_id,
                status=AiJobStatus.RUNNING,
                progress=70,
                message="Resuming AI job after human input",
            )

            if engine.session_id and not engine.running:
                await engine.send_message(response, job_id=job_id)
            else:
                await engine.run(response)

            await _finalize_task_chat_job_from_engine(job_id, engine)
    except Exception as exc:
        logger.exception(f"Failed to resume HITL AI job {job_id}: {exc}")
        await _update_job_state(
            job_id,
            status=AiJobStatus.FAILED,
            progress=100,
            message="Failed to resume job after HITL",
            error_message=str(exc),
            finalize=True,
        )


async def resume_waiting_hitl_job(
    *,
    task_id: str,
    response: str,
    job_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        query = (
            db.query(SddAiJob)
            .filter(
                SddAiJob.task_id == task_id,
                SddAiJob.channel == AiJobChannel.TASK_CHAT,
                SddAiJob.status == AiJobStatus.WAITING_HITL,
            )
            .order_by(SddAiJob.created_at.asc())
        )
        if job_id:
            query = query.filter(SddAiJob.id == job_id)
        job = query.first()
        if not job:
            return None

        job.status = AiJobStatus.RUNNING
        job.progress = 65
        job.message = "Human response received"
        job.error_message = None
        pending_hitl = job.context_json.get("pending_hitl") if isinstance(job.context_json, dict) else None
        job.context_json = _merge_hitl_context(
            job.context_json,
            response,
            actor_user_id=actor_user_id,
        )
        db.commit()
        db.refresh(job)
        if isinstance(pending_hitl, dict):
            try:
                context_token_service.record_hitl(
                    db,
                    workspace_id=job.workspace_id,
                    task_id=str(job.task_id or ""),
                    ai_job_id=job.id,
                    session_id=job.session_id,
                    prompt=str(pending_hitl.get("prompt") or ""),
                    response=response,
                    source_kind="hitl_response",
                )
            except Exception as exc:
                logger.warning(f"Failed to record HITL context attribution for job {job.id}: {exc}")
        payload = serialize_job(job)
    finally:
        db.close()

    await _broadcast_job_payload(payload, final=False)
    asyncio.create_task(_resume_task_chat_job(payload["id"], response))
    return payload


def cancel_job(
    db: Session,
    *,
    workspace_id: str,
    job_id: str,
) -> Optional[SddAiJob]:
    job = (
        db.query(SddAiJob)
        .filter(
            SddAiJob.id == job_id,
            SddAiJob.workspace_id == workspace_id,
        )
        .first()
    )
    if not job:
        return None
    if job.status in FINAL_STATUSES:
        return job
    _request_job_cancel(job.id)

    job.status = AiJobStatus.CANCELLED
    job.progress = 100
    job.message = "Job cancelled by user"
    job.error_message = None
    job.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    return job
