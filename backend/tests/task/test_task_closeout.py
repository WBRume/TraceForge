from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.task.models.task import SddTask, TaskStatus, TaskType
from app.domains.task.routers import task as task_router
from app.domains.task.routers import task_closeout as task_closeout_router
from app.domains.workspace_asset.models.workspace_asset import (
    SddEvidence,
    SddHumanReview,
    SddRequirement,
    SddRequirementAuditLog,
    SddTaskFinalSummary,
    SddTaskRequirement,
)
from app.domains.workspace_asset.routers import workspace_asset as workspace_asset_router
from app.domains.workspace_asset.services.tasks.detail import get_task_detail
from tests.workspace_asset.test_workspace_asset_boundary import _build_db, _seed_workspace, _session


def _build_closeout_app(SessionLocal, user):
    def _override_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(task_router.router, prefix="/api")
    app.include_router(task_closeout_router.router, prefix="/api")
    app.include_router(workspace_asset_router.router, prefix="/api")
    app.dependency_overrides[task_router.get_db] = _override_db
    app.dependency_overrides[task_router.get_current_user] = lambda: user
    app.dependency_overrides[task_closeout_router.get_db] = _override_db
    app.dependency_overrides[task_closeout_router.get_current_user] = lambda: user
    app.dependency_overrides[workspace_asset_router.get_db] = _override_db
    app.dependency_overrides[workspace_asset_router.get_current_user] = lambda: user
    return app


