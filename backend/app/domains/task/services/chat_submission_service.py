"""Durable ordinary-chat acceptance and recovery; receipts are never knowledge sources.

Preparation retains the existing checkpoint-before-message boundary.  Execution
messages are private to the conversation until the owning job succeeds.

Every receipt state change commits one ``task_event_outbox`` row in the same
transaction; a background publisher relays it into the task WebSocket room so
clients converge from events instead of periodic polling.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_

from app.core.distributed_lock import LockAcquireTimeout, lock_task
from app.core.logging import get_logger
from app.core.offload import run_db, run_db_txn
from app.config import settings
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.chat_submission import TaskChatSubmission
from app.domains.task.models.task import SddTask
from app.domains.task.models.task_event_outbox import TaskEventOutbox
from app.domains.task.services.task_attempt_recovery_service import BLOCKING, recover_task_attempts

logger = get_logger(__name__, category="task_execution")
_runners: dict[str, asyncio.Task] = {}

# PREPARING → {EXECUTING, FAILED}; EXECUTING → {SUCCEEDED, FAILED}.  Terminal
# states are final; the fallback reconciler re-validates before converging.
_ALLOWED_TRANSITIONS = {
    "PREPARING": {"EXECUTING", "FAILED"},
    "EXECUTING": {"SUCCEEDED", "FAILED"},
}


class SubmissionError(ValueError):
    def __init__(self, message: str, code: str = "TASK_SESSION_BUSY", status_code: int = 409):
        super().__init__(message)
        self.code, self.status_code = code, status_code


def serialize(row):
    return dict(id=row.id, task_id=row.task_id, client_message_id=row.client_message_id,
                content=row.content, status=row.status, creator_id=row.creator_id,
                ai_job_id=row.ai_job_id, chat_message_id=row.chat_message_id,
                error_message=row.error_message, version=int(row.version or 1),
                created_at=row.created_at.isoformat() if row.created_at else None)


def validate_transition(row, target_status):
    allowed = _ALLOWED_TRANSITIONS.get(str(row.status or ""))
    if not allowed or target_status not in allowed:
        raise SubmissionError("受理状态不允许该变更", "SUBMISSION_INVALID_TRANSITION")


def _event_payload(row, *, message=None, job=None):
    payload = dict(
        event_id=str(uuid4()),
        task_id=row.task_id,
        session_generation=int(row.session_generation or 0),
        session_revision=int(row.session_revision or 0),
        receipt=serialize(row),
    )
    if message is not None:
        payload["message"] = message
    if job is not None:
        payload["job"] = job
    return payload


def save_task_event_outbox(db, *, row, message=None, job=None):
    """Queue the publish for the receipt's committed state; same transaction as the change.

    The caller has already advanced ``row.status``/``row.version``; this helper
    only records the event so a crash between commit and broadcast still
    recovers through the publisher.
    """
    payload = _event_payload(row, message=message, job=job)
    db.add(TaskEventOutbox(event_id=payload["event_id"], task_id=row.task_id,
                           receipt_id=row.id, receipt_version=int(row.version or 1),
                           payload_json=payload))


async def wake_event_publisher():
    """Best-effort prompt after a transaction that wrote outbox rows committed."""
    from app.domains.task.services import task_event_publisher
    task_event_publisher.wake()


def assert_no_preparing_submission(db, task_id, allowed_id=None):
    db.query(SddTask).filter_by(id=task_id).with_for_update().first()
    row = db.query(TaskChatSubmission).filter(
        TaskChatSubmission.active_task_id == task_id,
        TaskChatSubmission.status == "PREPARING",
    ).first()
    if row and row.id != allowed_id:
        raise SubmissionError("当前消息正在准备，请等待完成")


def _existing_submission_sync(db, task_id, actor_id, client_id, content, metadata):
    task = db.query(SddTask).filter(SddTask.id == task_id).with_for_update().one_or_none()
    if task is None:
        raise SubmissionError("Task not found", "TASK_NOT_FOUND", 404)
    fingerprint = hashlib.sha256(json.dumps([content, metadata], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    previous = db.query(TaskChatSubmission).filter_by(
        task_id=task_id, creator_id=actor_id, client_message_id=client_id,
    ).first()
    if previous:
        if previous.payload_hash != fingerprint:
            raise SubmissionError("相同消息标识不能用于不同内容", "MESSAGE_CONFLICT")
        return serialize(previous)
    if str(getattr(task.status, "value", task.status)) in {"PENDING", "PROVISIONING", "DONE", "FAILED", "BASELINED", "INTERRUPTED"}:
        raise SubmissionError("当前任务状态不允许发送普通消息")
    return None


def _accept_sync(db, task_id, actor_id, client_id, content, metadata):
    previous = _existing_submission_sync(db, task_id, actor_id, client_id, content, metadata)
    if previous is not None:
        return previous
    task = db.get(SddTask, task_id)
    fingerprint = hashlib.sha256(json.dumps([content, metadata], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if db.query(SddAiJob.id).filter(
        SddAiJob.task_id == task_id, SddAiJob.channel == AiJobChannel.TASK_CHAT,
        SddAiJob.status.in_([AiJobStatus.TERMINATING, AiJobStatus.ORPHANED]),
    ).first():
        raise SubmissionError("旧回合尚未清理完成，请稍后重试", "TASK_ATTEMPT_RECOVERY_PENDING")
    if db.query(TaskChatSubmission.id).filter_by(active_task_id=task_id).first():
        raise SubmissionError("当前消息正在准备或执行，请等待完成")
    from app.domains.task.models.session_turn import TaskSessionOperation, TaskSessionOperationStatus
    if db.query(TaskSessionOperation.id).filter_by(
            task_id=task_id, status=TaskSessionOperationStatus.REVERTING).first():
        raise SubmissionError("当前会话正在撤销，请等待完成")
    if db.query(SddAiJob.id).filter(SddAiJob.task_id == task_id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT, SddAiJob.status.in_(BLOCKING)).first():
        raise SubmissionError("当前回合正在执行，请等待完成")
    row = TaskChatSubmission(task_id=task_id, workspace_id=task.workspace_id,
        creator_id=actor_id, client_message_id=client_id, content=content,
        metadata_json=metadata, payload_hash=fingerprint, active_task_id=task_id,
        status="PREPARING", version=1, session_generation=int(task.session_generation or 0),
        session_revision=int(task.session_revision or 0))
    db.add(row)
    db.flush()
    save_task_event_outbox(db, row=row)
    return serialize(row)


async def accept(*, task_id, actor_id, client_message_id, content, metadata=None):
    client_id, text = str(client_message_id or "").strip(), str(content or "").strip()
    if not client_id or len(client_id) > 128 or not text:
        raise SubmissionError("消息内容和消息标识不能为空", "MESSAGE_INVALID", 400)
    clean = dict(metadata or {})
    # These fields are exclusively server-owned.
    for key in ("submission_id", "knowledge_state", "client_message_id"):
        clean.pop(key, None)
    try:
        # Return a durable duplicate even when its runner holds the task lock.
        receipt = await run_db_txn(lambda db: _existing_submission_sync(db, task_id, actor_id, client_id, text, clean))
        if receipt is None:
            async with lock_task(task_id):
                receipt = await run_db_txn(lambda db: _existing_submission_sync(db, task_id, actor_id, client_id, text, clean))
                if receipt is None:
                    await recover_task_attempts(task_id, run_txn=run_db_txn)
                    # Commit receipt cleanup even if a separate blocker still
                    # prevents accepting this message in the next transaction.
                    await run_db_txn(lambda db: _reconcile_sync(db, task_id=task_id))
                    try:
                        receipt = await run_db_txn(lambda db: _accept_sync(db, task_id, actor_id, client_id, text, clean))
                    except IntegrityError as exc:
                        try:
                            receipt = await run_db_txn(lambda db: _accept_sync(db, task_id, actor_id, client_id, text, clean))
                        except IntegrityError:
                            raise SubmissionError("当前消息正在准备或执行，请稍后重试") from exc
    except LockAcquireTimeout as exc:
        raise SubmissionError("当前任务正在处理其他请求，请稍后重试") from exc
    schedule(receipt["id"])
    await wake_event_publisher()
    return receipt


def _load_preparation(db, submission_id):
    row = db.get(TaskChatSubmission, submission_id)
    if not row or row.status != "PREPARING":
        return None
    task = db.get(SddTask, row.task_id)
    if not task or str(getattr(task.status, "value", task.status)) in {"DONE", "FAILED", "BASELINED", "INTERRUPTED"} or (int(task.session_generation or 0), int(task.session_revision or 0)) != (
            row.session_generation, row.session_revision):
        _transition(db, row, "FAILED", error_message="会话已改变，本次发送未执行")
        return None
    return dict(task_id=row.task_id, actor_user_id=row.creator_id, content=row.content,
                client_message_id=row.client_message_id,
                context_json={**(row.metadata_json or {}), "submission_id": row.id,
                              "knowledge_state": "pending"})


def _transition(db, row, target_status, *, error_message=None):
    """Advance one receipt inside the caller's transaction and queue its event."""
    validate_transition(row, target_status)
    row.status = target_status
    row.version = int(row.version or 1) + 1
    if target_status in {"FAILED", "SUCCEEDED"}:
        row.active_task_id = None
    if error_message is not None:
        row.error_message = error_message
    save_task_event_outbox(db, row=row)
    return row


