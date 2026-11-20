"""Send an instruction to the current task run and persist its delivery status."""

import asyncio
import json
from collections.abc import Callable
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
from sqlalchemy.orm import Session

from app.agents.errors import AgentError, AgentSteeringClosedError
from app.core.distributed_lock import lock_task
from app.core.logging import get_logger
from app.core.offload import run_db_txn
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.chat_submission import TaskChatSubmission
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.models.task_event_outbox import TaskEventOutbox
from app.domains.task.services import reading_capture_service, task_session_service
from app.domains.task.services.chat_submission_service import SubmissionError, require_chat_actor, wake_event_publisher
from app.domains.task.services.repository_updates.storage import require_available
from app.engine.session.registry import get_engine

logger = get_logger(__name__, category="task_execution")


def _publish(db: Session, message: ChatMessage) -> dict:
    payload = task_session_service._chat_message_event_dto(db, message)
    db.add(
        TaskEventOutbox(
            event_id=str(uuid4()),
            task_id=message.task_id,
            payload_json={"event_type": "chat_message", **payload},
        )
    )
    return payload


def _prepare(
    db: Session, *, ws_id, task_id, actor_id, job_id, client_id, content, message_id, run_token, session_id
) -> tuple[dict, bool]:
    task = db.query(SddTask).filter_by(id=task_id, workspace_id=ws_id).one_or_none()
    if task is None:
        raise SubmissionError("Task not found", "TASK_NOT_FOUND", 404)
    require_chat_actor(db, task, actor_id)
    existing = db.get(ChatMessage, message_id)
    if existing:
        if existing.content != content or (existing.metadata_json or {}).get("steering", {}).get("job_id") != job_id:
            raise SubmissionError("相同消息标识不能用于不同的引导指令", "MESSAGE_CONFLICT")
        return task_session_service._chat_message_event_dto(db, existing), False
    if task.status != TaskStatus.RUNNING or not session_id or not run_token:
        raise SubmissionError("当前回合已结束或尚未准备好接收引导", "STEERING_NOT_RUNNING")
    try:
        require_available(task)
    except ValueError as exc:
        raise SubmissionError(str(exc), "REPOSITORY_UPDATE_BUSY") from exc
    job = (
        db.query(SddAiJob)
        .filter_by(id=job_id, task_id=task_id, channel=AiJobChannel.TASK_CHAT)
        .with_for_update()
        .first()
    )
    if (
        job is None
        or job.status != AiJobStatus.RUNNING
        or job.cancel_requested_at is not None
        or job.run_token != run_token
        or job.session_id != session_id
        or job.session_generation != task.session_generation
        or job.session_revision != task.session_revision
    ):
        raise SubmissionError("当前回合已变化，请确认后重新发送", "STEERING_NOT_RUNNING")
    metadata = {"client_message_id": client_id, "steering": {"job_id": job_id, "status": "pending"}}
    submission = db.query(TaskChatSubmission.id).filter_by(ai_job_id=job.id).first()
    if submission:
        metadata.update(submission_id=submission[0], knowledge_state="pending")
    message = task_session_service._new_chat_message(
        db,
        message_id=message_id,
        task_id=task_id,
        workspace_id=ws_id,
        actor_user_id=actor_id,
        content=content,
        metadata_json=metadata,
        session_generation=int(task.session_generation or 0),
    )
    message.session_turn_id = job.session_turn_id
    reading_capture_service.record_message_change(db, task_id=task_id, message=message)
    return _publish(db, message), True


def _set_status(db: Session, message: ChatMessage, status: str) -> None:
    metadata = dict(message.metadata_json or {})
    message.metadata_json = {**metadata, "steering": {**metadata["steering"], "status": status}}
    _publish(db, message)


def _update_message(db: Session, job_id: str, message_id: str, status: str) -> dict | None:
    message = db.query(ChatMessage).filter_by(id=message_id).with_for_update().one_or_none()
    if message is None:
        return None
    steering = (message.metadata_json or {}).get("steering") or {}
    if steering.get("job_id") != job_id:
        return None
    if steering.get("status") == "pending":
        _set_status(db, message, status)
    return task_session_service._chat_message_event_dto(db, message)


async def mark_delivered(job_id: str, message_id: str) -> None:
    if len(message_id) != 36:
        return
    await run_db_txn(lambda db: _update_message(db, job_id, message_id, "delivered"))
    await wake_event_publisher()


def finalize_in_txn(db: Session, job: SddAiJob) -> None:
    steering = ChatMessage.metadata_json["steering"]
    messages = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.task_id == job.task_id,
            ChatMessage.session_generation == job.session_generation,
            steering["job_id"].as_string() == job.id,
            steering["status"].as_string() == "pending",
        )
        .with_for_update()
        .all()
    )
    for message in messages:
        _set_status(db, message, "failed")


async def submit(
    *, ws_id: str, task_id: str, actor_id: str, job_id: str, client_id: str, content: str, run_txn: Callable
) -> dict:
    client_id, content = client_id.strip(), content.strip()
    if not client_id or not content:
        raise SubmissionError("引导指令和消息标识不能为空", "MESSAGE_INVALID", 422)
    message_id = str(uuid5(NAMESPACE_URL, json.dumps(["task-steering", task_id, actor_id, client_id])))
    async with lock_task(task_id):
        engine = get_engine(task_id)
        active = bool(engine and engine.can_steer(job_id))
        receipt, created = await run_txn(
            lambda db: _prepare(
                db,
                ws_id=ws_id,
                task_id=task_id,
                actor_id=actor_id,
                job_id=job_id,
                client_id=client_id,
                content=content,
                message_id=message_id,
                run_token=engine.attempt.run_token if active and engine.attempt else None,
                session_id=engine.session_id if active else None,
            )
        )
        if not created:
            return receipt
        await wake_event_publisher()
        try:
            async with asyncio.timeout(8):
                await engine.steer(job_id, message_id, content)
        except AgentSteeringClosedError:
            receipt = await run_txn(lambda db: _update_message(db, job_id, message_id, "failed")) or receipt
            await wake_event_publisher()
        except (AgentError, httpx.HTTPError, TimeoutError, OSError) as exc:
            # A lost acknowledgement can still be followed by a native
            # delivery event. The owning run closes any remaining pending input.
            logger.warning(
                "Steering receipt uncertain: job={}, message={}, error={}", job_id, message_id, type(exc).__name__
            )
        return receipt
