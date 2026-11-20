"""Durable replies for questions owned by a running Agent."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

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

# Only a direct provider ACK can attribute an answer to this user. Retain it
# in memory until its transaction commits, including across a database outage.
_delivery_outcomes: dict[str, tuple[str, bool, str | None]] = {}
_recovering: dict[str, asyncio.Task] = {}
_MAX_RECOVERING = 4
_PENDING_RECHECK = timedelta(seconds=4)
_SEND_TIMEOUT = 35
_SENDING_RECHECK = timedelta(seconds=45)
_RECOVERY_WINDOW = timedelta(minutes=3)
_OPEN_DELIVERIES = {"PENDING", "SENDING"}
_NOT_CONFIRMED = "The answer delivery could not be confirmed. Refresh the question before retrying."
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
class _Delivery:
    task_id: str
    job_id: str
    interaction_id: str
    content: str
    status: str
    token: str | None


def _lock_task(db: Session, task_id: str) -> SddTask | None:
    return db.query(SddTask).filter_by(id=task_id).with_for_update().first()


def _reserve(db: Session, request: ReplyRequest) -> str | None:
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
        return existing.id

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
            TaskConfirmationReply.status.in_(_OPEN_DELIVERIES | {"ACCEPTED"}),
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
        status="PENDING",
    )
    db.add(receipt)
    db.flush()
    return receipt.id


def _locked_receipt(db: Session, receipt_id: str) -> tuple[SddTask | None, TaskConfirmationReply | None]:
    task_id = db.query(TaskConfirmationReply.task_id).filter_by(id=receipt_id).scalar()
    task = _lock_task(db, task_id) if task_id else None
    return task, db.get(TaskConfirmationReply, receipt_id) if task else None


def _record_outcome(db: Session, receipt_id: str, token: str | None, accepted: bool, error: str | None) -> None:
    _, receipt = _locked_receipt(db, receipt_id)
    if receipt and receipt.status == "SENDING" and receipt.delivery_token == token:
        receipt.status = "ACCEPTED" if accepted else "FAILED"
        receipt.error_message = error


def _due_delivery(db: Session, receipt_id: str, *, recovery: bool) -> _Delivery | None:
    task, receipt = _locked_receipt(db, receipt_id)
    if task is None or receipt is None or receipt.status not in _OPEN_DELIVERIES:
        return None
    now = datetime.utcnow()
    if receipt.status == "SENDING" and (not recovery or receipt.updated_at > now - _SENDING_RECHECK):
        return None
    job = db.get(SddAiJob, receipt.job_id)
    if job.status in _FINISHED_JOBS or task.status_run_id != receipt.job_id:
        receipt.status = "FAILED"
        receipt.error_message = "The execution ended before the answer delivery could be confirmed."
        return None
    if receipt.created_at <= now - _RECOVERY_WINDOW:
        receipt.status = "FAILED"
        receipt.error_message = _NOT_CONFIRMED
        return None
    return _Delivery(task.id, job.id, receipt.interaction_id, receipt.content, receipt.status, receipt.delivery_token)


def _claim_delivery(db: Session, receipt_id: str, delivery: _Delivery) -> str | None:
    task, receipt = _locked_receipt(db, receipt_id)
    if task is None or receipt is None or (receipt.status, receipt.delivery_token) != (delivery.status, delivery.token):
        return None
    try:
        owner = questions.validate_reply_sync(db, task.id, receipt.interaction_id, receipt.question_id)
        if owner["delivery_mode"] != "live" or owner["job_id"] != receipt.job_id:
            raise questions.ConfirmationClosedError("The execution owning this question has changed.")
    except questions.ConfirmationClosedError as exc:
        receipt.status = "FAILED"
        receipt.error_message = str(exc)
        return None
    receipt.status = "SENDING"
    receipt.delivery_token = token = str(uuid4())
    # The lease starts in the same commit as the claim, before any provider I/O.
    receipt.updated_at = datetime.utcnow()
    return token


def _defer_delivery(db: Session, receipt_id: str, token: str | None, status: str) -> None:
    _, receipt = _locked_receipt(db, receipt_id)
    if receipt and receipt.status == "SENDING" and receipt.delivery_token == token:
        receipt.status = status
        receipt.updated_at = datetime.utcnow()


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
    if receipt.status != "ACCEPTED":
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


async def _flush_outcome(receipt_id: str) -> None:
    outcome = _delivery_outcomes.get(receipt_id)
    if outcome is not None:
        await run_db_txn(lambda db: _record_outcome(db, receipt_id, *outcome))
        if _delivery_outcomes.get(receipt_id) == outcome:
            _delivery_outcomes.pop(receipt_id, None)


async def _deliver(receipt_id: str, delivery: _Delivery) -> str | None:
    from app.domains.ai.services.jobs.executors import task_chat

    address = {"task_id": delivery.task_id, "interaction_id": delivery.interaction_id, "job_id": delivery.job_id}
    if delivery.status == "SENDING":
        pending = await task_chat.confirmation_is_pending(**address)
        if pending is False:
            await run_db_txn(lambda db: _record_outcome(db, receipt_id, delivery.token, False, _NOT_CONFIRMED))
            return None
        if pending is None:
            await run_db_txn(lambda db: _defer_delivery(db, receipt_id, delivery.token, "SENDING"))
            return None

    token = await run_db_txn(lambda db: _claim_delivery(db, receipt_id, delivery))
    if token is None:
        return None
    try:
        async with asyncio.timeout(_SEND_TIMEOUT):
            accepted = await task_chat.deliver_confirmation_response(response=delivery.content, **address)
    except (AgentInteractionDeliveryUncertain, TimeoutError):
        return _NOT_CONFIRMED
    except AgentError as exc:
        _delivery_outcomes[receipt_id] = (token, False, str(exc))
    else:
        if accepted:
            _delivery_outcomes[receipt_id] = (token, True, None)
        else:
            # The engine has no route for this question yet. This attempt sent
            # nothing, so preserve the previous delivery state.
            await run_db_txn(lambda db: _defer_delivery(db, receipt_id, token, delivery.status))
    await _flush_outcome(receipt_id)
    return None


async def _advance(receipt_id: str, *, recovery: bool) -> ReplyResult:
    await _flush_outcome(receipt_id)
    delivery = await run_db_txn(lambda db: _due_delivery(db, receipt_id, recovery=recovery))
    message = await _deliver(receipt_id, delivery) if delivery else None
    result = await run_db_txn(lambda db: _settle(db, receipt_id))
    task_event_publisher.wake()
    return ReplyResult("processing", error=message) if result.status == "processing" and message else result


async def submit(request: ReplyRequest) -> ReplyResult | None:
    """Commit the user's intent before exposing it to a provider transport."""
    receipt_id = await run_db_txn(lambda db: _reserve(db, request))
    if receipt_id is None:
        return None
    try:
        return await _advance(receipt_id, recovery=False)
    except Exception:
        logger.exception("Confirmation reply deferred: receipt_id={}", receipt_id)
        return ReplyResult("processing", error="The answer delivery is being reconciled.")


