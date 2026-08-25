"""
问题定位任务：诊断文档上传（需求/日志）测试

覆盖：upload-diagnosis-doc 端点、DIAGNOSIS_DOC 资产创建与查询、
CLI 工作区 .sdd/diagnosis 文件落盘、研发任务拒绝、创建任务时描述兜底。
"""

import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.dirname(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

from app.domains.asset.routers import asset as asset_router  # noqa: E402
from app.domains.task.models.task import TaskType  # noqa: E402
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
    app.include_router(asset_router.router, prefix="/api")
    app.dependency_overrides[task_router.get_db] = _override_db
    app.dependency_overrides[task_router.get_current_user] = lambda: user
    app.dependency_overrides[asset_router.get_db] = _override_db
    app.dependency_overrides[asset_router.get_current_user] = lambda: user
    return app


def _seed_diagnosis_task(db, workspace_id="ws-diag-doc", task_id="task-diag-doc", project_path=None):
    user, workspace, task = _seed_workspace(db, workspace_id=workspace_id, task_id=task_id)
    task.task_type = TaskType.DIAGNOSIS.value
    task.project_path = project_path or task.project_path
    db.commit()
    return user, workspace, task


def test_upload_diagnosis_doc_creates_asset_and_cli_copy(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db, project_path=str(tmp_path))
            ws_id, task_id = workspace.id, task.id
        client = TestClient(_build_app(SessionLocal, user))

        resp = client.post(
            f"/api/workspaces/{ws_id}/tasks/{task_id}/upload-diagnosis-doc",
            files={"file": ("issue.log", b"2026-08-15 10:00:00 ERROR timeout", "text/plain")},
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["status"] == "success"
        assert payload["filename"] == "issue.log"
        assert payload["asset_id"]
        cli_path = payload["path"]
        assert cli_path.endswith(os.path.join(".sdd", "diagnosis", "issue.log"))
        assert os.path.exists(cli_path)
        with open(cli_path, "rb") as f:
            assert f.read() == b"2026-08-15 10:00:00 ERROR timeout"

        # 资产列表可查询（诊断文档抽屉数据源）
        resp = client.get(
            f"/api/workspaces/{ws_id}/assets",
            params={"task_id": task_id, "asset_type": "DIAGNOSIS_DOC", "page": 1, "page_size": 50},
        )
        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == payload["asset_id"]
        assert items[0]["name"] == "issue.log"

        # 重复上传同名文件 → 复用同一资产（新版本）
        resp = client.post(
            f"/api/workspaces/{ws_id}/tasks/{task_id}/upload-diagnosis-doc",
            files={"file": ("issue.log", b"updated log content", "text/plain")},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["asset_id"] == payload["asset_id"]
        resp = client.get(
            f"/api/workspaces/{ws_id}/assets",
            params={"task_id": task_id, "asset_type": "DIAGNOSIS_DOC", "page": 1, "page_size": 50},
        )
        assert resp.json()["total"] == 1
    finally:
        engine.dispose()


def test_upload_diagnosis_doc_requires_diagnosis_task(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-dev-doc", task_id="task-dev-doc")
            task.project_path = str(tmp_path)
            task.task_type = TaskType.DEVELOPMENT.value
            db.commit()
            ws_id, task_id = workspace.id, task.id
        client = TestClient(_build_app(SessionLocal, user))

        resp = client.post(
            f"/api/workspaces/{ws_id}/tasks/{task_id}/upload-diagnosis-doc",
            files={"file": ("req.md", b"# requirement", "text/markdown")},
        )
        assert resp.status_code == 403, resp.text
    finally:
        engine.dispose()


def test_create_diagnosis_task_uses_phenomenon_as_description():
    from app.domains.task.services.task_service import create_task_record_for_provision

    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, _ = _seed_workspace(db, workspace_id="ws-diag-desc", task_id="task-diag-desc")
            task = create_task_record_for_provision(
                db,
                user,
                workspace.id,
                name="Diag with phenomenon",
                task_type="DIAGNOSIS",
                phenomenon="接口偶发超时",
                priority="P1",
            )
            assert task.description == "接口偶发超时"
            assert task.task_meta_json["phenomenon"] == "接口偶发超时"

            task2 = create_task_record_for_provision(
                db,
                user,
                workspace.id,
                name="Diag with desc",
                description="自定义描述",
                task_type="DIAGNOSIS",
                phenomenon="页面白屏",
            )
            assert task2.description == "自定义描述"
    finally:
        engine.dispose()


def test_create_diagnosis_task_requires_phenomenon_via_service():
    from app.domains.task.services.task_service import create_task_record_for_provision

    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, _ = _seed_workspace(db, workspace_id="ws-diag-required", task_id="task-diag-required")
            with pytest.raises(ValueError, match="phenomenon is required"):
                create_task_record_for_provision(
                    db,
                    user,
                    workspace.id,
                    name="Diag without phenomenon",
                    task_type="DIAGNOSIS",
                )
    finally:
        engine.dispose()


def test_create_diagnosis_task_requires_phenomenon_via_api():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, _ = _seed_workspace(db, workspace_id="ws-diag-api-required", task_id="task-diag-api-required")
            ws_id = workspace.id
        client = TestClient(_build_app(SessionLocal, user))

        resp = client.post(
            f"/api/workspaces/{ws_id}/tasks",
            json={
                "name": "Diag without phenomenon",
                "task_type": "DIAGNOSIS",
            },
        )
        assert resp.status_code == 422, resp.text
        assert "phenomenon is required" in resp.text
    finally:
        engine.dispose()
