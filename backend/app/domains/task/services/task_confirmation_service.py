"""Validate confirmation replies and restore their durable conversation state."""

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.offload import run_db_txn
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.task import SddTask, TaskStatus


class ConfirmationClosedError(RuntimeError):
    """A stale question must not become a new task submission."""


def reply_reference(metadata: dict | None) -> tuple[str, str] | None:
    metadata = metadata or {}
    if "interaction_id" in metadata or "reply_to_message_id" in metadata:
        return str(metadata.get("interaction_id") or "").strip(), str(metadata.get("reply_to_message_id") or "").strip()
    return None


_LIVE_CONFIRMATION_STATUSES = {AiJobStatus.RUNNING, AiJobStatus.WAITING_HITL}


def confirmation_owner(db: Session, task: SddTask | None) -> SddAiJob | None:
    if not task or task.status != TaskStatus.AWAITING_INPUT or task.baselined_at or not task.status_run_id:
        return None
    return (
        db.query(SddAiJob)
        .filter_by(
            id=task.status_run_id,
            task_id=task.id,
            channel=AiJobChannel.TASK_CHAT,
            session_generation=task.session_generation,
            cancel_requested_at=None,
        )
        .filter(SddAiJob.status.in_(_LIVE_CONFIRMATION_STATUSES | {AiJobStatus.SUCCESS}))
        .first()
    )


def question_context(message: ChatMessage) -> dict:
    """Snapshot the public question so an answer remains readable on its own."""
    confirmation = (message.metadata_json or {}).get("confirmation") or {}
    return {
        "prompt": message.content,
        "kind": confirmation.get("kind", "text"),
        "fields": confirmation.get("fields", []),
        "options": confirmation.get("options", []),
    }


def enrich_history(db: Session, task_id: str, messages: list[dict]) -> None:
    """Attach question context across page boundaries without rewriting history."""
    targets = {}
    for message in messages:
        metadata = message.get("metadata") or {}
        resolution = metadata.get("confirmation_resolution") or {}
        interaction_id = resolution.get("interaction_id") or metadata.get("interaction_id")
        if interaction_id:
            targets.setdefault(interaction_id, []).append(message)
    if not targets:
        return
    rows = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.task_id == task_id,
            or_(
                ChatMessage.metadata_json["confirmation"]["interaction_id"].as_string().in_(list(targets)),
                (ChatMessage.role == "user")
                & ChatMessage.metadata_json["interaction_id"].as_string().in_(list(targets)),
            ),
        )
        .all()
    )
    questions, answers = {}, {}
    for row in rows:
        metadata = row.metadata_json or {}
        if row.role == "assistant" and metadata.get("confirmation"):
            questions[metadata["confirmation"]["interaction_id"]] = row
        elif row.role == "user" and metadata.get("interaction_id"):
            answers[metadata["interaction_id"], row.session_generation] = row.id
    for interaction_id, items in targets.items():
        question = questions.get(interaction_id)
        for item in items:
            if not question or item.get("session_generation") != question.session_generation:
                continue
            item["metadata"] = {
                **(item.get("metadata") or {}),
                "confirmation_context": {
                    **question_context(question),
                    "answer_message_id": answers.get((interaction_id, question.session_generation)),
                },
            }


def validate_reply_sync(db: Session, task_id: str, interaction_id: str, message_id: str) -> dict:
    task = db.get(SddTask, task_id)
    parent = db.get(ChatMessage, message_id)
    metadata = (parent.metadata_json or {}) if parent else {}
    confirmation = metadata.get("confirmation") or {}
    if (
        not task
        or not parent
        or not interaction_id
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
            ChatMessage.session_generation == task.session_generation,
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
    job = confirmation_owner(db, task)
    allowed = _LIVE_CONFIRMATION_STATUSES if mode == "live" else {AiJobStatus.SUCCESS}
    if not job or job.id != confirmation.get("job_id") or job.status not in allowed:
        raise ConfirmationClosedError("The execution owning this question is not accepting answers.")
    return {"delivery_mode": mode, "job_id": job.id, "context": question_context(parent)}


def validate_turn_reply(db: Session, task_id: str, metadata: dict | None) -> None:
    reference = reply_reference(metadata)
    if reference and validate_reply_sync(db, task_id, *reference)["delivery_mode"] != "turn":
        raise ConfirmationClosedError("This answer must be delivered to the running agent.")


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
