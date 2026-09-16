"""
任务创建准备态（PROVISIONING）测试

覆盖：创建任务即进入 PROVISIONING（防 worktree 未完成即可启动）、
准备完成后回到 PENDING、PROVISIONING 期间 start 接口拒绝。
"""

import asyncio
import os
import sys
from types import SimpleNamespace
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.dirname(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

from app.domains.task.models.task import TaskStatus  # noqa: E402
from app.config import settings  # noqa: E402
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob  # noqa: E402
from app.domains.task.models.chat import ChatMessage  # noqa: E402
from app.domains.task.routers import task as task_router  # noqa: E402
from test_workspace_asset_boundary import _build_db, _session, _seed_workspace  # noqa: E402


@pytest.fixture(autouse=True)
def local_task_locks(monkeypatch):
    # These route tests use SQLite and a single event loop, not live Redis.
    from app.core import distributed_lock
    monkeypatch.setattr(distributed_lock, "_PROVIDER", distributed_lock.LocalLockProvider())


def _build_app(SessionLocal, user):
    def _override_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(task_router.router, prefix="/api")
    app.dependency_overrides[task_router.get_db] = _override_db
    app.dependency_overrides[task_router.get_current_user] = lambda: user
    return app


def test_created_task_starts_in_provisioning_and_prepare_moves_to_pending(tmp_path):
    from app.domains.task.services.task_service import (
        create_task_record_for_provision,
        prepare_task_resources_for_provision,
    )

    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, _ = _seed_workspace(db, workspace_id="ws-prov", task_id="task-prov")
            workspace.project_path = str(tmp_path)
            db.commit()

            task = create_task_record_for_provision(
                db,
                user,
                workspace.id,
                name="Provisioned task",
            )
            # 创建即进入准备态：git worktree/clone 未完成前禁止启动
            assert task.status == TaskStatus.PROVISIONING.value

            # 资源准备完成后回到 PENDING（可启动）
            prepared = prepare_task_resources_for_provision(
                db,
                workspace_id=workspace.id,
                task_id=task.id,
            )
            assert prepared.status == TaskStatus.PENDING.value
            assert os.path.exists(prepared.project_path)
    finally:
        engine.dispose()


def test_start_task_rejected_while_provisioning(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-prov2", task_id="task-prov2")
            task.status = TaskStatus.PROVISIONING.value
            task.project_path = str(tmp_path)
            db.commit()
            ws_id, task_id = workspace.id, task.id
        client = TestClient(_build_app(SessionLocal, user))

        resp = client.post(f"/api/workspaces/{ws_id}/tasks/{task_id}/start", json={})
        assert resp.status_code == 409, resp.text
        assert "provision" in resp.json()["detail"].lower()
    finally:
        engine.dispose()


def test_start_task_persists_user_initial_prompt_and_links_job(tmp_path, monkeypatch):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-start", task_id="task-start")
            task.status = TaskStatus.PENDING.value
            task.project_path = str(tmp_path)
            task.description = "backend task description"
            db.commit()
            ws_id, task_id = workspace.id, task.id

        async def _enqueue(_job_id):
            return None

        monkeypatch.setattr(task_router, "get_engine", lambda _task_id: None)
        monkeypatch.setattr(task_router.ai_job_service, "enqueue_task_chat_job", _enqueue)
        client = TestClient(_build_app(SessionLocal, user))

        resp = client.post(
            f"/api/workspaces/{ws_id}/tasks/{task_id}/start",
            json={"prompt": "用户真正提交的启动提示"},
        )

        assert resp.status_code == 200, resp.text
        with _session(SessionLocal) as db:
            message = db.query(ChatMessage).filter(ChatMessage.task_id == task_id).one()
            job = db.query(SddAiJob).filter(SddAiJob.task_id == task_id).one()
            assert message.role.value == "user"
            assert message.content == "用户真正提交的启动提示"
            assert message.metadata_json["source"] == "task_start"
            assert job.prompt_text.startswith("用户真正提交的启动提示")
            assert job.context_json["source"] == "task_start"
    finally:
        engine.dispose()


def test_initialize_task_uses_requested_initial_prompt(tmp_path, monkeypatch):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-init-prompt", task_id="task-init-prompt")
            task.project_path = str(tmp_path)
            task.description = "task description fallback"
            db.commit()
            ws_id, task_id = workspace.id, task.id

        captured = {}

        async def _run_db_txn(fn):
            with _session(SessionLocal) as db:
                return fn(db)

        async def _create_task_chat_turn(**kwargs):
            captured.update(kwargs)
            with _session(SessionLocal) as db:
                job = task_router.ai_job_service.create_task_chat_job(
                    db,
                    workspace_id=workspace.id,
                    task_id=task_id,
                    creator_id=user.id,
                    prompt_text=kwargs["prompt_text"],
                    context_json=kwargs["context_json"],
                )
                return SimpleNamespace(job_id=job.id)

        async def _enqueue(_job_id):
            return None

        monkeypatch.setattr(task_router, "run_db_txn", _run_db_txn)
        monkeypatch.setattr(task_router.task_session_service, "create_task_chat_turn", _create_task_chat_turn)
        monkeypatch.setattr(task_router.ai_job_service, "enqueue_task_chat_job", _enqueue)
        monkeypatch.setattr(task_router, "get_engine", lambda _task_id: None)
        client = TestClient(_build_app(SessionLocal, user))

        resp = client.post(
            f"/api/workspaces/{ws_id}/tasks/{task_id}/initialize",
            json={"prompt": "用户编辑后的初始化提示", "reason": "重新开始"},
        )

        assert resp.status_code == 200, resp.text
        assert captured["content"] == "用户编辑后的初始化提示"
        assert captured["prompt_text"] == "用户编辑后的初始化提示"
        assert captured["context_json"]["initialize_reason"] == "重新开始"
    finally:
        engine.dispose()


@pytest.mark.parametrize("old_status", [AiJobStatus.FAILED, AiJobStatus.INTERRUPTED, AiJobStatus.RUNNING])
def test_initialize_after_failed_or_interrupted_attempt(tmp_path, monkeypatch, old_status):
    engine, factory = _build_db()
    try:
        with _session(factory) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-recover", task_id="task-recover")
            task.project_path = str(tmp_path)
            task.status = TaskStatus.INTERRUPTED
            task.session_id = "old-session"
            old = task_router.ai_job_service.create_task_chat_job(
                db, workspace_id=workspace.id, task_id=task.id,
                creator_id=user.id, prompt_text="old prompt",
            )
            old.status = old_status
            if old_status == AiJobStatus.RUNNING:
                old.run_token = "before-restart"
                old.worker_boot_id = "previous-worker"
                old.process_pid = 4321
            db.commit()
            old_id, task_id, ws_id = old.id, task.id, workspace.id

        async def noop(*args, **kwargs):
            pass

        async def stop_attempt(token, reason):
            assert token == "before-restart"
            return None  # A new worker has no in-memory process registration.

        async def stop_persisted(pid, started_at, reason, **kwargs):
            from app.agents.process_supervisor import TerminationResult
            assert pid == 4321
            assert kwargs["run_token"] == "before-restart"
            return TerminationResult(confirmed_dead=True, root_return_code=None)

        monkeypatch.setattr("app.database.SessionLocal", factory)
        monkeypatch.setattr(task_router.ai_job_service, "SessionLocal", factory)
        monkeypatch.setattr(task_router.ai_job_service.process_supervisor, "stop_attempt", stop_attempt)
        monkeypatch.setattr(task_router.ai_job_service.process_supervisor, "stop_persisted", stop_persisted)
        monkeypatch.setattr(task_router, "get_engine", lambda _: None)
        monkeypatch.setattr(task_router.ai_job_service, "publish_job", noop)
        monkeypatch.setattr(task_router.ai_job_service, "enqueue_task_chat_job", noop)
        client = TestClient(_build_app(factory, user))
        response = client.post(f"/api/workspaces/{ws_id}/tasks/{task_id}/initialize", json={"prompt": "restart"})
        assert response.status_code == 200, response.text
        with _session(factory) as db:
            from app.domains.task.models.task import SddTask
            task = db.get(SddTask, task_id)
            assert task.session_id is None
            assert task.session_generation == 1
            jobs = db.query(SddAiJob).filter_by(task_id=task_id).all()
            assert len(jobs) == 2
            assert db.get(SddAiJob, old_id).status in {AiJobStatus.FAILED, AiJobStatus.CANCELLED}
            assert next(j for j in jobs if j.id != old_id).status == AiJobStatus.PENDING
    finally:
        engine.dispose()


@pytest.mark.parametrize("recovery", ["unresolved", "late_finalizer", "stop_failure"])
def test_initialize_preserves_or_recovers_session_after_cleanup(monkeypatch, recovery):
    monkeypatch.setattr(settings, "TASK_SESSION_REVERT_WAIT_SECONDS", 0.3)
    engine, factory = _build_db()
    try:
        with _session(factory) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-blocked", task_id="task-blocked")
            task.session_id = "preserve-session"
            task.session_generation = 7
            task.error_message = "original failure"
            job = task_router.ai_job_service.create_task_chat_job(
                db, workspace_id=workspace.id, task_id=task.id,
                creator_id=user.id, prompt_text="old prompt",
            )
            job.status = AiJobStatus.ORPHANED
            job.run_token = "persisted-owner"
            db.commit()
            ws_id, task_id = workspace.id, task.id

        async def noop(*args, **kwargs):
            pass

        async def reap(*args, **kwargs):
            if recovery == "late_finalizer":
                async def finish():
                    await asyncio.sleep(0.02)
                    with _session(factory) as db:
                        old = db.query(SddAiJob).filter_by(task_id=task_id).one()
                        old.status = AiJobStatus.CANCELLED
                        old.run_token = None
                        db.commit()
                asyncio.create_task(finish())

        async def stop():
            raise RuntimeError("provider stop failed")

        monkeypatch.setattr("app.database.SessionLocal", factory)
        monkeypatch.setattr(task_router, "get_engine", lambda _: SimpleNamespace(stop=stop) if recovery == "stop_failure" else None)
        monkeypatch.setattr(task_router.ai_job_service, "publish_job", noop)
        monkeypatch.setattr(task_router.ai_job_service, "enqueue_task_chat_job", noop)
        monkeypatch.setattr(task_router.ai_job_service, "reap_stale_jobs", reap)
        client = TestClient(_build_app(factory, user), raise_server_exceptions=False)
        response = client.post(f"/api/workspaces/{ws_id}/tasks/{task_id}/initialize", json={})
        assert response.status_code == (200 if recovery == "late_finalizer" else 409), response.text
        with _session(factory) as db:
            from app.domains.task.models.task import SddTask
            task = db.get(SddTask, task_id)
            if recovery == "late_finalizer":
                assert (task.session_id, task.session_generation, task.error_message) == (None, 8, None)
                assert db.query(SddAiJob).filter_by(task_id=task_id, status=AiJobStatus.PENDING).count() == 1
            else:
                assert (task.session_id, task.session_generation, task.error_message) == ("preserve-session", 7, "original failure")
                assert db.query(ChatMessage).filter_by(task_id=task_id).count() == 0
    finally:
        engine.dispose()
