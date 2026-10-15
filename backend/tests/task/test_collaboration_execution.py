"""Exercise the real submission/job barriers with durable collaboration rows."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services.jobs import store as job_store
from app.domains.auth.models.user import User, Workspace, WorkspaceMember, WorkspaceRole
from app.domains.task.models.chat_submission import TaskChatSubmission
from app.domains.task.models.session_turn import TaskSessionTurn
from app.domains.task.models.task import SddTask, TaskStatus, TaskType
from app.domains.task.models.task_repository import SddTaskRepository, TaskRepositoryState
from app.domains.task.services import chat_submission_service as submissions
from app.domains.task.services import task_session_service as turns
from app.domains.workspace_collaboration import content, hooks, service
from app.domains.workspace_collaboration.models import CollaborationSnapshot, CollaborationState


@pytest.fixture
def collaboration_db(db):
    db.add(User(id="u", email="collaboration-execution@test.local", hashed_password="x", display_name="User"))
    db.add(Workspace(id="w", name="Workspace", owner_id="u"))
    db.add(WorkspaceMember(workspace_id="w", user_id="u", role=WorkspaceRole.OWNER))
    task = SddTask(
        id="t",
        workspace_id="w",
        creator_id="u",
        name="Task",
        project_path="/unused",
        status=TaskStatus.CODING,
        agent_backend="mock",
        session_generation=1,
        session_revision=0,
    )
    db.add(task)
    db.add(
        SddTaskRepository(
            id="api",
            task_id="t",
            repo_url="https://example.test/api.git",
            repo_name="api",
            repo_slug="api",
            branch_name="release/2.x",
            base_commit_sha="a" * 40,
            rel_path="api",
            state=TaskRepositoryState.READY,
        )
    )
    db.commit()
    repositories = service.repository_metadata(db, task)
    manifest = {
        "snapshot_id": "input",
        "task_id": "t",
        "workspace_revision": 2,
        "repositories": [{**repo, "files": []} for repo in repositories],
    }
    db.add(
        CollaborationSnapshot(
            id="input",
            task_id="t",
            manifest_json=manifest,
            content_digest=content.digest(manifest),
            source="HUMAN_HANDOFF",
        )
    )
    state = CollaborationState(
        task_id="t",
        enabled=True,
        sync_phase="READY",
        state_version=1,
        workspace_revision=2,
        session_generation=1,
        session_revision=0,
        repository_set_digest=content.digest(repositories),
        binding_id="binding",
        driver_user_id="u",
        client_id="desktop",
        instance_id="instance",
        lease_epoch=1,
        lease_expires_at=datetime.utcnow() + timedelta(minutes=5),
        snapshot_id="input",
        input_snapshot_id="input",
        reconciled_revision=2,
    )
    db.add(state)
    db.commit()
    return db


def accept(db, message_id="message"):
    result = submissions._accept_sync(
        db,
        "t",
        "u",
        message_id,
        "Update login",
        {
            "collaboration": {
                "client_id": "desktop",
                "instance_id": "instance",
                "binding_id": "binding",
                "lease_epoch": 1,
            }
        },
    )
    db.commit()
    return db.get(TaskChatSubmission, result["id"])


def fixed_input(db, receipt):
    state = db.get(CollaborationState, "t")
    state.input_submission_id = receipt.id
    db.commit()


def test_message_is_durable_while_waiting_for_actual_input(collaboration_db):
    db = collaboration_db
    receipt = accept(db)
    assert submissions._load_preparation(db, receipt.id) is None
    assert receipt.status == "PREPARING"
    assert db.query(SddAiJob).count() == 0
    assert db.get(CollaborationState, "t").pending_submission_id == receipt.id
    fixed_input(db, receipt)
    prepared = submissions._load_preparation(db, receipt.id)
    assert prepared["context_json"]["submission_id"] == receipt.id
    assert db.query(SddAiJob).count() == 0


@pytest.mark.parametrize("phase", ["PREPARING", "RECOVERY_REQUIRED"])
def test_stop_does_not_cancel_preparing_message_without_an_agent_job(collaboration_db, phase):
    from app.domains.task.services import task_session_control_service as controls

    db = collaboration_db
    receipt = accept(db)
    state = db.get(CollaborationState, "t")
    state.sync_phase = phase
    if phase == "RECOVERY_REQUIRED":
        state.recovery_kind = "SERVER_INPUT"
        state.recovery_operation_id = "lost-handoff"
    db.commit()
    with pytest.raises(controls.TaskSessionControlError, match="No running"):
        controls._cancel_active_jobs_sync(db, task_id="t", workspace_id="w", message="cancel preparation")
    assert receipt.status == "PREPARING"
    assert receipt.active_task_id == "t"
    assert state.pending_submission_id == receipt.id
    assert state.sync_phase == phase
    assert db.query(SddAiJob).count() == 0


def test_another_desktop_cannot_submit_using_same_user(collaboration_db):
    db = collaboration_db
    with pytest.raises(submissions.SubmissionError, match="bound desktop"):
        submissions._accept_sync(db, "t", "u", "web", "Update login", {"collaboration": {"client_id": "other"}})
    db.rollback()
    assert db.query(TaskChatSubmission).count() == 0
    assert db.get(CollaborationState, "t").sync_phase == "READY"


@pytest.mark.parametrize("phase", ["READY", "DELIVERY_PENDING", "CONFLICT_PENDING", "RECOVERY_REQUIRED"])
def test_cloud_message_uses_fixed_server_code_without_a_desktop_lease(collaboration_db, phase):
    from app.domains.workspace_collaboration.models import CollaborationHandoff
    from app.domains.workspace_collaboration.schemas import EnableRequest

    db = collaboration_db
    state = db.get(CollaborationState, "t")
    state.sync_phase = phase
    state.recovery_kind = "LOCAL_DELIVERY" if phase == "RECOVERY_REQUIRED" else None
    state.lease_expires_at = datetime.utcnow() - timedelta(minutes=5)
    result = submissions._accept_sync(db, "t", "u", "cloud-message", "Read cloud code", {})
    db.commit()
    assert submissions._load_preparation(db, result["id"]) is not None
    assert state.input_snapshot_id == "input"
    assert state.input_submission_id == result["id"]
    assert service.get_state(db, db.get(SddTask, "t"))["input_mode"] == "CLOUD"
    # Reconnection must not cancel an already prepared cloud-only message.
    service.claim_driver(
        db,
        db.get(SddTask, "t"),
        "u",
        EnableRequest(operation_id="connect", client_id="desktop", instance_id="instance"),
    )
    assert db.get(TaskChatSubmission, result["id"]).status == "PREPARING"
    state.lease_expires_at = datetime.utcnow() - timedelta(minutes=5)
    accepted = service.authorize_execution(db, db.get(SddTask, "t"), result["id"], "cloud-job")
    assert accepted["snapshot_id"] == "input"
    assert state.sync_phase == "RUNNING"
    assert service.validate_execution(db, db.get(SddTask, "t"), "cloud-job")["snapshot_id"] == "input"
    assert db.query(CollaborationHandoff).count() == 0


@pytest.mark.parametrize(
    "phase,kind", [("RUNNING", None), ("RECOVERY_REQUIRED", "SERVER_INPUT"), ("RECOVERY_REQUIRED", "SERVER_OUTPUT")]
)
def test_cloud_message_still_respects_server_writer_and_recovery(collaboration_db, phase, kind):
    db = collaboration_db
    state = db.get(CollaborationState, "t")
    state.sync_phase = phase
    state.recovery_kind = kind
    with pytest.raises(submissions.SubmissionError, match="cloud execution or workspace recovery"):
        submissions._accept_sync(db, "t", "u", "cloud-blocked", "Read cloud code", {})


def test_job_creation_cannot_bypass_input_barrier(collaboration_db):
    db = collaboration_db
    with pytest.raises(service.CollaborationError, match="complete local input"):
        job_store.create_task_chat_job(
            db, workspace_id="w", task_id="t", creator_id="u", prompt_text="bypass", commit=False
        )
    db.rollback()
    assert db.query(SddAiJob).count() == 0


def test_browser_request_waits_for_bound_desktop_input(collaboration_db):
    db = collaboration_db
    result = submissions._accept_sync(
        db,
        "t",
        "u",
        "browser-request",
        "Update login",
        {"collaboration": {"request_driver_input": True, "binding_id": "binding", "lease_epoch": 1}},
    )
    db.commit()
    assert submissions._load_preparation(db, result["id"]) is None
    assert db.get(CollaborationState, "t").sync_phase == "PREPARING"
    assert db.query(SddAiJob).count() == 0


def test_browser_request_cannot_reuse_old_binding(collaboration_db):
    db = collaboration_db
    with pytest.raises(submissions.SubmissionError):
        submissions._accept_sync(
            db,
            "t",
            "u",
            "browser-stale",
            "Update login",
            {"collaboration": {"request_driver_input": True, "binding_id": "old-binding", "lease_epoch": 1}},
        )
    db.rollback()
    assert db.get(CollaborationState, "t").sync_phase == "READY"
    assert db.query(TaskChatSubmission).count() == 0


@pytest.mark.parametrize("phase,confirmed", [("READY", None), ("READY", "old"), ("CONFLICT_PENDING", "input")])
def test_closeout_cannot_silently_use_unconfirmed_code(collaboration_db, phase, confirmed):
    from app.domains.task.services.task_closeout_service import TaskCloseoutError
    from app.domains.workspace_collaboration.control import closeout_snapshot

    db = collaboration_db
    db.get(CollaborationState, "t").sync_phase = phase
    with pytest.raises(TaskCloseoutError):
        closeout_snapshot(db, db.get(SddTask, "t"), confirmed)


def test_closeout_evidence_binds_explicit_server_code_scope(collaboration_db):
    from app.domains.task.schemas.task_closeout import CompleteTaskCloseoutRequest
    from app.domains.task.services.task_closeout_service import _bind_closeout_snapshot, _complete_evidence_payloads

    db = collaboration_db
    payload = CompleteTaskCloseoutRequest(
        completion_summary="Done",
        landing_method="HUMAN_ADJUSTED",
        commit_id="abc",
        confirmed_server_snapshot_id="input",
    )
    evidence = _complete_evidence_payloads(payload, TaskType.DEVELOPMENT)
    snapshot_id = _bind_closeout_snapshot(db, db.get(SddTask, "t"), payload, evidence)
    assert snapshot_id == "input"
    assert evidence[0].source_metadata["collaboration"]["snapshot_id"] == "input"
    assert evidence[0].source_metadata["collaboration"]["unhanded_local_changes_excluded"] is True


@pytest.mark.parametrize("initial_generation", [0, 1])
def test_fixed_input_is_bound_to_one_job_after_checkpoint_preparation(
    collaboration_db, monkeypatch, initial_generation, tmp_path
):
    from app.domains.task.services import context_token_service

    db = collaboration_db
    db.get(SddTask, "t").session_generation = initial_generation
    db.get(CollaborationState, "t").session_generation = initial_generation
    db.commit()
    monkeypatch.setattr(context_token_service, "seed_snapshot_for_job", lambda *a, **k: None)
    receipt = accept(db)
    fixed_input(db, receipt)
    prepared = turns._prepare_chat_turn_sync(
        db,
        task_id="t",
        content="Update login",
        prompt="Update login",
        session_id=None,
        fresh_session=False,
        submission_id=receipt.id,
    )
    db.commit()
    prepared["actor_user_id"] = "u"
    created = turns._persist_chat_turn_sync(
        db,
        prepared=prepared,
        content="Update login",
        prompt="Update login",
        context_json={"submission_id": receipt.id},
        client_message_id="message",
    )
    state = db.get(CollaborationState, "t")
    job = db.get(SddAiJob, created.job_id)
    assert state.sync_phase == "RUNNING"
    assert state.run_id == job.id
    assert state.session_revision == job.session_revision == 1
    assert state.session_generation == job.session_generation == 1
    assert job.context_json["collaboration"]["snapshot_id"] == "input"
    assert job.context_json["collaboration"]["submission_id"] == receipt.id
    assert not service.input_ready(db, "t", receipt.id)
    turn = db.query(TaskSessionTurn).filter_by(ai_job_id=job.id).one()
    monkeypatch.setattr(content, "ObjectStore", lambda _: SimpleNamespace(root=tmp_path))
    for source in ("PROGRESS", "AGENT_OUTPUT"):
        manifest = service._snapshot(db, db.get(SddTask, "t"), state, source, [])
        assert manifest["session_turn_id"] == turn.id
        assert manifest["turn_index"] == turn.turn_index
        assert manifest["turn_title"] == "Update login"
        assert manifest["turn_created_at"] == turn.created_at.isoformat() + "Z"
        # Inventories are compressed separately; the persisted header does not
        # duplicate repositories. Compare through the public snapshot reader.
        assert service.get_snapshot(db, "t", manifest["snapshot_id"]) == manifest
    state.run_id = "missing-historical-job"
    assert "turn_index" not in service._snapshot(db, db.get(SddTask, "t"), state, "AGENT_OUTPUT", [])


def test_preparation_failure_keeps_already_accepted_input(collaboration_db):
    db = collaboration_db
    receipt = accept(db)
    fixed_input(db, receipt)
    submissions._fail_sync(db, receipt.id, "checkpoint failed")
    db.commit()
    state = db.get(CollaborationState, "t")
    assert state.sync_phase == "READY"
    assert state.snapshot_id == "input"
    assert state.workspace_revision == 2
    assert receipt.status == "FAILED"
    assert receipt.active_task_id is None


@pytest.mark.parametrize("status", [AiJobStatus.SUCCESS, AiJobStatus.CANCELLED])
def test_stale_job_delivery_cannot_change_current_round(collaboration_db, status):
    db = collaboration_db
    state = db.get(CollaborationState, "t")
    state.sync_phase, state.run_id = "RUNNING", "new"
    db.add(
        SddAiJob(
            id="old",
            task_id="t",
            workspace_id="w",
            creator_id="u",
            channel=AiJobChannel.TASK_CHAT,
            queue_key="TASK_CHAT:t",
            status=status,
            prompt_text="old",
        )
    )
    db.commit()
    hooks._settle_job(db, "old")
    assert state.sync_phase == "RUNNING"
    assert state.run_id == "new"


def test_unconfirmed_stop_never_publishes_final_code(collaboration_db):
    db = collaboration_db
    state = db.get(CollaborationState, "t")
    state.sync_phase, state.run_id = "RUNNING", "orphan"
    db.add(
        SddAiJob(
            id="orphan",
            task_id="t",
            workspace_id="w",
            creator_id="u",
            channel=AiJobChannel.TASK_CHAT,
            queue_key="TASK_CHAT:t",
            status=AiJobStatus.ORPHANED,
            prompt_text="uncertain",
        )
    )
    db.commit()
    hooks._settle_job(db, "orphan")
    assert state.sync_phase == "STOPPING"
    assert state.snapshot_id == "input"
    assert db.query(CollaborationSnapshot).count() == 1


@pytest.mark.asyncio
async def test_duplicate_terminal_notifications_share_one_capture(monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def capture(_body):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()

    monkeypatch.setattr(hooks, "run_db_txn", capture)
    first = asyncio.create_task(hooks.settle_job("concurrent-final"))
    await started.wait()
    await hooks.settle_job("concurrent-final")
    assert calls == 1
    release.set()
    await first
    assert "concurrent-final" not in hooks._settling_jobs


@pytest.mark.asyncio
async def test_competing_process_final_capture_is_deferred_without_recovery(monkeypatch):
    calls = 0

    async def busy(_body):
        nonlocal calls
        calls += 1
        raise service.CollaborationError("TASK_BUSY", "Another process is capturing")

    monkeypatch.setattr(hooks, "run_db_txn", busy)
    await hooks.settle_job("process-final")
    assert calls == 1
    assert "process-final" not in hooks._settling_jobs


@pytest.mark.parametrize("phase", ["DELIVERY_PENDING", "CONFLICT_PENDING", "READY"])
def test_late_failed_capture_cannot_overwrite_completed_delivery(collaboration_db, phase):
    state = collaboration_db.get(CollaborationState, "t")
    state.sync_phase, state.run_id = phase, "finished"
    service.mark_recovery(collaboration_db, "t", "late failure", expected_run_id="finished")
    assert state.sync_phase == phase
    assert state.recovery_kind is None


def test_state_events_commit_final_phase_and_do_not_escape_rollback(collaboration_db):
    from app.domains.task.models.task_event_outbox import TaskEventOutbox

    db = collaboration_db
    state = db.get(CollaborationState, "t")
    service._bump(state)
    state.sync_phase = "CONFLICT_PENDING"
    service._bump(state)
    state.progress_seq = 3
    db.commit()
    events = db.query(TaskEventOutbox).all()
    assert len(events) == 1
    assert events[0].payload_json["event_type"] == "workspace_collaboration_update"
    assert events[0].payload_json["sync_phase"] == "CONFLICT_PENDING"
    assert events[0].payload_json["state_version"] == state.state_version
    assert events[0].payload_json["progress_seq"] == 3
    service._bump(state)
    state.sync_phase = "READY"
    db.rollback()
    db.commit()
    assert db.query(TaskEventOutbox).count() == 1


@pytest.mark.parametrize("initial_generation", [0, 1])
def test_start_is_preparation_not_an_immediate_job(collaboration_db, initial_generation):
    from app.domains.task.services.task_session_control_service import start_task_session_sync

    db = collaboration_db
    db.get(SddTask, "t").session_generation = initial_generation
    db.get(CollaborationState, "t").session_generation = initial_generation
    db.commit()
    result = start_task_session_sync(
        db, ws_id="w", task_id="t", creator_id="u", prompt="Initial context", user_display="Start task"
    )
    db.commit()
    assert result["job_id"] is None
    assert result["submission"]["status"] == "PREPARING"
    assert db.get(SddTask, "t").session_generation == db.get(CollaborationState, "t").session_generation == 1
    assert db.query(SddAiJob).count() == 0
    receipt = db.get(TaskChatSubmission, result["submission"]["id"])
    fixed_input(db, receipt)
    prepared = submissions._load_preparation(db, receipt.id)
    assert prepared["prompt_text"] == "Initial context"
    assert prepared["fresh_session"] is True


def test_resume_receipt_is_idempotent_and_preserves_pre_input_metadata(collaboration_db):
    from app.domains.workspace_collaboration.control import existing_resume, resume_submission

    db = collaboration_db
    task = db.get(SddTask, "t")
    task.status = TaskStatus.INTERRUPTED
    db.add(
        SddAiJob(
            id="interrupted",
            task_id="t",
            workspace_id="w",
            creator_id="u",
            channel=AiJobChannel.TASK_CHAT,
            queue_key="TASK_CHAT:t",
            status=AiJobStatus.INTERRUPTED,
            prompt_text="old",
            session_id="interrupted-provider-session",
        )
    )
    db.commit()
    receipt = resume_submission(
        db,
        "t",
        "u",
        {"prompt_text": "continue", "old_job_id": "interrupted", "session_id": "interrupted-provider-session"},
        "resume-key",
        {"pre_input_id": "pre-input"},
    )
    db.commit()
    assert existing_resume(db, "t", "u", "resume-key", "continue", False)["submission"]["id"] == receipt["id"]
    row = db.get(TaskChatSubmission, receipt["id"])
    assert row.metadata_json["pre_input_id"] == "pre-input"
    assert task.status == TaskStatus.CODING
    assert task.session_id == "interrupted-provider-session"
    assert db.query(SddAiJob).count() == 1
