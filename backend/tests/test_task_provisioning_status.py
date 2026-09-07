"""
任务创建准备态（PROVISIONING）测试

覆盖：创建任务即进入 PROVISIONING（防 worktree 未完成即可启动）、
准备完成后回到 PENDING、PROVISIONING 期间 start 接口拒绝。
"""

import os
import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.dirname(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

from app.domains.task.models.task import TaskStatus  # noqa: E402
from app.domains.ai.models.ai_job import SddAiJob  # noqa: E402
from app.domains.task.models.chat import ChatMessage  # noqa: E402
from app.domains.task.routers import task as task_router  # noqa: E402
from test_workspace_asset_boundary import _build_db, _session, _seed_workspace  # noqa: E402


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