def _fail_sync(db, submission_id, message):
    row = db.query(TaskChatSubmission).filter_by(id=submission_id).with_for_update().one_or_none()
    # A commit may have completed despite a lost caller. Never mark a durable job unsent.
    if row and row.status == "PREPARING" and not row.ai_job_id:
        _transition(db, row, "FAILED", error_message=message)


async def _run(submission_id):
    from app.domains.ai.services import ai_job_service
    from app.domains.task.services import task_session_service
    try:
        task_id = await run_db(lambda: _task_id_sync(submission_id))
        if not task_id:
            return
        async with lock_task(task_id):
            prepared = await run_db_txn(lambda db: _load_preparation(db, submission_id))
            if prepared is None:
                await wake_event_publisher()
                return
            logger.info("Chat preparation started: task_id={}, submission_id={}", task_id, submission_id)
            created = await task_session_service.create_task_chat_turn(**prepared)
        await ai_job_service.enqueue_task_chat_job(created.job_id)
        await wake_event_publisher()
        logger.info("Chat preparation completed: task_id={}, submission_id={}, job_id={}",
                    task_id, submission_id, created.job_id)
    except LockAcquireTimeout:
        # Another process may be preparing this receipt. Dispatcher retries only
        # after acquiring that same task lock; no concurrent checkpoint publication.
        return
    except asyncio.CancelledError:
        # Durable receipt remains recoverable after shutdown/worker loss.
        raise
    except Exception:
        logger.exception("Chat preparation failed: submission_id={}", submission_id)
        await run_db_txn(lambda db: _fail_sync(db, submission_id, "消息准备失败，请重试"))
        await wake_event_publisher()


