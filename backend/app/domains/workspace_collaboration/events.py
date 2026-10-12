"""Commit small collaboration version references with the state transition."""

from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.domains.task.models.task_event_outbox import TaskEventOutbox

PENDING = "traceforge_collaboration_events"


def emit_state(db, state) -> None:
    # Some transitions advance the revision before assigning their final
    # phase/input pointers. Capture them at commit, after the entire operation.
    db.info.setdefault(PENDING, {})[state.task_id] = state


def _outbox_row(state):
    event_id = str(uuid4())
    fields = (
        "task_id",
        "state_version",
        "workspace_revision",
        "session_generation",
        "session_revision",
        "sync_phase",
        "snapshot_id",
        "input_snapshot_id",
        "progress_snapshot_id",
        "progress_seq",
        "final_progress_seq",
        "pending_submission_id",
        "input_submission_id",
    )
    payload = {field: getattr(state, field, None) for field in fields}
    return TaskEventOutbox(
        event_id=event_id,
        task_id=state.task_id,
        payload_json={
            "event_type": "workspace_collaboration_update",
            "event_id": event_id,
            **payload,
        },
    )


@event.listens_for(Session, "before_commit")
def _flush_events(db):
    for state in db.info.pop(PENDING, {}).values():
        db.add(_outbox_row(state))


@event.listens_for(Session, "after_rollback")
def _discard_events(db):
    db.info.pop(PENDING, None)