def test_complete_closeout_allows_no_evidence():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, _workspace, _task = _seed_workspace(db, workspace_id="ws-closeout-none", task_id="task-closeout-none")

        client = TestClient(_build_closeout_app(SessionLocal, user))
        response = client.post(
            "/api/workspaces/ws-closeout-none/tasks/task-closeout-none/closeout/complete",
            json={
                "completion_summary": "Implemented locally.",
                "landing_method": "HUMAN_ADJUSTED",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "DONE"
        assert payload["evidence_ids"] == []

        with _session(SessionLocal) as db:
            task = db.get(SddTask, "task-closeout-none")
            evidence = db.query(SddEvidence).filter(SddEvidence.task_id == "task-closeout-none").all()
            summary = db.query(SddTaskFinalSummary).filter(SddTaskFinalSummary.task_id == "task-closeout-none").one()
            assert task is not None
            assert task.status == TaskStatus.DONE
            assert evidence == []
            assert summary.final_status.value == "PARTIAL"
    finally:
        engine.dispose()


def test_complete_closeout_records_evidence_summary_and_done_status():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, _workspace, _task = _seed_workspace(db, workspace_id="ws-closeout", task_id="task-closeout")

        client = TestClient(_build_closeout_app(SessionLocal, user))
        response = client.post(
            "/api/workspaces/ws-closeout/tasks/task-closeout/closeout/complete",
            json={
                "completion_summary": "Implemented locally and compiled in the IDE.",
                "landing_method": "HUMAN_ADJUSTED",
                "commit_id": "abc1234",
                "human_delta": {
                    "status": "READY",
                    "title": "Manual API adjustment",
                    "summary": "Changed the AI output to use the internal API.",
                    "change_category": "framework_api_misuse",
                    "change_reason": "The AI output called the wrong helper.",
                },
                "decision": {
                    "status": "ACCEPTED",
                    "title": "Use existing internal helper",
                    "body": "Keep implementation aligned with local framework conventions.",
                },
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "DONE"
        assert payload["evidence_ids"]

        with _session(SessionLocal) as db:
            task = db.get(SddTask, "task-closeout")
            evidence = db.query(SddEvidence).filter(SddEvidence.task_id == "task-closeout").one()
            review = db.query(SddHumanReview).filter(SddHumanReview.task_id == "task-closeout").one()
            summary = db.query(SddTaskFinalSummary).filter(SddTaskFinalSummary.task_id == "task-closeout").one()
            detail_task = get_task_detail(db, "ws-closeout", "task-closeout")
            assert task is not None
            assert task.status == TaskStatus.DONE
            assert evidence.source_ref == "abc1234"
            assert review.status.value == "RESOLVED"
            assert review.review_type == "EXPERT_FINAL_REVIEW"
            assert summary.final_status.value == "PARTIAL"
            assert detail_task is not None
            assert detail_task.task.status == "DONE"
            assert detail_task.process_summary.coverage_status != "verified"

        old_complete = client.post("/api/workspaces/ws-closeout/tasks/task-closeout/complete")
        old_cancel = client.post("/api/workspaces/ws-closeout/tasks/task-closeout/cancel")
        assert old_complete.status_code == 404
        assert old_cancel.status_code == 404
    finally:
        engine.dispose()


def test_failure_closeout_records_failure_evidence_and_rejected_summary():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, _workspace, _task = _seed_workspace(db, workspace_id="ws-fail-closeout", task_id="task-fail-closeout")

        client = TestClient(_build_closeout_app(SessionLocal, user))
        response = client.post(
            "/api/workspaces/ws-fail-closeout/tasks/task-fail-closeout/closeout/fail",
            json={
                "failure_stage": "COMPILE",
                "failure_reason": "COMPILE_ERROR",
                "failure_summary": "Local compile failed after applying the AI plan.",
                "evidence_attachments": [
                    {
                        "filename": "compile.log",
                        "source_uri": "/api/upload/files/compile.log",
                        "source_path": "uploads/compile.log",
                        "source_label": "compile.log",
                    }
                ],
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "FAILED"
        assert payload["evidence_ids"]

        detail = client.get("/api/workspaces/ws-fail-closeout/workspace-assets/tasks/task-fail-closeout")
        assert detail.status_code == 200
        body = detail.json()
        assert body["task"]["status"] == TaskStatus.FAILED.value
        assert body["evidence"][0]["evidence_type"] == "FAILURE"
        assert body["final_summary"]["final_status"] == "REJECTED"
        assert body["clarifications"] == []
    finally:
        engine.dispose()


def test_failure_closeout_allows_no_attachment_and_preserves_summary():
    engine, sessions = _build_db()
    try:
        with _session(sessions) as db:
            user, workspace, task = _seed_workspace(db)
        client = TestClient(_build_closeout_app(sessions, user))
        response = client.post(
            f"/api/workspaces/{workspace.id}/tasks/{task.id}/closeout/fail",
            json={
                "failure_stage": "CODING",
                "failure_reason": "OTHER",
                "failure_summary": "Unable to reproduce the issue",
            },
        )
        assert response.status_code == 200
        assert response.json()["evidence_ids"] == []
        with _session(sessions) as db:
            assert db.get(SddTask, task.id).status == TaskStatus.FAILED
            assert db.query(SddEvidence).count() == 0
            assert db.query(SddTaskFinalSummary).one().summary == "Unable to reproduce the issue"
    finally:
        engine.dispose()


def test_diagnosis_completion_links_leaf_requirement_and_rejects_parent_before_writes():
    engine, sessions = _build_db()
    try:
        with _session(sessions) as db:
            user, workspace, task = _seed_workspace(db)
            task.task_type = TaskType.DIAGNOSIS
            db.add_all(
                [
                    SddRequirement(id="parent", workspace_id=workspace.id, title="Parent"),
                    SddRequirement(id="leaf", workspace_id=workspace.id, title="Leaf", parent_requirement_id="parent"),
                ]
            )
            db.commit()
        client = TestClient(_build_closeout_app(sessions, user))
        endpoint = f"/api/workspaces/{workspace.id}/tasks/{task.id}/closeout/complete"
        payload = {
            "completion_summary": "Root cause confirmed",
            "landing_method": "HUMAN_ADJUSTED",
            "requirement_id": "parent",
        }
        assert client.post(endpoint, json=payload).status_code == 409
        payload["requirement_id"] = "foreign-or-missing"
        assert client.post(endpoint, json=payload).status_code == 404
        with _session(sessions) as db:
            assert db.get(SddTask, task.id).status != TaskStatus.DONE
            assert db.query(SddTaskRequirement).count() == 0
            assert db.query(SddTaskFinalSummary).count() == 0
        payload["requirement_id"] = "leaf"
        assert client.post(endpoint, json=payload).status_code == 200
        with _session(sessions) as db:
            assert db.get(SddTask, task.id).status == TaskStatus.DONE
            assert db.query(SddTaskRequirement).one().requirement_id == "leaf"
            assert db.query(SddRequirementAuditLog).one().source_metadata_json["created_from"] == "task_closeout"
        detail = client.get(f"/api/workspaces/{workspace.id}/workspace-assets/requirements/leaf").json()
        assert detail["linked_tasks"][0]["task_id"] == task.id
    finally:
        engine.dispose()
