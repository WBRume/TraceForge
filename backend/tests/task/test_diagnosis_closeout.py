import pytest
from fastapi.testclient import TestClient

from app.domains.task.models.task import SddTask, TaskStatus, TaskType
from app.domains.workspace_asset.models.workspace_asset import (
    SddEvidence,
    SddTaskFinalSummary,
    SddTaskProcessAuditLog,
    SddTaskRequirement,
)
from tests.task.test_task_closeout import _build_closeout_app
from tests.workspace_asset.test_workspace_asset_boundary import _build_db, _seed_workspace, _session


@pytest.fixture
def closeout_task():
    engine, sessions = _build_db()
    try:
        with _session(sessions) as db:
            user, workspace, task = _seed_workspace(db)
            task.task_type = TaskType.DIAGNOSIS
            db.commit()
        client = TestClient(_build_closeout_app(sessions, user))
        yield sessions, client, workspace.id, task.id
    finally:
        engine.dispose()


@pytest.mark.parametrize("with_attachment", [False, True])
def test_diagnosis_completion_records_method_without_implying_code_implementation(closeout_task, with_attachment):
    sessions, client, workspace_id, task_id = closeout_task
    payload = {"completion_summary": "Root cause identified from runtime logs", "landing_method": "AI_DIAGNOSED"}
    if with_attachment:
        payload["evidence_attachments"] = [{"filename": "runtime.log", "source_uri": "/api/upload/files/runtime.log"}]
    response = client.post(f"/api/workspaces/{workspace_id}/tasks/{task_id}/closeout/complete", json=payload)
    assert response.status_code == 200, response.text
    with _session(sessions) as db:
        assert db.get(SddTask, task_id).status == TaskStatus.DONE
        summary = db.query(SddTaskFinalSummary).one()
        assert summary.final_status.value == "PARTIAL"
        assert "diagnosis closeout" in summary.remaining_risk
        assert "local development" not in summary.remaining_risk
        assert any("AI_DIAGNOSED" in (audit.reason or "") for audit in db.query(SddTaskProcessAuditLog).all())
        if with_attachment:
            evidence = db.query(SddEvidence).one()
            assert evidence.source_metadata_json["landing_method"] == "AI_DIAGNOSED"
            assert evidence.source_metadata_json["task_type"] == "DIAGNOSIS"
        else:
            assert db.query(SddEvidence).count() == 0


@pytest.mark.parametrize("with_attachment", [False, True])
def test_diagnosis_failure_persists_stage_and_reason(closeout_task, with_attachment):
    sessions, client, workspace_id, task_id = closeout_task
    payload = {
        "failure_stage": "REPRODUCTION",
        "failure_reason": "NOT_REPRODUCIBLE",
        "failure_summary": "Available logs do not reproduce the issue",
    }
    if with_attachment:
        payload["evidence_attachments"] = [
            {"filename": "reproduction.log", "source_uri": "/api/upload/files/repro.log"}
        ]
    response = client.post(f"/api/workspaces/{workspace_id}/tasks/{task_id}/closeout/fail", json=payload)
    assert response.status_code == 200, response.text
    with _session(sessions) as db:
        assert db.get(SddTask, task_id).status == TaskStatus.FAILED
        summary = db.query(SddTaskFinalSummary).one()
        assert summary.remaining_risk == "Failure stage: REPRODUCTION; reason: NOT_REPRODUCIBLE."
        assert "hypotheses" in summary.next_steps
        if with_attachment:
            evidence = db.query(SddEvidence).one()
            assert evidence.source_metadata_json["failure_stage"] == "REPRODUCTION"
            assert evidence.source_metadata_json["failure_reason"] == "NOT_REPRODUCIBLE"


@pytest.mark.parametrize(
    ("task_type", "action", "fields"),
    [
        (TaskType.DIAGNOSIS, "complete", {"landing_method": "HUMAN_ADJUSTED"}),
        (TaskType.DIAGNOSIS, "fail", {"failure_stage": "COMPILE", "failure_reason": "OTHER"}),
        (TaskType.DIAGNOSIS, "fail", {"failure_stage": "OTHER", "failure_reason": "COMPILE_ERROR"}),
        (TaskType.DEVELOPMENT, "complete", {"landing_method": "AI_DIAGNOSED"}),
        (TaskType.DEVELOPMENT, "fail", {"failure_stage": "REPRODUCTION", "failure_reason": "OTHER"}),
        (TaskType.DEVELOPMENT, "fail", {"failure_stage": "OTHER", "failure_reason": "NOT_REPRODUCIBLE"}),
    ],
)
def test_task_type_mismatch_is_rejected_before_closeout_writes(closeout_task, task_type, action, fields):
    sessions, client, workspace_id, task_id = closeout_task
    with _session(sessions) as db:
        task = db.get(SddTask, task_id)
        task.task_type = task_type
        original_status = task.status
        db.commit()
    response = client.post(
        f"/api/workspaces/{workspace_id}/tasks/{task_id}/closeout/{action}",
        json={
            **fields,
            "completion_summary": "Root cause confirmed",
            "failure_summary": "Blocked",
            "requirement_id": "must-not-be-linked",
            "evidence_attachments": [{"filename": "test.log", "source_uri": "/api/upload/files/test.log"}],
        },
    )
    assert response.status_code == 422, response.text
    with _session(sessions) as db:
        assert db.get(SddTask, task_id).status == original_status
        assert db.query(SddEvidence).count() == 0
        assert db.query(SddTaskFinalSummary).count() == 0
        assert db.query(SddTaskRequirement).count() == 0
