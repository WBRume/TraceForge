"""
任务创建准备态（PROVISIONING）测试

覆盖：创建任务即进入 PROVISIONING（防 worktree 未完成即可启动）、
准备完成后回到 PENDING、PROVISIONING 期间 start 接口拒绝。
"""

import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.dirname(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

from app.domains.task.models.task import TaskStatus  # noqa: E402
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
