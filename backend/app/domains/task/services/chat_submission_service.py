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
from functools import partial
from uuid import uuid4

from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.core.distributed_lock import LockAcquireTimeout, lock_task
from app.core.logging import get_logger
from app.core.offload import run_db, run_db_txn
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services.jobs.store import row_has_leaked_interrupted_ownership
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.chat_submission import TaskChatSubmission
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.models.task_event_outbox import TaskEventOutbox
from app.domains.task.services import agent_session_switch
from app.domains.task.services import status_machine as sm
from app.domains.task.services.conversation import history as task_conversation_history
from app.domains.task.services.task_attempt_recovery_service import (
    BLOCKING,
    active_statuses,
    blocking_attempt_predicate,
    recover_task_attempts,
)

logger = get_logger(__name__, category="task_execution")
_runners: dict[str, asyncio.Task] = {}
PRE_INPUT_CLIENT_ID_PREFIX = "pre-input:"

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


def require_chat_actor(db, task, actor_id):
    from app.domains.auth.models.user import WorkspacePermission
    from app.domains.local_resource.client import ResourceError
    from app.domains.local_resource.service import require_operation
    from app.domains.workspace.services import workspace_service

    if task.execution_location != "LOCAL" and not workspace_service.user_has_permission(
        db, task.workspace_id, actor_id, WorkspacePermission.START_TASK
    ):
        raise SubmissionError("No permission to send messages in this task", "TASK_WRITE_FORBIDDEN", 403)
    try:
        require_operation(db, task, actor_id)
    except ResourceError as exc:
        raise SubmissionError(str(exc), exc.code, exc.status_code) from exc


