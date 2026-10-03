"""Real task routes and SQLite lifecycle with a failed Redis release command."""

import asyncio
from types import SimpleNamespace
from unittest import mock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError

from app import database
from app.agents import selection
from app.agents.contract import AgentStopResult
from app.config import settings
from app.core import distributed_lock as dl
from app.core.offload import run_db_txn_with_bind
from app.dependencies import get_current_user, get_db
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.ai.services.jobs import publishing, registry
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.routers.task import session_control, session_runs
from app.domains.task.routers.task.deps import TASK_BUSY_MSG
from app.domains.task.services import task_session_control_service as lifecycle
from app.domains.task.services import task_session_snapshot_service
from tests.ai.jobs.ai_job_test_utils import patch_ai_job_db
from tests.core.test_redis_lock_release import RedisLockTransport
from tests.workspace_asset.test_workspace_asset_boundary import _build_db, _seed_workspace


@pytest.fixture
def task_api(monkeypatch):
    db_engine, SessionLocal = _build_db()
    with SessionLocal() as db:
        _user, _workspace, task = _seed_workspace(db)
        task.status = TaskStatus.INTERRUPTED
        task.session_generation = 1
        task.session_id = "old-session"
        db.commit()

    class RemoteEngine:
        running = False
        current_job_id = None
        session_id = None
        interrupts = 0

        async def stop(self):
            self.running = False

        async def interrupt(self):
            self.interrupts += 1
            self.running = False
            return AgentStopResult(execution_kind="REMOTE_SESSION", stop_acknowledged=True)

    remote = RemoteEngine()
    monkeypatch.setattr(database, "SessionLocal", SessionLocal)
    patch_ai_job_db(monkeypatch, SessionLocal)
    monkeypatch.setattr(lifecycle, "get_engine", lambda _task_id: remote)
    monkeypatch.setattr(selection, "resolve_task_backend", lambda *_args: "opencode")
    monkeypatch.setattr(task_session_snapshot_service, "create_checkpoint", mock.AsyncMock(return_value={"root": "isolated-checkpoint"}))
    monkeypatch.setattr(settings, "DISTRIBUTED_LOCK_BLOCKING_TIMEOUT_SECONDS", 0.05)
    broadcast = mock.AsyncMock()
    monkeypatch.setattr(lifecycle.task_ws_manager, "send_message_to_room", broadcast)
    monkeypatch.setattr(publishing, "publish_job", mock.AsyncMock())

    async def enqueue(job_id):
        # Simulate the remote worker reaching a native form wait. Keep real
        # initialization, messages, generations and termination finalization.
        def start(db):
            job = db.get(SddAiJob, job_id)
            job.status = AiJobStatus.RUNNING
            job.run_token = job.id
            job.worker_boot_id = registry.WORKER_BOOT_ID
            job.process_execution_kind = "REMOTE_SESSION"
            job.session_id = f"session-{job.session_generation}"
            remote.session_id = job.session_id
            remote.current_job_id = job.id
            remote.running = True
            db.add(ChatMessage(
                task_id=job.task_id, workspace_id=job.workspace_id, creator_id="user-1",
                role="assistant", content="Questions", message_type="text",
                session_generation=job.session_generation,
                metadata_json={"confirmation": {"job_id": job.id, "kind": "form", "fields": [
                    {"name": "project", "label": "项目类型", "type": "text"},
                ]}},
            ))

        await run_db_txn_with_bind(db_engine, start)

    monkeypatch.setattr(publishing, "enqueue_task_chat_job", enqueue)
    transport = RedisLockTransport()
    monkeypatch.setattr(dl, "get_redis_client", mock.AsyncMock(return_value=transport))
    monkeypatch.setattr(dl, "_PROVIDER", dl.RedisLockProvider())

    def db_dependency():
        with SessionLocal() as db:
            yield db

    app = FastAPI()
    app.include_router(session_runs.router, prefix="/api")
    app.include_router(session_control.router, prefix="/api")
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-1")
    try:
        yield app, transport, remote, SessionLocal, broadcast
    finally:
        db_engine.dispose()


def test_initialize_then_stop_native_question_twice_after_release_disconnect(task_api):
    app, transport, remote, SessionLocal, broadcast = task_api

    async def run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for generation in (2, 3):
                transport.failures.append(RedisConnectionError("Connection lost"))
                initialized = await client.post("/api/workspaces/ws-1/tasks/task-1/initialize", json={"prompt": "创建 Python 项目，请提问"})
                assert initialized.status_code == 200, initialized.text
                job = initialized.json()["job"]
                assert job["session_generation"] == generation
                assert remote.running
                assert transport.values == {}

                stopped = await client.post("/api/workspaces/ws-1/tasks/task-1/interrupt")
                assert stopped.status_code == 200, stopped.text
                assert stopped.json()["status"] == "INTERRUPTED"
                assert stopped.json()["job"]["status"] == "INTERRUPTED"
                assert stopped.json()["job"]["session_generation"] == generation
                assert not remote.running
                assert transport.values == {}

                with SessionLocal() as db:
                    assert db.get(SddTask, "task-1").session_generation == generation
                    stopped_job = db.get(SddAiJob, job["id"])
                    assert stopped_job.status == AiJobStatus.INTERRUPTED
                    assert stopped_job.run_token is None
                    questions = db.query(ChatMessage).filter_by(role="assistant", session_generation=generation).all()
                    assert len(questions) == 1
                    assert questions[0].metadata_json["confirmation"]["job_id"] == job["id"]

    asyncio.run(run())
    assert remote.interrupts == 2
    assert sum(call.args[1].type == "task_interrupted" for call in broadcast.call_args_list) == 2


def test_stop_preserves_another_owner_and_uses_an_operation_conflict_message(task_api):
    app, transport, remote, _SessionLocal, _broadcast = task_api
    key = dl._sanitize_lock_key(resource_type="task", resource_id="task-1")
    transport.values[key] = b"other-request"

    async def run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/workspaces/ws-1/tasks/task-1/interrupt")
            assert response.status_code == 409
            assert response.json()["detail"] == TASK_BUSY_MSG
            assert "initialized" not in response.json()["detail"]

    asyncio.run(run())
    assert transport.values[key] == b"other-request"
    assert remote.interrupts == 0
