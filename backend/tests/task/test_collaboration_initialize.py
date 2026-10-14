"""Initialize uses the current actor's input and commits acceptance with the reset."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import sessionmaker

from app import database
from app.dependencies import get_current_user, get_db
from app.domains.ai.models.ai_job import SddAiJob
from app.domains.auth.models.user import User, WorkspaceMember, WorkspaceRole
from app.domains.notification.models.task_awareness import TaskAwarenessEvent
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.chat_submission import TaskChatSubmission
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.routers.task import session_runs
from app.domains.task.services import chat_submission_service as submissions
from app.domains.task.services import task_session_control_service as lifecycle
from app.domains.task.services import task_session_service
from app.domains.workspace_collaboration import control
from app.domains.workspace_collaboration.models import CollaborationState
from tests.task.test_collaboration_execution import collaboration_db as collaboration_db


@pytest.fixture
def initialize_api(collaboration_db, monkeypatch):
    db = collaboration_db
    db.add(User(id="other", email="initialize-other@test.local", hashed_password="x", display_name="Other"))
    db.add(WorkspaceMember(workspace_id="w", user_id="u", role=WorkspaceRole.OWNER))
    task = db.get(SddTask, "t")
    task.session_id = "previous-session"
    task.status = TaskStatus.INTERRUPTED
    # A different task's failed preparation must not block this task or be reset.
    db.add(
        SddTask(
            id="unrelated",
            workspace_id="w",
            creator_id="u",
            name="Failed preparation",
            project_path="/other",
            status=TaskStatus.CODING,
            session_generation=8,
            session_revision=9,
        )
    )
    db.add(
        TaskChatSubmission(
            id="other-pending",
            task_id="unrelated",
            workspace_id="w",
            creator_id="u",
            client_message_id="other-message",
            content="Other input",
            payload_hash="x",
            status="PREPARING",
            active_task_id="unrelated",
            session_generation=8,
            session_revision=9,
        )
    )
    db.commit()
    sessions = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    monkeypatch.setattr(lifecycle, "get_engine", lambda _: None)
    scheduled = AsyncMock()
    monkeypatch.setattr(control, "schedule_control", scheduled)

    def get_session():
        with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(session_runs.router, prefix="/api")
    app.dependency_overrides[get_db] = get_session
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u")
    return app, db, scheduled


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["READY", "DELIVERY_PENDING", "CONFLICT_PENDING", "RECOVERY_REQUIRED"])
@pytest.mark.parametrize("driver,connected", [("u", True), ("u", False), ("other", True), ("other", False)])
async def test_initialize_only_waits_for_its_connected_driver(initialize_api, driver, connected, phase):
    app, db, scheduled = initialize_api
    state = db.get(CollaborationState, "t")
    state.driver_user_id = driver
    state.sync_phase = phase
    state.recovery_kind = "LOCAL_DELIVERY" if phase == "RECOVERY_REQUIRED" else None
    state.lease_expires_at = datetime.utcnow() + timedelta(minutes=5 if connected else -5)
    identity = (state.driver_user_id, state.client_id, state.instance_id, state.lease_epoch, state.lease_expires_at)
    db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/workspaces/w/tasks/t/initialize", json={"prompt": "Check cloud code", "reason": "Retry"}
        )
    if driver == "u" and connected and phase != "READY":
        assert response.status_code == 409, response.text
        db.expire_all()
        assert db.get(SddTask, "t").session_id == "previous-session"
        assert db.get(SddTask, "t").session_generation == 1
        assert state.sync_phase == phase
        scheduled.assert_not_awaited()
        return
    assert response.status_code == 200, response.text
    receipt_id = response.json()["submission"]["id"]
    db.expire_all()
    task, row = db.get(SddTask, "t"), db.get(TaskChatSubmission, receipt_id)
    local = driver == "u" and connected
    assert task.session_generation == state.session_generation == row.session_generation == 2
    assert task.session_id is None
    assert ("collaboration" in row.metadata_json) is local
    prepared = submissions._load_preparation(db, row.id)
    assert (prepared is None) is local
    if prepared:
        assert prepared["fresh_session"] is True
        assert prepared["prompt_text"] == "Check cloud code"
        assert prepared["context_json"]["initialize_reason"] == "Retry"
        assert state.input_snapshot_id == "input"
    assert identity == (
        state.driver_user_id,
        state.client_id,
        state.instance_id,
        state.lease_epoch,
        state.lease_expires_at,
    )
    assert db.query(SddAiJob).count() == 0
    assert db.query(ChatMessage).filter_by(message_type="init_reason").count() == 1
    assert db.query(TaskAwarenessEvent).filter_by(event_type="TASK_INITIALIZED").count() == 1
    assert db.get(TaskChatSubmission, "other-pending").status == "PREPARING"
    assert db.get(SddTask, "unrelated").session_generation == 8
    scheduled.assert_awaited_once()


@pytest.mark.asyncio
async def test_rejected_input_rolls_back_reset_and_can_retry(initialize_api):
    app, db, scheduled = initialize_api
    state = db.get(CollaborationState, "t")
    state.driver_user_id = "other"
    digest = state.repository_set_digest
    state.repository_set_digest = "invalid"
    db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        rejected = await client.post("/api/workspaces/w/tasks/t/initialize", json={"prompt": "retry"})
        assert rejected.status_code == 409, rejected.text
        db.expire_all()
        task = db.get(SddTask, "t")
        assert task.session_id == "previous-session"
        assert task.session_generation == state.session_generation == 1
        assert task.status == TaskStatus.INTERRUPTED
        assert state.sync_phase == "READY" and state.pending_submission_id is None
        assert db.query(TaskChatSubmission).filter_by(task_id="t").count() == 0
        assert db.query(TaskAwarenessEvent).filter_by(event_type="TASK_INITIALIZED").count() == 0
        assert db.query(ChatMessage).filter_by(task_id="t").count() == 0
        scheduled.assert_not_awaited()
        state.repository_set_digest = digest
        db.commit()
        retried = await client.post("/api/workspaces/w/tasks/t/initialize", json={"prompt": "retry"})
        assert retried.status_code == 200, retried.text
    db.expire_all()
    assert db.get(SddTask, "t").session_generation == 2
    assert submissions._load_preparation(db, retried.json()["submission"]["id"]) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["PREPARING", "RUNNING", "RECOVERY_REQUIRED"])
async def test_initialize_keeps_server_write_barriers(initialize_api, phase):
    app, db, scheduled = initialize_api
    state = db.get(CollaborationState, "t")
    state.sync_phase = phase
    state.recovery_kind = "SERVER_INPUT" if phase == "RECOVERY_REQUIRED" else None
    state.lease_expires_at = datetime.utcnow() - timedelta(days=1)
    db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/workspaces/w/tasks/t/initialize", json={"prompt": "retry"})
        assert response.status_code == 409, response.text
    db.expire_all()
    assert db.get(SddTask, "t").session_id == "previous-session"
    assert db.get(SddTask, "t").session_generation == 1
    assert state.sync_phase == phase
    scheduled.assert_not_awaited()


@pytest.mark.asyncio
async def test_checkpoint_failure_finishes_receipt_and_allows_next_initialize(initialize_api, monkeypatch):
    app, db, _ = initialize_api
    state = db.get(CollaborationState, "t")
    state.driver_user_id = "other"
    state.lease_expires_at = datetime.utcnow() - timedelta(days=1)
    db.commit()
    monkeypatch.setattr("app.agents.selection.resolve_task_backend", lambda *_: "opencode")
    capture = AsyncMock(side_effect=FileNotFoundError("deleted checkpoint"))
    monkeypatch.setattr(task_session_service.task_session_snapshot_service, "create_checkpoint", capture)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/workspaces/w/tasks/t/initialize", json={"prompt": "failed round"})
        assert response.status_code == 200, response.text
        receipt_id = response.json()["submission"]["id"]
        await submissions._run(receipt_id)
        db.expire_all()
        failed = db.get(TaskChatSubmission, receipt_id)
        assert failed.status == "FAILED" and failed.active_task_id is None
        assert failed.ai_job_id is None and failed.chat_message_id is None
        assert state.sync_phase == "READY" and state.pending_submission_id is None
        assert db.query(SddAiJob).count() == 0
        assert db.query(ChatMessage).filter_by(task_id="t", role="user").count() == 0
        capture.assert_awaited_once()
        retried = await client.post("/api/workspaces/w/tasks/t/initialize", json={"prompt": "next round"})
        assert retried.status_code == 200, retried.text
    db.expire_all()
    assert db.get(SddTask, "t").session_generation == 3
    assert submissions._load_preparation(db, retried.json()["submission"]["id"])["content"] == "next round"
    assert db.get(TaskChatSubmission, receipt_id).status == "FAILED"