def _task_id_sync(submission_id):
    from app.database import SessionLocal
    with SessionLocal() as db:
        row = db.get(TaskChatSubmission, submission_id)
        return row.task_id if row else None


def schedule(submission_id):
    if submission_id in _runners:
        return
    if len(_runners) >= max(1, settings.GIT_OFFLOAD_WORKERS):
        return  # The durable dispatcher schedules remaining receipts later.
    task = asyncio.create_task(_run(submission_id))
    _runners[submission_id] = task
    def finished(done):
        _runners.pop(submission_id, None)
        if not done.cancelled() and done.exception():
            logger.error("Chat submission runner failed: submission_id={}, error={}", submission_id, done.exception())
    task.add_done_callback(finished)


def _publish_knowledge(db, task, job, row):
    """Mark the turn's messages published; search capture creates its outbox atomically."""
    if task and job.session_turn_id and int(task.session_generation or 0) == int(job.session_generation or 0):
        for message in db.query(ChatMessage).filter(ChatMessage.session_turn_id == job.session_turn_id).all():
            meta = dict(message.metadata_json or {})
            if meta.get("submission_id") == row.id:
                message.metadata_json = {**meta, "knowledge_state": "published"}


def finalize_submission_in_txn(db, job, final_status):
    """Converge the job's receipt inside the convergence transaction; returns the row or None.

    Called from the single business-finalize point so a normally finished job
    updates its submission and queues the event in the same commit.  No new
    ChatMessage is invented on failure.
    """
    success = str(final_status) == str(AiJobStatus.SUCCESS.value) or final_status == AiJobStatus.SUCCESS
    row = (
        db.query(TaskChatSubmission).filter_by(ai_job_id=job.id).with_for_update().one_or_none()
        if job.id else None
    )
    if row is None or row.status != "EXECUTING":
        return None
    task = db.query(SddTask).filter_by(id=row.task_id).first()
    _transition(db, row, "SUCCEEDED" if success else "FAILED",
                error_message=None if success else "本轮执行未成功，内容未进入知识检索")
    if success:
        _publish_knowledge(db, task, job, row)
    return row


