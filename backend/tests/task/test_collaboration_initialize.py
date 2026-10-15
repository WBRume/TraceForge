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
    from app.config import settings

    monkeypatch.setattr(settings, "TASK_SESSION_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))
    monkeypatch.setattr(settings, "COLLABORATION_SNAPSHOT_ROOT", str(tmp_path / "collaboration"))

    def get_session():
        with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(session_runs.router, prefix="/api")
    app.dependency_overrides[get_db] = get_session
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u")
    return app, db, scheduled


IDENTITY = {"client_id": "desktop", "instance_id": "instance", "binding_id": "binding"}


async def begin(client, **extra):
    return await client.post(
        "/api/workspaces/w/tasks/t/initialize",
        json={
            "prompt": "Check cloud code",
            "operation_id": "operation-test",
            "collaboration": IDENTITY,
            **extra,
        },
    )


def receipt(command):
    return {key: command[key] for key in ("task_id", "operation_id", "binding_id")} | {
        "repositories": [
            {"task_repository_id": row["task_repository_id"], "head": row["target"], "clean": True}
            for row in command["repositories"]
        ]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["READY", "DELIVERY_PENDING", "CONFLICT_PENDING", "RECOVERY_REQUIRED"])
@pytest.mark.parametrize("connected", [True, False])
async def test_initialize_requires_local_receipt_before_new_generation(initialize_api, phase, connected):
    app, db, scheduled = initialize_api
    state = db.get(CollaborationState, "t")
    state.sync_phase = phase
    state.lease_expires_at = datetime.utcnow() + timedelta(minutes=5 if connected else -5)
    db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await begin(client)
        assert first.status_code == 200, first.text
        command = first.json()["local_reset"]
        db.expire_all()
        assert db.get(SddTask, "t").session_generation == 1
        assert not state.enabled and state.binding_id != "binding"
        assert db.query(SddAiJob).count() == 0
        scheduled.assert_not_awaited()
        status = (await client.get("/api/workspaces/w/tasks/t/initialize")).json()["operation"]
        assert status["state"] == "WAITING_LOCAL"
        assert (await begin(client)).json()["local_reset"] == command
        invalid = receipt(command)
        invalid["repositories"] = []
        assert (await begin(client, local_reset_receipt=invalid)).status_code == 409
        done = await begin(client, local_reset_receipt=receipt(command))
        assert done.status_code == 200, done.text
        repeated = await begin(client, local_reset_receipt=receipt(command))
        assert repeated.json()["job"]["id"] == done.json()["job"]["id"]
    db.expire_all()
    job = db.get(SddAiJob, done.json()["job"]["id"])
    assert db.get(SddTask, "t").session_generation == job.session_generation == 2
    assert db.query(SddAiJob).count() == 1
    assert state.enabled and state.sync_phase == "RUNNING" and state.run_id == job.id
    assert job.context_json["collaboration"]["binding_id"] == command["binding_id"]
    assert state.input_snapshot_id != "input"
    assert db.get(TaskChatSubmission, "other-pending").status == "PREPARING"
    assert db.get(SddTask, "unrelated").session_generation == 8


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", [None, {**IDENTITY, "client_id": "other"}, {**IDENTITY, "binding_id": "stale"}])
async def test_initialize_rejects_missing_or_stale_desktop_before_mutation(initialize_api, identity):
    app, db, scheduled = initialize_api
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await begin(client, collaboration=identity)
        assert result.status_code == 409, result.text
    db.expire_all()
    assert db.get(SddTask, "t").session_id == "previous-session"
    assert db.get(CollaborationState, "t").binding_id == "binding"
    scheduled.assert_not_awaited()


@pytest.mark.asyncio
async def test_checkpoint_failure_resumes_after_local_receipt_once(initialize_api, monkeypatch):
    app, db, scheduled = initialize_api
    original = task_session_service.task_session_snapshot_service.create_checkpoint
    calls = 0

    async def interrupted(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise FileNotFoundError("deleted checkpoint")
        return await original(*args, **kwargs)

    capture = AsyncMock(side_effect=interrupted)
    monkeypatch.setattr(task_session_service.task_session_snapshot_service, "create_checkpoint", capture)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        command = (await begin(client)).json()["local_reset"]
        response = await begin(
            client, local_reset_receipt=receipt(command), collaboration={**IDENTITY, "instance_id": "restarted"}
        )
        assert response.status_code == 409, response.text
        status = (await client.get("/api/workspaces/w/tasks/t/initialize")).json()["operation"]
        assert status["state"] == "STARTING"
        assert "roots" not in status and "url" not in status["repositories"][0]
        retried = await begin(client, prompt="changed round")
        assert retried.status_code == 200, retried.text
    db.expire_all()
    assert db.get(SddTask, "t").session_generation == 2
    assert db.query(SddAiJob).count() == 1
    assert db.query(SddAiJob).one().prompt_text == "Check cloud code"
    assert db.get(CollaborationState, "t").instance_id == "restarted"
    scheduled.assert_awaited_once()
