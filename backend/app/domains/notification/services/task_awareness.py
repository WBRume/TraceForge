"""Capture actual transitions inside the owning transaction; never perform I/O."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import inspect

from app.config import settings
from app.domains.ai.models.ai_job import SddAiJob
from app.domains.auth.models.user import User, Workspace
from app.domains.notification.models.task_awareness import TaskAwarenessEvent
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.task import SddTask

LONG_RUN_SECONDS = 10
DEFAULT_EVENTS = ["AI_HITL_SUSPENDED", "AI_RUN_FINISHED", "AI_RUN_ERROR"]
RUNTIME_EVENTS = [*DEFAULT_EVENTS, "AI_RUN_INTERRUPTED"]
BUSINESS_EVENTS = ["TASK_INITIALIZED", "TASK_COMPLETED", "TASK_FAILED"]


def value(item):
    return str(getattr(item, "value", item) or "")


def iso(item):
    return item.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if item else None


def run_state(job):
    status = value(job.status)
    if status in {"RUNNING", "WAITING_HITL"}:
        return "AI_HITL_SUSPENDED" if job.awareness_pending_json or status == "WAITING_HITL" else "AI_RUNNING"
    if status == "SUCCESS":
        return "AI_RUN_FINISHED"
    if status in {"FAILED", "ORPHANED"}:
        return "AI_RUN_ERROR"
    if status == "INTERRUPTED":
        if job.interrupted_by_id:
            return "AI_RUN_INTERRUPTED"
        if job.error_message:
            return "AI_RUN_ERROR"
    return "AI_RUN_STOPPED"


def task_context(db, *, task_id, workspace_id, initiator_id):
    task = db.get(SddTask, task_id)
    workspace = db.get(Workspace, workspace_id)
    creator = db.get(User, initiator_id)
    url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/workspaces/{workspace_id}/chat/{task_id}"
    return {
        "workspace": {"id": workspace_id, "name": workspace.name if workspace else ""},
        "task": {"id": task_id, "title": task.name if task else "", "url": url,
                 "session_generation": task.session_generation if task else None},
        "initiator": {"id": initiator_id, "name": creator.display_name if creator else ""},
    }


def run_payload(db, job, *, summary=None):
    context = job.context_json if isinstance(job.context_json, dict) else {}
    state = job.awareness_state or run_state(job)
    return {
        "schema_version": 1, "event_type": state,
        **task_context(db, task_id=job.task_id, workspace_id=job.workspace_id, initiator_id=job.creator_id),
        "run": {"id": job.id, "version": int(job.awareness_version or 0),
                "started_at": iso(job.started_at), "finished_at": iso(job.finished_at),
                "client_message_id": context.get("client_message_id"),
                "session_generation": job.session_generation},
        "summary": str(summary or (job.interrupt_reason if state == "AI_RUN_INTERRUPTED" else None) or job.error_message or job.message or "")[:500],
    }


def capture_job(db, job, *, allow_start=False, summary=None):
    if not job.task_id or value(job.channel) != "TASK_CHAT" or not job.started_at:
        return
    # A historical record first read after deployment must never become an event.
    if not job.awareness_state and not allow_start:
        return
    state = run_state(job)
    if job.awareness_state == state:
        return
    job.awareness_state = state
    job.awareness_version = int(job.awareness_version or 0) + 1
    if state in {"AI_RUN_FINISHED", "AI_RUN_ERROR", "AI_RUN_INTERRUPTED", "AI_RUN_STOPPED"}:
        job.awareness_pending_json = []
    now = datetime.utcnow()
    event_id = str(uuid4())
    payload = run_payload(db, job, summary=summary)
    payload.update(event_id=event_id, occurred_at=iso(now))
    db.add(TaskAwarenessEvent(
        id=event_id, event_key=f"run:{job.id}:{job.awareness_version}", creator_id=job.creator_id,
        workspace_id=job.workspace_id, task_id=job.task_id, job_id=job.id,
        event_type=state, payload_json=payload, available_at=now, created_at=now,
    ))


def capture_flush(db):
    # Only new confirmation/reply messages affect HITL. Reading messages is inert.
    for message in list(db.new):
        if not isinstance(message, ChatMessage):
            continue
        metadata = message.metadata_json if isinstance(message.metadata_json, dict) else {}
        confirmation = metadata.get("confirmation")
        job = None
        prompt = None
        if value(message.role) == "assistant" and isinstance(confirmation, dict):
            job = db.query(SddAiJob).filter(SddAiJob.id == confirmation.get("job_id")).with_for_update().first()
            if job and job.awareness_state and value(job.status) in {"RUNNING", "WAITING_HITL"}:
                interaction = str(confirmation.get("interaction_id") or "")
                if interaction:
                    job.awareness_pending_json = list(dict.fromkeys([*(job.awareness_pending_json or []), interaction]))
                    prompt = message.content
        elif value(message.role) == "user" and metadata.get("interaction_id"):
            parent = db.get(ChatMessage, metadata.get("reply_to_message_id"))
            parent_meta = parent.metadata_json if parent and isinstance(parent.metadata_json, dict) else {}
            parent_confirmation = parent_meta.get("confirmation") or {}
            job = db.query(SddAiJob).filter(SddAiJob.id == parent_confirmation.get("job_id")).with_for_update().first()
            if job and job.awareness_state:
                job.awareness_pending_json = [item for item in job.awareness_pending_json or [] if item != metadata["interaction_id"]]
        if job:
            capture_job(db, job, summary=prompt)
    for job in list(db.dirty):
        if isinstance(job, SddAiJob) and inspect(job).attrs.status.history.has_changes():
            capture_job(db, job)


def capture_business(db, task, actor_id, event_type, summary=""):
    if event_type not in BUSINESS_EVENTS:
        raise ValueError("Unsupported business event")
    if event_type == "TASK_INITIALIZED":
        event_key = f"business:{task.id}:initialize:{task.session_generation}"
        if db.query(TaskAwarenessEvent.id).filter_by(event_key=event_key).first():
            return
        task.business_state = "TASK_IN_PROGRESS"
    elif task.business_state == event_type:
        return
    else:
        task.business_state = event_type
        event_key = f"business:{task.id}:{uuid4()}"
    # A committed manual action is independent of any AI runtime or duration.
    now = datetime.utcnow()
    event_id = str(uuid4())
    payload = {"schema_version": 1, "event_id": event_id, "event_type": event_type, "occurred_at": iso(now),
               **task_context(db, task_id=task.id, workspace_id=task.workspace_id, initiator_id=actor_id),
               "run": None, "summary": str(summary or "")[:500]}
    payload["actor"] = payload["initiator"].copy()
    db.add(TaskAwarenessEvent(id=event_id, event_key=event_key,
                             creator_id=actor_id, workspace_id=task.workspace_id, task_id=task.id,
                             job_id=None, event_type=event_type, payload_json=payload, available_at=now, created_at=now))


def webhook_eligible(event, job, now=None):
    now = now or datetime.utcnow()
    if event.event_type in BUSINESS_EVENTS:
        return True
    if event.event_type not in RUNTIME_EVENTS or not job or not job.started_at:
        return False
    if event.event_type == "AI_HITL_SUSPENDED" and (job.awareness_state != "AI_HITL_SUSPENDED"
        or event.payload_json.get("run", {}).get("version") != job.awareness_version):
        return False
    ended = job.finished_at or now
    return (ended - job.started_at).total_seconds() >= LONG_RUN_SECONDS
