"""Durable replies for questions owned by a running Agent."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.agents.errors import AgentError, AgentInteractionDeliveryUncertain
from app.core.logging import get_logger
from app.core.offload import run_db_txn
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.confirmation_reply import TaskConfirmationReply
from app.domains.task.models.task import SddTask
from app.domains.task.services import task_confirmation_service as questions
from app.domains.task.services import task_event_publisher

logger = get_logger(__name__, category="task_execution")

# This preserves a definitive provider ACK across a database outage in the
# same process. OpenCode also replays matching terminal answers after restart.
_delivery_outcomes: dict[str, tuple[bool, str | None]] = {}
_UNCERTAIN_GRACE = timedelta(minutes=2)
_FINISHED_JOBS = {
    AiJobStatus.SUCCESS,
    AiJobStatus.FAILED,
    AiJobStatus.CANCELLED,
    AiJobStatus.INTERRUPTED,
    AiJobStatus.REVERTED,
}


@dataclass(frozen=True)
class ReplyRequest:
    task_id: str
    actor_id: str
    client_id: str
    interaction_id: str
    question_id: str
    content: str
    value: Any


@dataclass(frozen=True)
class ReplyResult:
    status: str
    message: dict | None = None
    error: str | None = None


@dataclass(frozen=True)
class _Reservation:
    id: str
    job_id: str
    deliver: bool


def _lock_task(db: Session, task_id: str) -> SddTask | None:
    return db.query(SddTask).filter_by(id=task_id).with_for_update().first()


def _reserve(db: Session, request: ReplyRequest) -> _Reservation | None:
    task = _lock_task(db, request.task_id)
    if task is None:
        raise questions.ConfirmationClosedError("Task not found.")
    existing = (
        db.query(TaskConfirmationReply)
        .filter_by(task_id=task.id, creator_id=request.actor_id, client_message_id=request.client_id)
        .first()
    )
    if existing:
        if (
            existing.question_id != request.question_id
            or existing.interaction_id != request.interaction_id
            or existing.content != request.content
            or json.dumps(existing.confirmation_value, sort_keys=True) != json.dumps(request.value, sort_keys=True)
        ):
            raise questions.ConfirmationClosedError("This message ID is already bound to a different answer.")
        return _Reservation(existing.id, existing.job_id, False)

    parent = questions.load_question(db, task.id, request.interaction_id, request.question_id)
    if questions.delivery_mode(task, parent) == "turn":
        return None
    if not request.client_id or len(request.client_id) > 128 or not request.content.strip():
        raise questions.ConfirmationClosedError("A reply needs a valid message ID and an answer.")
    confirmation = questions.validate_reply_sync(db, task.id, request.interaction_id, parent.id)
    if (
        db.query(TaskConfirmationReply.id)
        .filter(
            TaskConfirmationReply.question_id == parent.id,
            TaskConfirmationReply.status.in_(["SENDING", "ACCEPTED"]),
        )
        .first()
    ):
        raise questions.ConfirmationClosedError("An answer for this question is already being confirmed.")
    receipt = TaskConfirmationReply(
        task_id=task.id,
        job_id=confirmation["job_id"],
        question_id=parent.id,
        creator_id=request.actor_id,
        client_message_id=request.client_id,
        interaction_id=request.interaction_id,
        content=request.content,
        confirmation_value=request.value,
        status="SENDING",
    )
    db.add(receipt)
    db.flush()
    return _Reservation(receipt.id, receipt.job_id, True)


def _locked_receipt(db: Session, receipt_id: str) -> tuple[SddTask | None, TaskConfirmationReply | None]:
    task_id = db.query(TaskConfirmationReply.task_id).filter_by(id=receipt_id).scalar()
    task = _lock_task(db, task_id) if task_id else None
    return task, db.get(TaskConfirmationReply, receipt_id) if task else None


def _record_outcome(db: Session, receipt_id: str, accepted: bool, error: str | None) -> None:
    _, receipt = _locked_receipt(db, receipt_id)
    if receipt and receipt.status == "SENDING":
        receipt.status = "ACCEPTED" if accepted else "FAILED"
        receipt.error_message = error


def _message_payload(db: Session, message: ChatMessage) -> dict:
    from app.domains.task.services.task_session_turn_service import _chat_message_event_dto

    return {**_chat_message_event_dto(db, message), "can_undo": False}


def _settle(db: Session, receipt_id: str) -> ReplyResult:
    task, receipt = _locked_receipt(db, receipt_id)
    if task is None or receipt is None:
        return ReplyResult("failed", error="This question is no longer available.")
    if receipt.status == "DELIVERED":
        return ReplyResult("duplicate", _message_payload(db, db.get(ChatMessage, receipt.message_id)))
    if receipt.status == "FAILED":
        return ReplyResult("failed", error=receipt.error_message)
    if receipt.status == "SENDING":
        job = db.get(SddAiJob, receipt.job_id)
        if receipt.updated_at <= datetime.utcnow() - _UNCERTAIN_GRACE and (
            job.status in _FINISHED_JOBS or task.status_run_id != receipt.job_id
        ):
            receipt.status = "FAILED"
            receipt.error_message = "The execution ended before the answer delivery could be confirmed."
            return ReplyResult("failed", error=receipt.error_message)
        return ReplyResult("processing")

    from app.domains.task.services.task_session_turn_service import persist_confirmation_reply

    parent = db.get(ChatMessage, receipt.question_id)
    message = persist_confirmation_reply(
        db,
        task=task,
        parent=parent,
        actor_user_id=receipt.creator_id,
        content=receipt.content,
        client_message_id=receipt.client_message_id,
        interaction_id=receipt.interaction_id,
        confirmation_value=receipt.confirmation_value,
    )
    receipt.status = "DELIVERED"
    receipt.message_id = message.id
    job = db.get(SddAiJob, receipt.job_id)
    questions.sync_waiting_status(db, task, job, event_key=f"confirmation-reply:{receipt.id}")
    payload = _message_payload(db, message)
    task_event_publisher.queue_chat_message(db, task.id, payload)
    return ReplyResult("accepted", payload)


def _matches_answer(db: Session, receipt: TaskConfirmationReply, resolution: dict) -> bool:
    status = resolution.get("status")
    if status in {"approved", "rejected"}:
        rejected = receipt.content.strip().lower() in {"reject", "n", "no", "false"}
        return status == ("rejected" if rejected else "approved")
    if status != "answered" or resolution.get("answer") is None:
        return False
    try:
        expected = json.loads(receipt.content)
    except ValueError:
        expected = None
    if not isinstance(expected, dict):
        fields = questions.question_context(db.get(ChatMessage, receipt.question_id))["fields"]
        if len(fields) == 1 and fields[0].get("type") == "string":
            expected = {fields[0]["key"]: receipt.content}
    return expected == resolution["answer"]


def observe_resolution(db: Session, job: SddAiJob, resolution: dict) -> None:
    """Use a matching provider outcome to recover a lost transport ACK."""
    receipt = (
        db.query(TaskConfirmationReply)
        .filter_by(job_id=job.id, interaction_id=resolution.get("interaction_id"), status="SENDING")
        .first()
    )
    if receipt and _matches_answer(db, receipt, resolution):
        receipt.status = "ACCEPTED"


async def _flush_outcome(receipt_id: str) -> None:
    outcome = _delivery_outcomes.get(receipt_id)
    if outcome is not None:
        await run_db_txn(lambda db: _record_outcome(db, receipt_id, *outcome))
        _delivery_outcomes.pop(receipt_id, None)


async def submit(request: ReplyRequest) -> ReplyResult | None:
    """Reserve under the caller's task lock, then deliver at most once per receipt."""
    from app.domains.ai.services.jobs.executors import task_chat

    reservation = await run_db_txn(lambda db: _reserve(db, request))
    if reservation is None:
        return None
    try:
        if reservation.deliver:
            try:
                accepted = await task_chat.deliver_confirmation_response(
                    task_id=request.task_id,
                    interaction_id=request.interaction_id,
                    response=request.content,
                    job_id=reservation.job_id,
                )
            except AgentInteractionDeliveryUncertain as exc:
                return ReplyResult("processing", error=str(exc))
            except AgentError as exc:
                _delivery_outcomes[reservation.id] = (False, str(exc))
            else:
                _delivery_outcomes[reservation.id] = (
                    accepted,
                    None if accepted else "This question is closed or its execution is recovering.",
                )
        await _flush_outcome(reservation.id)
        result = await run_db_txn(lambda db: _settle(db, reservation.id))
    except Exception:
        logger.exception("Confirmation reply deferred: receipt_id={}", reservation.id)
        return ReplyResult("processing", error="The answer delivery is being reconciled.")
    task_event_publisher.wake()
    return result