def serialize(row):
    return {
        "id": row.id,
        "task_id": row.task_id,
        "client_message_id": row.client_message_id,
        "content": row.content,
        "status": row.status,
        "creator_id": row.creator_id,
        "ai_job_id": row.ai_job_id,
        "chat_message_id": row.chat_message_id,
        "error_message": row.error_message,
        "version": int(row.version or 1),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def validate_transition(row, target_status):
    allowed = _ALLOWED_TRANSITIONS.get(str(row.status or ""))
    if not allowed or target_status not in allowed:
        raise SubmissionError("受理状态不允许该变更", "SUBMISSION_INVALID_TRANSITION")


def _event_payload(row, *, message=None, job=None):
    payload = {
        "event_id": str(uuid4()),
        "task_id": row.task_id,
        "session_generation": int(row.session_generation or 0),
        "session_revision": int(row.session_revision or 0),
        "receipt": serialize(row),
    }
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
    db.add(
        TaskEventOutbox(
            event_id=payload["event_id"],
            task_id=row.task_id,
            receipt_id=row.id,
            receipt_version=int(row.version or 1),
            payload_json=payload,
        )
    )


async def wake_event_publisher():
    """Best-effort prompt after a transaction that wrote outbox rows committed."""
    from app.domains.task.services import task_event_publisher

    task_event_publisher.wake()


def assert_no_preparing_submission(db, task_id, allowed_id=None, *, initialization_id=None):
    from app.domains.task.services.repository_updates.storage import require_available

    task = db.query(SddTask).filter_by(id=task_id).with_for_update().first()
    try:
        require_available(task, initialization_id=initialization_id)
    except ValueError as exc:
        raise SubmissionError(str(exc), "REPOSITORY_UPDATE_BUSY") from exc
    row = (
        db.query(TaskChatSubmission)
        .filter(
            TaskChatSubmission.active_task_id == task_id,
            TaskChatSubmission.status == "PREPARING",
        )
        .first()
    )
    if row and row.id != allowed_id:
        raise SubmissionError("当前消息正在准备，请等待完成")


def _existing_submission_sync(db, task_id, actor_id, client_id, content, metadata, *, allow_recovered_interrupt=False):
    task = db.query(SddTask).filter(SddTask.id == task_id).with_for_update().one_or_none()
    if task is None:
        raise SubmissionError("Task not found", "TASK_NOT_FOUND", 404)
    require_chat_actor(db, task, actor_id)
    fingerprint = hashlib.sha256(
        json.dumps([content, metadata], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    previous = (
        db.query(TaskChatSubmission)
        .filter_by(
            task_id=task_id,
            creator_id=actor_id,
            client_message_id=client_id,
        )
        .first()
    )
    if previous:
        if previous.payload_hash != fingerprint:
            raise SubmissionError("相同消息标识不能用于不同内容", "MESSAGE_CONFLICT")
        return serialize(previous)
    if str(getattr(task.status, "value", task.status)) in {
        "INITIALIZED",
        "PROVISIONING",
        "COMPLETED",
        "FAILED",
        "BASELINED",
    } or (task.status == "INTERRUPTED" and not allow_recovered_interrupt):
        raise SubmissionError("当前任务状态不允许发送普通消息")
    return None


def _accept_sync(
    db,
    task_id,
    actor_id,
    client_id,
    content,
    metadata,
    *,
    after_recovery=False,
    failed_check=None,
    replacement_check=None,
):
    previous = _existing_submission_sync(
        db, task_id, actor_id, client_id, content, metadata, allow_recovered_interrupt=after_recovery
    )
    if previous is not None:
        return previous
    task = db.get(SddTask, task_id)
    from app.domains.task.services.repository_updates.storage import require_available

    try:
        require_available(task)
    except ValueError as exc:
        raise SubmissionError(str(exc), "REPOSITORY_UPDATE_BUSY") from exc
    fingerprint = hashlib.sha256(
        json.dumps([content, metadata], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    if (
        db.query(SddAiJob.id)
        .filter(
            SddAiJob.task_id == task_id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
            SddAiJob.status.in_([AiJobStatus.TERMINATING, AiJobStatus.ORPHANED]),
        )
        .first()
    ):
        raise SubmissionError("旧回合尚未清理完成，请稍后重试", "TASK_ATTEMPT_RECOVERY_PENDING")
    if db.query(TaskChatSubmission.id).filter_by(active_task_id=task_id).first():
        raise SubmissionError("当前消息正在准备或执行，请等待完成")
    from app.domains.task.models.session_turn import TaskSessionOperation, TaskSessionOperationStatus

    if (
        db.query(TaskSessionOperation.id)
        .filter(
            TaskSessionOperation.task_id == task_id,
            TaskSessionOperation.status.in_([TaskSessionOperationStatus.REVERTING, TaskSessionOperationStatus.FAILED]),
        )
        .first()
    ):
        raise SubmissionError("当前会话正在撤销，请等待完成")
    if (
        db.query(SddAiJob.id)
        .filter(SddAiJob.task_id == task_id, SddAiJob.channel == AiJobChannel.TASK_CHAT, blocking_attempt_predicate())
        .first()
    ):
        raise SubmissionError("当前回合正在执行，请等待完成")
    from app.agents.model_selection import apply_task_selection

    try:
        apply_task_selection(db, task, metadata.get("agent_model"))
    except ValueError as exc:
        raise SubmissionError(str(exc), "MODEL_SELECTION_INVALID", 422) from exc
    # Preserve the caller's exact metadata/hash for durable duplicate detection.
    # The task preference is frozen into the job when preparing this receipt.
    if after_recovery and task.status == "INTERRUPTED":
        # This same send requested continuation before recovery stopped a stale
        # attempt. All blockers were checked above; retain its session/context.
        sm.dispatch(db, task, sm.Trigger.RESUME, event_key=f"recovered-input:{client_id}", actor_id=actor_id)
        task.error_message = None
        task.interrupt_reason = None
        task.interrupted_by_id = None
        task.interrupted_at = None
    stored_metadata = dict(metadata)
    if failed_check:
        stored_metadata["_agent_session_check_failed"] = failed_check
    if replacement_check:
        stored_metadata["_agent_session_replacement_check"] = replacement_check
    row = TaskChatSubmission(
        task_id=task_id,
        workspace_id=task.workspace_id,
        creator_id=actor_id,
        client_message_id=client_id,
        content=content,
        metadata_json=stored_metadata,
        payload_hash=fingerprint,
        active_task_id=task_id,
        status="PREPARING",
        version=1,
        session_generation=int(task.session_generation or 0),
        session_revision=int(task.session_revision or 0),
    )
    db.add(row)
    db.flush()
    if task.status in {TaskStatus.ROUND_COMPLETED, TaskStatus.AWAITING_INPUT}:
        sm.dispatch(db, task, sm.Trigger.INPUT_SUBMITTED, event_key=f"input:{row.id}", actor_id=actor_id)
    from app.domains.workspace_collaboration.hooks import request_input

    request_input(db, task, row)
    save_task_event_outbox(db, row=row)
    return serialize(row)


async def accept(*, task_id, actor_id, client_message_id, content, metadata=None, new_agent_session=False):
    client_id, text = str(client_message_id or "").strip(), str(content or "").strip()
    if not client_id or len(client_id) > 128 or not text:
        raise SubmissionError("消息内容和消息标识不能为空", "MESSAGE_INVALID", 400)
    if client_id.lower().startswith(PRE_INPUT_CLIENT_ID_PREFIX):
        raise SubmissionError("该消息标识由协作预输入保留", "MESSAGE_INVALID", 400)
    clean = dict(metadata or {})
    # These fields are exclusively server-owned.
    for key in (
        "submission_id",
        "knowledge_state",
        "client_message_id",
        "steering",
        "_collaboration_control",
        "_new_agent_session",
        "_agent_session_check_failed",
        "_agent_session_replacement_check",
        "fresh_session",
        "agent_service_replacement",
        "resume_interrupted",
        "resumed_from_job_id",
        "resumed_by_id",
        "resumed_at",
    ):
        clean.pop(key, None)
    if new_agent_session:
        clean["_new_agent_session"] = True
    try:
        # Return a durable duplicate even when its runner holds the task lock.
        receipt = await run_db_txn(lambda db: _existing_submission_sync(db, task_id, actor_id, client_id, text, clean))
        if receipt is None:
            async with lock_task(task_id):
                receipt = await run_db_txn(
                    lambda db: _existing_submission_sync(db, task_id, actor_id, client_id, text, clean)
                )
                if receipt is None:
                    await recover_task_attempts(task_id, run_txn=run_db_txn)
                    # Commit receipt cleanup even if a separate blocker still
                    # prevents accepting this message in the next transaction.
                    await run_db_txn(lambda db: _reconcile_sync(db, task_id=task_id))
                    key, status = await agent_session_switch.check_task_session(task_id, new_session=new_agent_session)
                    accept_sync = partial(
                        _accept_sync,
                        task_id=task_id,
                        actor_id=actor_id,
                        client_id=client_id,
                        content=text,
                        metadata=clean,
                        after_recovery=True,
                        failed_check=key if status is None else None,
                        replacement_check=key if new_agent_session else None,
                    )
                    try:
                        receipt = await run_db_txn(accept_sync)
                    except IntegrityError as exc:
                        try:
                            receipt = await run_db_txn(accept_sync)
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
    if (
        not task
        or task.baselined_at is not None
        or str(getattr(task.status, "value", task.status)) in {"COMPLETED", "FAILED", "BASELINED", "INTERRUPTED"}
        or (int(task.session_generation or 0), int(task.session_revision or 0))
        != (row.session_generation, row.session_revision)
    ):
        _fail_sync(db, submission_id, "会话已改变，本次发送未执行")
        return None
    from app.domains.workspace_collaboration.hooks import input_ready
    from app.domains.workspace_collaboration.service import local_input_expired

    if not input_ready(db, row.task_id, row.id):
        if local_input_expired(db, row.task_id, row.id):
            _fail_sync(db, submission_id, "本地协同输入已过期，请重新发送")
        return None
    control = (row.metadata_json or {}).get("_collaboration_control") or {}
    return {
        "task_id": row.task_id,
        "actor_user_id": row.creator_id,
        "content": row.content,
        "prompt_text": control.get("prompt"),
        "fresh_session": bool(control.get("fresh_session")),
        "replace_agent_session": bool((row.metadata_json or {}).get("_new_agent_session")),
        "agent_session_replacement_check": (row.metadata_json or {}).get("_agent_session_replacement_check"),
        "failed_session_check": (row.metadata_json or {}).get("_agent_session_check_failed"),
        "client_message_id": row.client_message_id,
        "context_json": {**(row.metadata_json or {}), "submission_id": row.id, "knowledge_state": "pending"},
    }


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
    """Close a preparation and its task state in the same transaction."""
    task_id = db.query(TaskChatSubmission.task_id).filter_by(id=submission_id).scalar()
    if not task_id:
        return None
    task = db.query(SddTask).filter_by(id=task_id).populate_existing().with_for_update().one_or_none()
    row = db.query(TaskChatSubmission).filter_by(id=submission_id).populate_existing().with_for_update().one_or_none()
    # A commit may have completed despite a lost caller.
    if row is None or row.status != "PREPARING" or row.ai_job_id:
        return None
    from app.domains.workspace_collaboration import service as collaboration

    collaboration.abandon_input(db, task_id, submission_id)
    if (
        task is not None
        and task.status == TaskStatus.RUNNING
        and task.baselined_at is None
        and row.active_task_id == task_id
        and (row.session_generation, row.session_revision) == (task.session_generation, task.session_revision)
        and not active_statuses(db, task_id)
    ):
        sm.dispatch(
            db,
            task,
            sm.Trigger.INPUT_PREPARATION_FAILED,
            event_key=f"input-failed:{submission_id}",
            reason=message,
        )
        task.interrupt_reason = message
        task.interrupted_by_id = None
        task.interrupted_at = datetime.utcnow()
        task.error_message = None
    return _transition(db, row, "FAILED", error_message=message)


async def _run(submission_id):
    from app.domains.ai.services.jobs.publishing import enqueue_task_chat_job
    from app.domains.task.services import task_session_service
    from app.domains.workspace_collaboration.service import CollaborationError

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
        await enqueue_task_chat_job(created.job_id)
        await wake_event_publisher()
        logger.info(
            "Chat preparation completed: task_id={}, submission_id={}, job_id={}",
            task_id,
            submission_id,
            created.job_id,
        )
    except LockAcquireTimeout:
        # Another process may be preparing this receipt. Dispatcher retries only
        # after acquiring that same task lock; no concurrent checkpoint publication.
        return
    except asyncio.CancelledError:
        # Durable receipt remains recoverable after shutdown/worker loss.
        raise
    except (agent_session_switch.SessionSwitchError, CollaborationError) as exc:
        message = str(exc)
        logger.warning("Chat preparation rejected: submission_id={}, code={}", submission_id, exc.code)
        await run_db_txn(lambda db: _fail_sync(db, submission_id, message))
        await wake_event_publisher()
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
    row = db.query(TaskChatSubmission).filter_by(ai_job_id=job.id).with_for_update().one_or_none() if job.id else None
    if row is None or row.status != "EXECUTING":
        return None
    task = db.query(SddTask).filter_by(id=row.task_id).first()
    _transition(
        db,
        row,
        "SUCCEEDED" if success else "FAILED",
        error_message=None if success else "本轮执行未成功，内容未进入知识检索",
    )
    if success:
        _publish_knowledge(db, task, job, row)
    return row


def _recover_execution_status(db, task, receipt, job):
    if (
        task is None
        or task.baselined_at is not None
        or task.status not in {TaskStatus.RUNNING, TaskStatus.AWAITING_INPUT}
        or (receipt.session_generation, receipt.session_revision) != (task.session_generation, task.session_revision)
    ):
        return
    event_key = f"submission-recovery:{receipt.id}"
    if job is not None:
        if job.id != task.status_run_id:
            return
        trigger = sm.Trigger.ROUND_FINISHED if job.status == AiJobStatus.SUCCESS else sm.Trigger.EXECUTION_INTERRUPTED
        sm.execution_event(
            db,
            task,
            trigger,
            event_key=event_key,
            job_id=job.id,
            generation=int(job.session_generation or 0),
            revision=int(job.session_revision or 0),
        )
    elif not active_statuses(db, task.id):
        reason = "本轮执行记录缺失，请重新发送消息"
        sm.dispatch(db, task, sm.Trigger.EXECUTION_LOST, event_key=event_key, reason=reason)
        task.interrupt_reason = reason
        task.interrupted_at = datetime.utcnow()
        task.interrupted_by_id = None


def _reconcile_sync(db, task_id=None):
    from app.domains.workspace_collaboration.models import CollaborationState

    scope = TaskChatSubmission.task_id == task_id if task_id is not None else True
    now = datetime.utcnow()
    cloud_input = TaskChatSubmission.metadata_json["collaboration"].as_string().is_(None)
    pending = [
        row.id
        for row in db.query(TaskChatSubmission.id)
        .join(SddTask, SddTask.id == TaskChatSubmission.task_id)
        .outerjoin(
            CollaborationState,
            and_(CollaborationState.task_id == TaskChatSubmission.task_id, CollaborationState.enabled.is_(True)),
        )
        .filter(
            TaskChatSubmission.status == "PREPARING",
            scope,
            or_(
                CollaborationState.task_id.is_(None),
                SddTask.session_generation != TaskChatSubmission.session_generation,
                SddTask.session_revision != TaskChatSubmission.session_revision,
                SddTask.status.in_([TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.INTERRUPTED]),
                SddTask.baselined_at.isnot(None),
                and_(
                    CollaborationState.pending_submission_id == TaskChatSubmission.id,
                    or_(
                        and_(CollaborationState.lease_expires_at <= now, ~cloud_input),
                        and_(
                            CollaborationState.sync_phase == "PREPARING",
                            CollaborationState.input_submission_id == TaskChatSubmission.id,
                            or_(CollaborationState.lease_expires_at > now, cloud_input),
                        ),
                    ),
                ),
            ),
        )
        .order_by(TaskChatSubmission.created_at, TaskChatSubmission.id)
        .limit(100)
        .all()
    ]
    # Long-running jobs must not occupy the entire recovery page and starve
    # terminal receipts belonging to later tasks.
    rows = (
        db.query(TaskChatSubmission)
        .outerjoin(SddAiJob, SddAiJob.id == TaskChatSubmission.ai_job_id)
        .filter(
            scope,
            TaskChatSubmission.active_task_id.isnot(None),
            TaskChatSubmission.status == "EXECUTING",
            or_(SddAiJob.id.is_(None), ~blocking_attempt_predicate()),
        )
        .order_by(TaskChatSubmission.task_id, TaskChatSubmission.id)
        .limit(100)
        .all()
    )
    for row in rows:
        # Follow the same task-before-message lock order as search capture and acceptance.
        task = db.query(SddTask).filter_by(id=row.task_id).populate_existing().with_for_update().one_or_none()
        row = db.query(TaskChatSubmission).filter_by(id=row.id).populate_existing().with_for_update().one_or_none()
        if row is None or row.status != "EXECUTING":
            continue
        job = db.get(SddAiJob, row.ai_job_id) if row.ai_job_id else None
        if job is not None and (job.status in BLOCKING or row_has_leaked_interrupted_ownership(job)):
            continue
        _recover_execution_status(db, task, row, job)
        success = job is not None and job.status == AiJobStatus.SUCCESS
        _transition(
            db,
            row,
            "SUCCEEDED" if success else "FAILED",
            error_message=None if success else "本轮执行未成功，内容未进入知识检索",
        )
        if success:
            _publish_knowledge(db, task, job, row)
        row.updated_at = datetime.utcnow()
    return pending


async def recover():
    from app.domains.task.services.task_session_undo_finalization import recover_pending_undos
    from app.domains.workspace_collaboration.hooks import recover_deliveries

    await recover_deliveries()
    await recover_pending_undos()
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
        for row in (
            db.query(TaskChatSubmission)
            .filter(
                TaskChatSubmission.task_id == task_id,
                TaskChatSubmission.creator_id == actor_id,
                TaskChatSubmission.client_message_id.in_(keys),
            )
            .all()
        ):
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
    from app.domains.ai.services.jobs.store import list_task_jobs, serialize_job

    for job in list_task_jobs(db, task_id=task_id, active_only=True):
        jobs.setdefault(job.id, job)

    from app.domains.task.services.task_confirmation_service import snapshot_messages

    for message in snapshot_messages(db, task_id, int(task.session_generation or 0), list(jobs)):
        messages.setdefault(message.id, message)

    ordered = task_conversation_history.sort_chat_messages(list(messages.values()))
    return {
        **sm.snapshot(task),
        "session_generation": int(task.session_generation or 0),
        "session_revision": int(task.session_revision or 0),
        "receipts": [serialize(row) for row in receipts.values()],
        "jobs": [serialize_job(job) for job in jobs.values()],
        "messages": task_conversation_history.serialize_history_messages(db, task, ordered, task.workspace_id, task_id),
    }


async def shutdown():
    tasks = list(_runners.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
