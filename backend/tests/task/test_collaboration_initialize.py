"""Initialization fences old local input and publishes only the clean baseline."""

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
from app.domains.ai.services.jobs import publishing
from app.domains.auth.models.user import User
from app.domains.notification.models.task_awareness import TaskAwarenessEvent
from app.domains.task.models.chat_submission import TaskChatSubmission
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.models.task_repository import SddTaskRepository
from app.domains.task.routers.task import session_runs
from app.domains.task.services import task_session_control_service as lifecycle
from app.domains.task.services import task_session_service
from app.domains.task.services.repository_updates.git import git
from app.domains.workspace_collaboration import control
from app.domains.workspace_collaboration.models import CollaborationState
from tests.task.test_collaboration_execution import collaboration_db as collaboration_db


@pytest.fixture
def initialize_api(collaboration_db, monkeypatch, tmp_path):
    db = collaboration_db
    db.add(User(id="other", email="initialize-other@test.local", hashed_password="x", display_name="Other"))
    task = db.get(SddTask, "t")
    task.session_id = "previous-session"
    task.status = TaskStatus.INTERRUPTED
    root = tmp_path / "task"
    root.mkdir()
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    git(upstream, "init", "-b", "release/2.x")
    (upstream / "base.txt").write_text("base")
    git(upstream, "add", ".")
    git(upstream, "commit", "-m", "base")
    git(tmp_path, "clone", str(upstream), str(root / "api"))
    task.project_path = str(root)
    db.get(SddTaskRepository, "api").repo_url = str(upstream)
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
    monkeypatch.setattr(publishing, "enqueue_task_chat_job", scheduled)
    monkeypatch.setattr("app.agents.selection.resolve_task_backend", lambda *_: "opencode")
    monkeypatch.setattr(
        task_session_service.task_session_snapshot_service,
        "create_checkpoint",
        AsyncMock(return_value={"root": str(tmp_path / "checkpoint")}),
    )

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
    db.expire_all()
    task = db.get(SddTask, "t")
    job = db.get(SddAiJob, response.json()["job"]["id"])
    assert task.session_generation == job.session_generation == 2
    assert task.session_id is None
    assert job.session_id is None and job.context_json["fresh_session"] is True
    assert job.prompt_text == "Check cloud code"
    assert not state.enabled and state.input_snapshot_id is None
    assert state.lease_epoch > identity[3] and state.binding_id != "binding"
    assert db.query(SddAiJob).count() == 1
    assert db.query(TaskChatSubmission).filter_by(task_id="t").count() == 0
    assert db.query(TaskAwarenessEvent).filter_by(event_type="TASK_INITIALIZED").count() == 1
    assert db.get(TaskChatSubmission, "other-pending").status == "PREPARING"
    assert db.get(SddTask, "unrelated").session_generation == 8
    scheduled.assert_awaited_once()


@pytest.mark.asyncio
async def test_old_input_is_discarded_even_if_its_digest_is_invalid(initialize_api):
    app, db, scheduled = initialize_api
    state = db.get(CollaborationState, "t")
    state.repository_set_digest = "invalid-old-input"
    db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await client.post("/api/workspaces/w/tasks/t/initialize", json={"prompt": "retry"})
        assert result.status_code == 200, result.text
    db.expire_all()
    assert not state.enabled and state.input_snapshot_id is None
    assert db.get(SddTask, "t").session_generation == 2
    assert db.query(TaskChatSubmission).filter_by(task_id="t").count() == 0
    scheduled.assert_awaited_once()


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
async def test_checkpoint_failure_resumes_same_operation_and_generation(initialize_api, monkeypatch):
    app, db, scheduled = initialize_api
    capture = AsyncMock(side_effect=[FileNotFoundError("deleted checkpoint"), {"root": "clean-checkpoint"}])
    monkeypatch.setattr(task_session_service.task_session_snapshot_service, "create_checkpoint", capture)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/workspaces/w/tasks/t/initialize", json={"prompt": "original round", "operation_id": "operation-test"}
        )
        assert response.status_code == 409, response.text
        status = (await client.get("/api/workspaces/w/tasks/t/initialize")).json()["operation"]
        assert status["id"] == "operation-test" and status["state"] == "STARTING"
        assert "roots" not in status and "url" not in status["repositories"][0]
        retried = await client.post(
            "/api/workspaces/w/tasks/t/initialize", json={"prompt": "changed round", "operation_id": status["id"]}
        )
        assert retried.status_code == 200, retried.text
    db.expire_all()
    assert db.get(SddTask, "t").session_generation == 2
    assert db.query(SddAiJob).count() == 1
    assert db.query(SddAiJob).one().prompt_text == "original round"
    scheduled.assert_awaited_once()
