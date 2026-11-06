"""The transition matrix, event ordering and atomic audit."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.domains.task.models.task import SddTask
from app.domains.task.models.task import TaskStatus as S
from app.domains.task.models.task_event_outbox import TaskEventOutbox
from app.domains.task.models.task_status_event import TaskStatusEvent
from app.domains.task.services import status_machine as sm
from app.domains.task.services import task_event_publisher as publisher
from tests.workspace_asset.test_workspace_asset_boundary import _seed_workspace

# Independent expected contract: changing the implementation table alone cannot
# make an illegal edge pass. Every state x trigger pair is exercised below.
LEGAL = {
    sm.Trigger.RESOURCES_READY: ({S.PROVISIONING}, S.INITIALIZED),
    sm.Trigger.START: ({S.INITIALIZED}, S.RUNNING),
    sm.Trigger.INPUT_SUBMITTED: ({S.ROUND_COMPLETED, S.AWAITING_INPUT}, S.RUNNING),
    sm.Trigger.RESUME: ({S.INTERRUPTED}, S.RUNNING),
    sm.Trigger.RESET: ({S.INITIALIZED, S.RUNNING, S.ROUND_COMPLETED, S.AWAITING_INPUT, S.INTERRUPTED}, S.RUNNING),
    sm.Trigger.BIND_EXECUTION: ({S.RUNNING}, S.RUNNING),
    sm.Trigger.QUESTION_OPENED: ({S.RUNNING, S.AWAITING_INPUT}, S.AWAITING_INPUT),
    sm.Trigger.ANSWER_RECEIVED: ({S.AWAITING_INPUT}, S.RUNNING),
    sm.Trigger.ROUND_FINISHED: ({S.RUNNING, S.AWAITING_INPUT}, S.ROUND_COMPLETED),
    sm.Trigger.EXECUTION_INTERRUPTED: ({S.RUNNING, S.AWAITING_INPUT}, S.INTERRUPTED),
    sm.Trigger.INTERRUPT: ({S.RUNNING, S.AWAITING_INPUT}, S.INTERRUPTED),
    sm.Trigger.REVERT: ({S.RUNNING, S.ROUND_COMPLETED, S.AWAITING_INPUT, S.INTERRUPTED}, S.ROUND_COMPLETED),
    sm.Trigger.COMPLETE: ({S.INITIALIZED, S.RUNNING, S.ROUND_COMPLETED, S.AWAITING_INPUT, S.INTERRUPTED}, S.COMPLETED),
    sm.Trigger.FAIL: ({S.INITIALIZED, S.RUNNING, S.ROUND_COMPLETED, S.AWAITING_INPUT, S.INTERRUPTED}, S.FAILED),
}


def seed(db, state=S.RUNNING):
    _, _, task = _seed_workspace(db)
    task.status = state  # Test-fixture setup is deliberately outside the application writer gate.
    task.status_seq = 10
    task.status_run_id = "job"
    task.session_generation = 2
    task.session_revision = 4
    db.commit()
    return task


def event(db, task, trigger, key="event", **kwargs):
    if trigger in sm.EXECUTION_TRIGGERS:
        kwargs = {"job_id": "job", "generation": 2, "revision": 4, "expected_seq": int(task.status_seq), **kwargs}
    if trigger == sm.Trigger.BIND_EXECUTION:
        kwargs.setdefault("job_id", "next-job")
    return sm.dispatch(db, task, trigger, event_key=key, **kwargs)


@pytest.mark.parametrize("state", list(S))
@pytest.mark.parametrize("trigger", list(sm.Trigger))
def test_complete_state_transition_matrix(db, state, trigger):
    task = seed(db, state)
    allowed, target = LEGAL.get(trigger, (set(), None))
    if state not in allowed:
        if trigger in sm.EXECUTION_TRIGGERS:
            result = event(db, task, trigger)
            assert result["outcome"] == "IGNORED_LATE"
        else:
            with pytest.raises(sm.StatusTransitionError):
                event(db, task, trigger)
        assert task.status == state
        assert task.status_seq == 10
        assert db.query(TaskEventOutbox).count() == 0
        assert db.query(TaskStatusEvent).filter_by(outcome="APPLIED").count() == 0
        return
    result = event(db, task, trigger, actor_id=None if trigger in sm.EXECUTION_TRIGGERS else "user-1")
    expected = S.AWAITING_INPUT if trigger == sm.Trigger.ROUND_FINISHED and state == S.AWAITING_INPUT else target
    assert task.status == expected
    changed = state != expected or trigger in {sm.Trigger.RESET, sm.Trigger.REVERT, sm.Trigger.BIND_EXECUTION}
    assert task.status_seq == 10 + changed
    assert result["status_seq"] == str(task.status_seq)
    assert db.query(TaskEventOutbox).count() == int(changed)
    audit = db.query(TaskStatusEvent).one()
    assert (audit.from_status, audit.to_status) == (state.value, expected.value)
    assert audit.status_seq == (11 if changed else None)
    assert audit.trigger == trigger.value


def test_creation_is_audited_and_broadcast_in_the_same_transaction(db):
    _, ws, _ = _seed_workspace(db)
    task = SddTask(id=str(uuid4()), workspace_id=ws.id, creator_id="user-1", name="new")
    sm.initialize(db, task)
    assert (task.status, task.status_seq) == (S.PROVISIONING, 1)
    assert db.query(TaskStatusEvent).filter_by(task_id=task.id).one().from_status is None
    assert db.query(TaskEventOutbox).filter_by(task_id=task.id).one().payload_json["status_seq"] == "1"


def test_creation_entry_cannot_reset_a_persisted_terminal_task(db):
    task = seed(db, S.COMPLETED)
    with pytest.raises(sm.StatusTransitionError, match="new task"):
        sm.initialize(db, task)
    assert (task.status, task.status_seq) == (S.COMPLETED, 10)


def test_duplicate_created_event_returns_original_receipt_after_readiness(db):
    _, ws, _ = _seed_workspace(db)
    task = SddTask(id=str(uuid4()), workspace_id=ws.id, creator_id="user-1", name="new")
    sm.initialize(db, task)
    sm.dispatch(db, task, sm.Trigger.RESOURCES_READY, event_key="ready")
    result = sm.dispatch(db, task, sm.Trigger.CREATED, event_key="created", actor_id=task.creator_id)
    assert (result["status"], result["status_seq"], result["duplicate"]) == ("PROVISIONING", "1", True)
    assert (task.status, task.status_seq) == (S.INITIALIZED, 2)
    assert db.query(TaskStatusEvent).filter_by(task_id=task.id).count() == 2


def test_reused_command_key_with_changed_payload_is_rejected(db):
    task = seed(db)
    sm.dispatch(db, task, sm.Trigger.COMPLETE, event_key="close", content={"evidence": ["a"]})
    with pytest.raises(sm.StatusTransitionError, match="different content"):
        sm.dispatch(db, task, sm.Trigger.COMPLETE, event_key="close", content={"evidence": ["b"]})


def test_duplicate_event_returns_original_receipt_without_new_audit_or_delivery(db):
    task = seed(db)
    first = event(db, task, sm.Trigger.QUESTION_OPENED)
    db.commit()
    second = event(db, task, sm.Trigger.QUESTION_OPENED)
    assert second == {**first, "duplicate": True}
    assert task.status_seq == 11
    assert db.query(TaskStatusEvent).count() == db.query(TaskEventOutbox).count() == 1
    with pytest.raises(sm.StatusTransitionError, match="different content"):
        event(db, task, sm.Trigger.ROUND_FINISHED)


@pytest.mark.parametrize(
    "identity",
    [
        {"job_id": "old-job"},
        {"generation": 1},
        {"revision": 3},
        {"expected_seq": 9},
    ],
)
def test_stale_callbacks_are_durable_idempotent_noops(db, identity):
    task = seed(db)
    first = event(db, task, sm.Trigger.ROUND_FINISHED, **identity)
    assert first["outcome"] == "IGNORED_STALE"
    assert event(db, task, sm.Trigger.ROUND_FINISHED, **identity)["duplicate"]
    assert (task.status, task.status_seq) == (S.RUNNING, 10)
    assert db.query(TaskStatusEvent).one().status_seq is None
    assert db.query(TaskEventOutbox).count() == 0


def test_out_of_order_answer_and_old_round_cannot_mutate_a_newer_state(db):
    task = seed(db)
    result = event(db, task, sm.Trigger.ANSWER_RECEIVED, "answer-before-question")
    assert result["outcome"] == "IGNORED_LATE"
    event(db, task, sm.Trigger.QUESTION_OPENED, "question")
    assert event(db, task, sm.Trigger.ANSWER_RECEIVED, "answer-before-question")["duplicate"]
    assert task.status == S.AWAITING_INPUT
    event(db, task, sm.Trigger.ANSWER_RECEIVED, "valid-answer")
    event(db, task, sm.Trigger.ROUND_FINISHED, "finish")
    event(db, task, sm.Trigger.INPUT_SUBMITTED, "next-input")
    event(db, task, sm.Trigger.BIND_EXECUTION, "next-bind")
    assert event(db, task, sm.Trigger.ROUND_FINISHED, "late-finish", job_id="job")["outcome"] == "IGNORED_STALE"
    assert task.status == S.RUNNING


def test_rollback_rolls_back_state_audit_and_outbox_together(db):
    task = seed(db)
    event(db, task, sm.Trigger.COMPLETE)
    db.rollback()
    db.refresh(task)
    assert (task.status, task.status_seq) == (S.RUNNING, 10)
    assert db.query(TaskStatusEvent).count() == db.query(TaskEventOutbox).count() == 0


def test_revert_of_a_completed_round_versions_the_new_revision_even_when_status_name_is_unchanged(db):
    task = seed(db, S.ROUND_COMPLETED)
    task.session_revision += 1
    first = event(db, task, sm.Trigger.REVERT, "undo")
    assert (first["outcome"], first["status_seq"], first["session_revision"]) == ("APPLIED", "11", 5)
    audit = db.query(TaskStatusEvent).one()
    assert audit.from_status == audit.to_status == "ROUND_COMPLETED"
    assert db.query(TaskEventOutbox).one().payload_json["session_revision"] == 5
    assert event(db, task, sm.Trigger.REVERT, "undo")["duplicate"]
    assert task.status_seq == 11


def test_stale_orm_identity_map_cannot_override_a_concurrent_terminal_transition(db):
    task = seed(db)
    with Session(db.get_bind()) as closer:
        other = closer.get(SddTask, task.id)
        event(closer, other, sm.Trigger.COMPLETE, "complete")
        closer.commit()
    assert task.status == S.RUNNING  # Deliberately stale in this Session.
    result = event(db, task, sm.Trigger.ROUND_FINISHED, "late-finish")
    assert result["outcome"].startswith("IGNORED")
    assert (task.status, task.status_seq) == (S.COMPLETED, 11)


def test_optimistic_command_sequence_rejects_a_concurrent_winner(db):
    task = seed(db)
    event(db, task, sm.Trigger.INTERRUPT, "interrupt", expected_seq=10)
    with pytest.raises(sm.StatusTransitionError, match="sequence"):
        event(db, task, sm.Trigger.RESUME, "resume", expected_seq=10)


def test_outbox_leases_only_each_tasks_oldest_unpublished_event(db):
    task = seed(db)
    event(db, task, sm.Trigger.QUESTION_OPENED, "question")
    event(db, task, sm.Trigger.ANSWER_RECEIVED, "answer")
    db.commit()
    first = publisher._pending_sync(db, datetime.utcnow() + timedelta(seconds=1))
    db.commit()
    assert len(first) == 1
    assert first[0][3]["status_seq"] == "11"
    assert publisher._pending_sync(db, datetime.utcnow() + timedelta(seconds=1)) == []
    publisher._finalize_sync(db, first[0][1], error_code="offline", attempts=0)
    db.commit()
    assert publisher._pending_sync(db, datetime.utcnow()) == []
    publisher._finalize_sync(db, first[0][1], error_code=None, attempts=1)
    db.commit()
    assert publisher._pending_sync(db, datetime.utcnow() + timedelta(seconds=1))[0][3]["status_seq"] == "12"


def test_receipt_survives_session_restart_and_does_not_touch_a_new_run(db):
    task = seed(db)
    first = event(db, task, sm.Trigger.INTERRUPT, "stop")
    db.commit()
    event(db, task, sm.Trigger.RESUME, "resume")
    event(db, task, sm.Trigger.BIND_EXECUTION, "bind")
    db.commit()
    with Session(db.get_bind()) as restarted:
        current = restarted.get(SddTask, task.id)
        replay = event(restarted, current, sm.Trigger.INTERRUPT, "stop")
        assert replay == {**first, "duplicate": True}
        assert (current.status, current.status_run_id, current.status_seq) == (S.RUNNING, "next-job", 13)
        assert restarted.query(TaskStatusEvent).count() == restarted.query(TaskEventOutbox).count() == 3


def test_interrupt_command_atomically_persists_its_stop_intent(db):
    from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
    from app.domains.task.services.task_session_control_service import _accept_interrupt_command

    task = seed(db)
    job = SddAiJob(
        id="job",
        workspace_id=task.workspace_id,
        task_id=task.id,
        creator_id=task.creator_id,
        channel=AiJobChannel.TASK_CHAT,
        queue_key="TASK_CHAT:task-1",
        status=AiJobStatus.RUNNING,
    )
    db.add(job)
    db.commit()
    _accept_interrupt_command(db, task.id, task.creator_id, "stop", 10, "user stop")
    with Session(db.get_bind()) as restarted:
        assert restarted.get(SddTask, task.id).status == S.INTERRUPTED
        stopped = restarted.get(SddAiJob, job.id)
        assert stopped.cancel_requested_at is not None
        assert stopped.context_json["termination_mode"] == "INTERRUPT"
        assert restarted.query(TaskStatusEvent).one().trigger == "INTERRUPT"
        assert restarted.query(TaskEventOutbox).one().payload_json["status"] == "INTERRUPTED"


def test_pre_input_turn_uses_input_transition_and_binds_its_actual_job(db):
    from app.domains.task.services import task_session_service as turns

    task = seed(db, S.ROUND_COMPLETED)
    prepared = turns._prepare_chat_turn_sync(
        db,
        task_id=task.id,
        content="pre-input",
        prompt="pre-input",
        session_id=None,
        fresh_session=False,
    )
    prepared["actor_user_id"] = task.creator_id
    created = turns._persist_chat_turn_sync(
        db,
        prepared=prepared,
        content="pre-input",
        prompt="pre-input",
        context_json={"source": "pre_input"},
        client_message_id="pre-input-command",
    )
    db.refresh(task)
    assert (task.status, task.status_run_id, task.status_seq) == (S.RUNNING, created.job_id, 12)
    assert [row.trigger for row in db.query(TaskStatusEvent).order_by(TaskStatusEvent.status_seq)] == [
        "INPUT_SUBMITTED",
        "BIND_EXECUTION",
    ]


def test_stale_job_interruption_cannot_overwrite_new_session_metadata(db):
    from app.agents.contract import AttemptFinalizerEvidence
    from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
    from app.domains.ai.services.ai_job_convergence_service import (
        AttemptConvergenceRequest,
        _apply_task_interrupt_in_txn,
    )

    task = seed(db)
    task.session_id = "new-session"
    task.interrupt_reason = None
    job = SddAiJob(
        id="old-job",
        workspace_id=task.workspace_id,
        task_id=task.id,
        creator_id=task.creator_id,
        channel=AiJobChannel.TASK_CHAT,
        queue_key="TASK_CHAT:task-1",
        status=AiJobStatus.RUNNING,
        session_id="old-session",
        session_generation=2,
        session_revision=4,
    )
    db.add(job)
    db.commit()
    evidence = AttemptFinalizerEvidence(
        execution_kind="REMOTE_SESSION",
        process_started=True,
        termination_confirmed_dead=None,
        remote_stop_acknowledged=True,
        failure_code=None,
        error_message=None,
        remaining_pids=(),
        source="test",
    )
    request = AttemptConvergenceRequest(job.id, "token", "boot", AiJobStatus.INTERRUPTED, "old failure", evidence)
    _apply_task_interrupt_in_txn(db, job, task, request, datetime.utcnow())
    assert (task.status, task.session_id, task.interrupt_reason) == (S.RUNNING, "new-session", None)
    assert db.query(TaskStatusEvent).one().outcome == "IGNORED_STALE"