def _recoverable_receipts(db: Session) -> list[str]:
    receipt = TaskConfirmationReply
    return [
        receipt_id
        for (receipt_id,) in db.query(receipt.id)
        .join(SddAiJob, SddAiJob.id == receipt.job_id)
        .join(SddTask, SddTask.id == receipt.task_id)
        .filter(
            or_(
                receipt.status == "ACCEPTED",
                (receipt.status == "SENDING")
                & (receipt.updated_at <= datetime.utcnow() - _UNCERTAIN_GRACE)
                & or_(
                    SddAiJob.status.in_(_FINISHED_JOBS),
                    SddTask.status_run_id.is_distinct_from(receipt.job_id),
                ),
            )
        )
        .order_by(receipt.updated_at, receipt.id)
        .limit(50)
        .all()
    ]


async def recover() -> None:
    for receipt_id in list(_delivery_outcomes)[:50]:
        try:
            await _flush_outcome(receipt_id)
        except Exception:
            logger.exception("Confirmation provider acknowledgement deferred: receipt_id={}", receipt_id)
    for receipt_id in await run_db_txn(_recoverable_receipts):
        try:
            await run_db_txn(lambda db, receipt_id=receipt_id: _settle(db, receipt_id))
        except Exception:
            logger.exception("Confirmation reply recovery deferred: receipt_id={}", receipt_id)
    task_event_publisher.wake()