def _reconcile_sync(db, task_id=None):
    scope = TaskChatSubmission.task_id == task_id if task_id is not None else True
    pending = [row.id for row in db.query(TaskChatSubmission.id).filter_by(status="PREPARING").filter(scope).order_by(
        TaskChatSubmission.created_at, TaskChatSubmission.id).limit(100).all()]
    # Long-running jobs must not occupy the entire recovery page and starve
    # terminal receipts belonging to later tasks.
    rows = db.query(TaskChatSubmission).outerjoin(SddAiJob, SddAiJob.id == TaskChatSubmission.ai_job_id).filter(
        scope,
        TaskChatSubmission.active_task_id.isnot(None), TaskChatSubmission.status == "EXECUTING",
        or_(SddAiJob.id.is_(None), SddAiJob.status.notin_(BLOCKING)),
    ).order_by(
        TaskChatSubmission.task_id, TaskChatSubmission.id).limit(100).all()
    for row in rows:
        # Follow the same task-before-message lock order as search capture and acceptance.
        task = db.query(SddTask).filter_by(id=row.task_id).with_for_update().one_or_none()
        row = db.query(TaskChatSubmission).filter_by(id=row.id).populate_existing().with_for_update().one_or_none()
        if row is None or row.status != "EXECUTING":
            continue
        job = db.get(SddAiJob, row.ai_job_id) if row.ai_job_id else None
        if job is not None and job.status in BLOCKING:
            continue
        success = job is not None and job.status == AiJobStatus.SUCCESS
        _transition(db, row, "SUCCEEDED" if success else "FAILED",
                    error_message=None if success else "本轮执行未成功，内容未进入知识检索")
        if success:
            _publish_knowledge(db, task, job, row)
        row.updated_at = datetime.utcnow()
    return pending


async def recover():
    for submission_id in await run_db_txn(_reconcile_sync):
        schedule(submission_id)
    await wake_event_publisher()


def build_session_state(db, task_id, *, actor_id, client_message_ids=None):
    """One snapshot for initialization and exception recovery.

    The active receipt plus any receipts addressed by the caller's unconfirmed
    idempotency keys are returned with their jobs and formal messages, so a
    client never depends on a "recent 50" window to resolve an old UNKNOWN.
    """
    task = db.get(SddTask, task_id)
    if not task:
        return None
    receipts = {}
    active = db.query(TaskChatSubmission).filter_by(active_task_id=task_id).first()
    if active:
        receipts[active.id] = active
    keys = [str(value or "").strip() for value in (client_message_ids or []) if str(value or "").strip()]
    if keys:
        for row in db.query(TaskChatSubmission).filter(
                TaskChatSubmission.task_id == task_id,
                TaskChatSubmission.creator_id == actor_id,
                TaskChatSubmission.client_message_id.in_(keys)).all():
            receipts.setdefault(row.id, row)
    jobs = {}
    messages = {}
    for row in receipts.values():
        if row.ai_job_id and row.ai_job_id not in jobs:
            job = db.get(SddAiJob, row.ai_job_id)
            if job:
                jobs[job.id] = job
        if row.chat_message_id and row.chat_message_id not in messages:
            message = db.get(ChatMessage, row.chat_message_id)
            if message:
                messages[message.id] = message
    from app.domains.ai.services import ai_job_service
    for job in ai_job_service.list_task_jobs(db, task_id=task_id, active_only=True):
        jobs.setdefault(job.id, job)
    from app.domains.task.services import task_service
    ordered = task_service.sort_chat_messages(list(messages.values()))
    return {
        "task_id": task_id,
        "session_generation": int(task.session_generation or 0),
        "session_revision": int(task.session_revision or 0),
        "receipts": [serialize(row) for row in receipts.values()],
        "jobs": [ai_job_service.serialize_job(job) for job in jobs.values()],
        "messages": task_service.serialize_history_messages(
            db, task, ordered, task.workspace_id, task_id),
    }


async def shutdown():
    tasks = list(_runners.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
