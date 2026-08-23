"""问题定位任务「一键总结问题案例」API 测试。

覆盖：POST /diagnosis-summary 创建后台总结任务、GET 状态查询
（前端轮询收敛）、进行中任务幂等、非诊断任务拒绝。
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

from app.domains.task.models.task import TaskType  # noqa: E402
from app.domains.task.routers import task as task_router  # noqa: E402
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob  # noqa: E402
from app.domains.ai.services import ai_job_service  # noqa: E402
from test_workspace_asset_boundary import _build_db, _seed_workspace, _session  # noqa: E402


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


def _seed_diagnosis_task(db, workspace_id="ws-summary", task_id="task-summary"):
    user, workspace, task = _seed_workspace(db, workspace_id=workspace_id, task_id=task_id)
    task.task_type = TaskType.DIAGNOSIS.value
    task.task_meta_json = {"phenomenon": "接口偶发超时", "priority": "P1"}
    db.commit()
    return user, workspace, task


def test_trigger_diagnosis_summary_creates_job_and_polls_status():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db)
        client = TestClient(_build_app(SessionLocal, user))
        ws_id, task_id = workspace.id, task.id

        resp = client.post(f"/api/workspaces/{ws_id}/tasks/{task_id}/diagnosis-summary")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["task_id"] == task_id
        job_id = data["job_id"]
        assert job_id

        with _session(SessionLocal) as db:
            job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
            assert job is not None
            assert job.channel == AiJobChannel.TASK_CHAT
            assert job.status == AiJobStatus.PENDING
            ctx = job.context_json if isinstance(job.context_json, dict) else {}
            assert ctx.get("job_kind") == "DIAGNOSIS_SUMMARY"

        # 进行中的总结任务幂等：重复触发返回同一 job
        resp2 = client.post(f"/api/workspaces/{ws_id}/tasks/{task_id}/diagnosis-summary")
        assert resp2.status_code == 200
        assert resp2.json()["job_id"] == job_id

        # 状态查询（前端轮询收敛）
        status_resp = client.get(
            f"/api/workspaces/{ws_id}/tasks/{task_id}/diagnosis-summary/{job_id}"
        )
        assert status_resp.status_code == 200, status_resp.text
        assert status_resp.json()["job_id"] == job_id
        assert status_resp.json()["status"] == AiJobStatus.PENDING.value
    finally:
        engine.dispose()


def test_diagnosis_summary_rejected_after_case_adopted():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(
                db,
                workspace_id="ws-summary-adopted",
                task_id="task-summary-adopted",
            )
            ws_id, task_id = workspace.id, task.id
        client = TestClient(_build_app(SessionLocal, user))

        # 确认采纳 → 一键生成案例草稿
        adopt_resp = client.post(
            f"/api/workspaces/{ws_id}/tasks/{task_id}/case-draft",
            json={},
        )
        assert adopt_resp.status_code == 201, adopt_resp.text

        # 案例已被采纳后禁止再次一键总结
        resp = client.post(
            f"/api/workspaces/{ws_id}/tasks/{task_id}/diagnosis-summary"
        )
        assert resp.status_code == 409, resp.text
        assert "already adopted" in resp.json()["detail"]
    finally:
        engine.dispose()


def test_diagnosis_summary_job_marker_blocks_auto_fill():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(
                db,
                workspace_id="ws-summary-marker",
                task_id="task-summary-marker",
            )
            assert ai_job_service._has_diagnosis_summary_job(db, task.id) is False
            job = ai_job_service.create_diagnosis_summary_job(
                db,
                workspace_id=workspace.id,
                task_id=task.id,
                creator_id=user.id,
            )
            assert job is not None
            assert ai_job_service._has_diagnosis_summary_job(db, task.id) is True
    finally:
        engine.dispose()


def test_diagnosis_summary_rejected_for_development_task():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-summary-dev", task_id="task-summary-dev")
            task.task_type = TaskType.DEVELOPMENT.value
            db.commit()
        client = TestClient(_build_app(SessionLocal, user))
        resp = client.post(
            f"/api/workspaces/{workspace.id}/tasks/{task.id}/diagnosis-summary"
        )
        assert resp.status_code == 403
    finally:
        engine.dispose()