def _recoverable_receipts(db: Session) -> list[tuple[str, str]]:
    receipt = TaskConfirmationReply
    now = datetime.utcnow()
    return (
        db.query(receipt.id, receipt.status)
        .filter(
            or_(
                receipt.status == "ACCEPTED",
                (receipt.status == "PENDING") & (receipt.updated_at <= now - _PENDING_RECHECK),
                (receipt.status == "SENDING") & (receipt.updated_at <= now - _SENDING_RECHECK),
            )
        )
        .order_by((receipt.status != "ACCEPTED"), receipt.updated_at, receipt.id)
        .limit(50)
        .all()
    )


async def _recover_delivery(receipt_id: str) -> None:
    try:
        await _advance(receipt_id, recovery=True)
    except Exception:
        logger.exception("Confirmation reply recovery deferred: receipt_id={}", receipt_id)
    finally:
        _recovering.pop(receipt_id, None)


async def recover() -> None:
    for receipt_id in list(_delivery_outcomes)[:50]:
        try:
            await _flush_outcome(receipt_id)
        except Exception:
            logger.exception("Confirmation provider acknowledgement deferred: receipt_id={}", receipt_id)
    for receipt_id, status in await run_db_txn(_recoverable_receipts):
        if status == "ACCEPTED":
            try:
                await run_db_txn(lambda db, receipt_id=receipt_id: _settle(db, receipt_id))
            except Exception:
                logger.exception("Confirmation reply recovery deferred: receipt_id={}", receipt_id)
        elif receipt_id not in _recovering and len(_recovering) < _MAX_RECOVERING:
            _recovering[receipt_id] = asyncio.create_task(_recover_delivery(receipt_id))
    task_event_publisher.wake()
