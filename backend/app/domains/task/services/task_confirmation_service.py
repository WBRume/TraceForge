"""Validate confirmation replies and restore their durable conversation state."""

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.offload import run_db_txn
from app.domains.ai.models.ai_job import SddAiJob
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.task import SddTask


class ConfirmationClosedError(RuntimeError):
    """A stale question must not become a new task submission."""


def validate_reply_sync(db: Session, task_id: str, interaction_id: str, message_id: str) -> dict:
    task = db.get(SddTask, task_id)
    parent = db.get(ChatMessage, message_id)
    metadata = (parent.metadata_json or {}) if parent else {}
    confirmation = metadata.get("confirmation") or {}
    if (
        not task
        or not parent
        or parent.task_id != task_id
        or parent.role != "assistant"
        or confirmation.get("interaction_id") != interaction_id
        or parent.session_generation != task.session_generation
    ):
        raise ConfirmationClosedError("This question is no longer available in the current session.")
    resolved = (
        db.query(ChatMessage.id)
        .filter(
            ChatMessage.task_id == task_id,
            or_(
                (ChatMessage.role == "assistant")
                & (
                    ChatMessage.metadata_json["confirmation_resolution"]["interaction_id"].as_string() == interaction_id
                ),
                (ChatMessage.role == "user")
                & (ChatMessage.metadata_json["interaction_id"].as_string() == interaction_id),
            ),
        )
        .first()
    )
    if resolved:
        raise ConfirmationClosedError("This question has already been answered or closed. Refresh the conversation.")
    mode = confirmation.get("delivery_mode") or ("live" if task.agent_backend in {"opencode", "dsh"} else "turn")
    if mode == "live":
        job = db.get(SddAiJob, confirmation.get("job_id"))
        if (
            not job
            or job.task_id != task_id
            or job.status not in {"RUNNING", "WAITING_HITL"}
            or task.status in {"INTERRUPTED", "DONE", "FAILED", "BASELINED"}
        ):
            raise ConfirmationClosedError("The execution owning this question has ended.")
    return {"delivery_mode": mode, "job_id": confirmation.get("job_id")}


async def validate_reply(task_id: str, interaction_id: str, message_id: str) -> dict:
    return await run_db_txn(lambda db: validate_reply_sync(db, task_id, interaction_id, message_id))


def snapshot_messages(db: Session, task_id: str, generation: int, job_ids: list[str]) -> list[ChatMessage]:
    """Include older questions and outcomes even outside the recent history page."""
    if not job_ids:
        return []
    rows = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.task_id == task_id,
            ChatMessage.session_generation == generation,
            ChatMessage.role == "assistant",
            or_(
                ChatMessage.metadata_json["confirmation"]["job_id"].as_string().in_(job_ids),
                ChatMessage.metadata_json["confirmation_resolution"]["job_id"].as_string().in_(job_ids),
            ),
        )
        .all()
    )
    prompt_ids = [row.id for row in rows if (row.metadata_json or {}).get("confirmation")]
    if prompt_ids:
        rows.extend(
            db.query(ChatMessage)
            .filter(
                ChatMessage.task_id == task_id,
                ChatMessage.role == "user",
                ChatMessage.metadata_json["reply_to_message_id"].as_string().in_(prompt_ids),
            )
            .all()
        )
    return rows
