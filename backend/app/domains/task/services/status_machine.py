"""The sole task-status writer. Callers own the surrounding business transaction.

Row locking + a sequence CAS serialize transitions across processes. Audit,
idempotency receipt and delivery outbox commit or roll back with the task.
Provider callbacks have no permission to start/restart a task.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from uuid import uuid4

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.domains.task.models.task import SddTask
from app.domains.task.models.task import TaskStatus as S
from app.domains.task.models.task_event_outbox import TaskEventOutbox
from app.domains.task.models.task_status_event import TaskStatusEvent


class Trigger(str, Enum):
    CREATED = "CREATED"
    RESOURCES_READY = "RESOURCES_READY"
    START = "START"
    INPUT_SUBMITTED = "INPUT_SUBMITTED"
    RESET = "RESET"
    RESUME = "RESUME"
    BIND_EXECUTION = "BIND_EXECUTION"
    QUESTION_OPENED = "QUESTION_OPENED"
    ANSWER_RECEIVED = "ANSWER_RECEIVED"
    ROUND_FINISHED = "ROUND_FINISHED"
    EXECUTION_INTERRUPTED = "EXECUTION_INTERRUPTED"
    INTERRUPT = "INTERRUPT"
    REVERT = "REVERT"
    COMPLETE = "COMPLETE"
    FAIL = "FAIL"


OPEN = (S.INITIALIZED, S.RUNNING, S.ROUND_COMPLETED, S.AWAITING_INPUT, S.INTERRUPTED)
TRANSITIONS: dict[Trigger, dict[S | None, S]] = {
    Trigger.CREATED: {None: S.PROVISIONING},
    Trigger.RESOURCES_READY: {S.PROVISIONING: S.INITIALIZED},
    Trigger.START: {S.INITIALIZED: S.RUNNING},
    Trigger.INPUT_SUBMITTED: {S.ROUND_COMPLETED: S.RUNNING, S.AWAITING_INPUT: S.RUNNING},
    Trigger.RESUME: {S.INTERRUPTED: S.RUNNING},
    Trigger.RESET: dict.fromkeys(OPEN, S.RUNNING),
    Trigger.BIND_EXECUTION: {S.RUNNING: S.RUNNING},
    Trigger.QUESTION_OPENED: {S.RUNNING: S.AWAITING_INPUT, S.AWAITING_INPUT: S.AWAITING_INPUT},
    Trigger.ANSWER_RECEIVED: {S.AWAITING_INPUT: S.RUNNING},
    Trigger.ROUND_FINISHED: {S.RUNNING: S.ROUND_COMPLETED, S.AWAITING_INPUT: S.AWAITING_INPUT},
    Trigger.EXECUTION_INTERRUPTED: {S.RUNNING: S.INTERRUPTED, S.AWAITING_INPUT: S.INTERRUPTED},
    Trigger.INTERRUPT: {S.RUNNING: S.INTERRUPTED, S.AWAITING_INPUT: S.INTERRUPTED},
    Trigger.REVERT: {state: S.ROUND_COMPLETED for state in OPEN if state != S.INITIALIZED},
    Trigger.COMPLETE: dict.fromkeys(OPEN, S.COMPLETED),
    Trigger.FAIL: dict.fromkeys(OPEN, S.FAILED),
}
EXECUTION_TRIGGERS = frozenset(
    {Trigger.QUESTION_OPENED, Trigger.ANSWER_RECEIVED, Trigger.ROUND_FINISHED, Trigger.EXECUTION_INTERRUPTED}
)


class StatusTransitionError(ValueError):
    status_code = 409
    code = "TASK_STATUS_TRANSITION_REJECTED"


def snapshot(task: SddTask) -> dict:
    return {
        "task_id": task.id,
        "workspace_id": task.workspace_id,
        "status": task.status.value,
        "status_seq": str(task.status_seq or 0),
        "session_generation": int(task.session_generation or 0),
        "session_revision": int(task.session_revision or 0),
    }


def receipt(db: Session, task_id: str, event_key: str) -> dict | None:
    row = db.query(TaskStatusEvent).filter_by(task_id=task_id, event_key=event_key).one_or_none()
    return dict(row.result_json.get("command_result", row.result_json)) if row else None


def remember_command_result(db: Session, task_id: str, event_key: str, result: dict) -> None:
    """Persist the business receipt alongside its transition, before commit."""
    row = db.query(TaskStatusEvent).filter_by(task_id=task_id, event_key=event_key).one()
    row.result_json = {**row.result_json, "command_result": result}


def _fingerprint(trigger, actor_id, job_id=None, generation=None, revision=None, reason=None, content=None):
    return hashlib.sha256(
        json.dumps(
            [trigger.value, actor_id, job_id, generation, revision, reason, content], ensure_ascii=False, sort_keys=True
        ).encode()
    ).hexdigest()


def dispatch(
    db: Session,
    task: SddTask,
    trigger: Trigger,
    *,
    event_key: str,
    actor_id: str | None = None,
    job_id: str | None = None,
    expected_seq: int | None = None,
    generation: int | None = None,
    revision: int | None = None,
    reason: str | None = None,
    content: dict | None = None,
) -> dict:
    """Apply a command or reject it. Duplicate keys return the original receipt.

    Execution events require run/generation/revision/sequence identity. Fenced,
    out-of-order and post-terminal callbacks are recorded as ignored receipts.
    They cannot consume a sequence, emit a transition, or resurrect a task.
    """
    trigger = Trigger(trigger)
    if not event_key or len(event_key) > 190:
        raise StatusTransitionError("A bounded, stable status event key is required")
    fingerprint = _fingerprint(trigger, actor_id, job_id, generation, revision, reason, content)
    # Flush the caller's pending changes before reloading under the row lock.
    db.flush()
    task = db.query(SddTask).filter_by(id=task.id).populate_existing().with_for_update().one()
    # Reload the transition under the task lock to observe the preceding writer.
    previous = db.query(TaskStatusEvent).filter_by(task_id=task.id, event_key=event_key).with_for_update().one_or_none()
    if previous:
        if previous.fingerprint != fingerprint:
            raise StatusTransitionError("Status event key was reused with different content")
        return {**previous.result_json, "duplicate": True}
    before = task.status
    outcome = _outcome(task, trigger, job_id, expected_seq, generation, revision)
    target = TRANSITIONS[trigger].get(before)
    if outcome is None and target is None:
        if trigger in EXECUTION_TRIGGERS:
            outcome = "IGNORED_LATE"
        else:
            raise StatusTransitionError(f"Illegal task status transition: {before.value} / {trigger.value}")
    if outcome is None:
        changed_identity = trigger in {Trigger.RESET, Trigger.REVERT} or (
            trigger == Trigger.BIND_EXECUTION and job_id != task.status_run_id
        )
        outcome = "APPLIED" if target != before or changed_identity else "IGNORED_NO_CHANGE"
    if outcome == "APPLIED":
        _write(db, task, target, trigger, job_id)
    result = {**snapshot(task), "outcome": outcome}
    _record(db, task, before.value, trigger, event_key, fingerprint, result, actor_id, job_id, reason)
    db.flush()
    return result


def _outcome(task, trigger, job_id, expected_seq, generation, revision):
    if expected_seq is not None and int(expected_seq) != int(task.status_seq):
        if trigger not in EXECUTION_TRIGGERS:
            raise StatusTransitionError("Task status sequence has changed")
        return "IGNORED_STALE"
    if trigger not in EXECUTION_TRIGGERS:
        return None
    if job_id is None or expected_seq is None or generation is None or revision is None:
        raise StatusTransitionError("Execution events require job, generation, revision and sequence")
    if (job_id, generation, revision) != (task.status_run_id, task.session_generation, task.session_revision):
        return "IGNORED_STALE"
    return None


def _write(db, task, target, trigger, job_id):
    sequence = int(task.status_seq or 0)
    run_id = task.status_run_id
    if trigger == Trigger.BIND_EXECUTION:
        if not job_id:
            raise StatusTransitionError("Binding execution requires a job identity")
        run_id = job_id
    elif trigger not in EXECUTION_TRIGGERS:
        run_id = None
    affected = (
        db.query(SddTask)
        .filter_by(id=task.id, status_seq=sequence)
        .update({"status": target, "status_seq": sequence + 1, "status_run_id": run_id}, synchronize_session=False)
    )
    if affected != 1:
        raise StatusTransitionError("Concurrent task status transition; retry with the current sequence")
    db.refresh(task)


def _record(db, task, before, trigger, event_key, fingerprint, result, actor_id, job_id, reason):
    applied = result["outcome"] == "APPLIED"
    db.add(
        TaskStatusEvent(
            task_id=task.id,
            event_key=event_key,
            fingerprint=fingerprint,
            trigger=trigger.value,
            from_status=before,
            to_status=task.status.value,
            status_seq=task.status_seq if applied else None,
            outcome=result["outcome"],
            actor_id=actor_id,
            job_id=job_id,
            session_generation=task.session_generation or 0,
            session_revision=task.session_revision or 0,
            reason=reason[:1000] if reason else None,
            result_json=result,
        )
    )
    if applied:
        db.add(
            TaskEventOutbox(
                event_id=str(uuid4()),
                task_id=task.id,
                payload_json={
                    **result,
                    "event_type": "task_status_changed",
                    "trigger": trigger.value,
                    "previous_status": before,
                    "actor_id": actor_id,
                    "job_id": job_id,
                },
            )
        )


def initialize(db: Session, task: SddTask) -> None:
    """The creation path is also audited and delivered transactionally."""
    if not inspect(task).transient:
        raise StatusTransitionError("Only a new task may enter the state machine")
    task.status = TRANSITIONS[Trigger.CREATED][None]
    task.status_seq = 1
    task.status_run_id = None
    db.add(task)
    db.flush()
    result = {**snapshot(task), "outcome": "APPLIED"}
    fingerprint = _fingerprint(Trigger.CREATED, task.creator_id)
    _record(db, task, None, Trigger.CREATED, "created", fingerprint, result, task.creator_id, None, None)
    db.flush()


def execution_event(
    db: Session,
    task: SddTask,
    trigger: Trigger,
    *,
    job_id: str,
    event_key: str,
    generation: int,
    revision: int,
    expected_seq: int | None = None,
    reason: str | None = None,
) -> dict:
    """Finalizers can load the cursor under the task lock; engines retain their cursor."""
    if trigger not in EXECUTION_TRIGGERS:
        raise StatusTransitionError("A provider cannot dispatch user commands")
    return dispatch(
        db,
        task,
        trigger,
        event_key=event_key,
        job_id=job_id,
        generation=generation,
        revision=revision,
        expected_seq=int(task.status_seq or 0) if expected_seq is None else expected_seq,
        reason=reason,
    )
