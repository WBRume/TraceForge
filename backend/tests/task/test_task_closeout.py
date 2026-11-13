from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.auth.models.user import User, WorkspaceMember, WorkspaceRole
from app.domains.dashboard.models.metric import SddDashboardMetric
from app.domains.local_resource import service as local_resources
from app.domains.notification.models.task_awareness import TaskAwarenessEvent
from app.domains.task.models.task import SddTask, TaskStatus, TaskType
from app.domains.task.models.task_event_outbox import TaskEventOutbox
from app.domains.task.models.task_status_event import TaskStatusEvent
from app.domains.task.routers import task as task_router
from app.domains.task.routers import task_closeout as task_closeout_router
from app.domains.task.services import status_machine
from app.domains.workspace_asset.models.evidence_attachment import TaskEvidenceAttachment
from app.domains.workspace_asset.models.workspace_asset import (
    SddEvidence,
    SddHumanReview,
    SddRequirement,
    SddRequirementAuditLog,
    SddTaskFinalSummary,
    SddTaskProcessAuditLog,
    SddTaskRequirement,
)
from app.domains.workspace_asset.routers import workspace_asset as workspace_asset_router
from app.domains.workspace_asset.services.task_final_workflow import review_service
from app.domains.workspace_asset.services.task_process import evidence_attachments
from app.domains.workspace_asset.services.tasks.detail import get_task_detail
from app.domains.workspace_collaboration.models import CollaborationState
from app.domains.workspace_collaboration.router import router as collaboration_router
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
    app.include_router(collaboration_router, prefix="/api")
    app.include_router(workspace_asset_router.router, prefix="/api")
    app.dependency_overrides[task_router.get_db] = _override_db
    app.dependency_overrides[task_router.get_current_user] = lambda: user
    app.dependency_overrides[task_closeout_router.get_db] = _override_db
    app.dependency_overrides[task_closeout_router.get_current_user] = lambda: user
    app.dependency_overrides[workspace_asset_router.get_db] = _override_db
    app.dependency_overrides[workspace_asset_router.get_current_user] = lambda: user
    return app


@pytest.fixture(autouse=True)
def _attachment_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(evidence_attachments, "ATTACHMENT_ROOT", tmp_path / "attachments")


def upload_closeout_file(client, workspace_id, task_id, name="build.log"):
    response = client.post(
        f"/api/workspaces/{workspace_id}/tasks/{task_id}/closeout/attachments",
        files={"file": (name, b"build output", "text/plain")},
    )
    assert response.status_code == 201, response.text
    return response.json()


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
        assert payload["status"] == "COMPLETED"
        assert payload["evidence_ids"] == []

        with _session(SessionLocal) as db:
            task = db.get(SddTask, "task-closeout-none")
            evidence = db.query(SddEvidence).filter(SddEvidence.task_id == "task-closeout-none").all()
            summary = db.query(SddTaskFinalSummary).filter(SddTaskFinalSummary.task_id == "task-closeout-none").one()
            assert task is not None
            assert task.status == TaskStatus.COMPLETED
            assert evidence == []
            assert summary.final_status.value == "PARTIAL"
    finally:
        engine.dispose()


@pytest.mark.parametrize("reuse_default", [False, True])
def test_complete_closeout_records_evidence_summary_and_done_status(reuse_default):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-closeout", task_id="task-closeout")
            db.add(
                SddEvidence(
                    id="prior-evidence",
                    workspace_id=workspace.id,
                    task_id=task.id,
                    source_type="OTHER",
                    source_ref="local-test-report",
                )
            )
            if reuse_default:
                db.add(
                    SddHumanReview(
                        id="prior-review",
                        workspace_id=workspace.id,
                        task_id=task.id,
                        reviewer_id=user.id,
                        review_type=review_service.EXPERT_REVIEW_TYPE,
                        status="RESOLVED",
                        title="Saved review title",
                        source_ref_json={"seed": review_service.DEFAULT_REVIEW_MARKER},
                        target_ref_json={"targets": [{"target_type": "EVIDENCE", "target_id": "prior-evidence"}]},
                    )
                )
            db.commit()

        client = TestClient(_build_closeout_app(SessionLocal, user))
        response = client.post(
            "/api/workspaces/ws-closeout/tasks/task-closeout/closeout/complete",
            json={
                "completion_summary": "Implemented locally and compiled in the IDE.",
                "landing_method": "HUMAN_ADJUSTED",
                "commit_id": "abc1234",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "COMPLETED"
        assert payload["evidence_ids"]

        with _session(SessionLocal) as db:
            task = db.get(SddTask, "task-closeout")
            evidence = db.query(SddEvidence).filter_by(task_id=task.id, source_ref="abc1234").one()
            review = db.query(SddHumanReview).filter(SddHumanReview.task_id == "task-closeout").one()
            summary = db.query(SddTaskFinalSummary).filter(SddTaskFinalSummary.task_id == "task-closeout").one()
            detail_task = get_task_detail(db, "ws-closeout", "task-closeout")
            assert task is not None
            assert task.status == TaskStatus.COMPLETED
            assert evidence.source_ref == "abc1234"
            assert review.status.value == "RESOLVED"
            assert review.review_type == "EXPERT_FINAL_REVIEW"
            assert review.outcome is None
            if reuse_default:
                assert review.id == "prior-review"
                assert review.title == "Saved review title"
            assert {target["target_id"] for target in review.target_ref_json["targets"]} == {
                evidence.id,
                "prior-evidence",
            }
            review_id = review.id
            assert summary.final_status.value == "PARTIAL"
            assert detail_task is not None
            assert detail_task.task.status == "COMPLETED"
            assert detail_task.process_summary.coverage_status != "verified"

        workflow = client.get(f"/api/workspaces/{workspace.id}/workspace-assets/tasks/{task.id}/final-workflow")
        assert workflow.status_code == 200, workflow.text
        review = workflow.json()["reviews"][0]
        assert review["id"] == review_id
        assert review["outcome"] is None
        assert {target["target_id"] for target in review["target_refs"]} == {"prior-evidence", *payload["evidence_ids"]}

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
        upload = upload_closeout_file(client, "ws-fail-closeout", "task-fail-closeout", "compile.log")
        response = client.post(
            "/api/workspaces/ws-fail-closeout/tasks/task-fail-closeout/closeout/fail",
            json={
                "failure_stage": "COMPILE",
                "failure_reason": "COMPILE_ERROR",
                "failure_summary": "Local compile failed after applying the AI plan.",
                "evidence_attachments": [{"attachment_id": upload["id"]}],
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


def test_attachment_permissions_follow_evidence_and_require_the_exact_association():
    engine, sessions = _build_db()
    try:
        with _session(sessions) as db:
            owner, workspace, task = _seed_workspace(db)
            viewer = User(id="reader", display_name="Reader", email="reader@example.com", hashed_password="x")
            outsider = User(id="outsider", display_name="Outsider", email="outsider@example.com", hashed_password="x")
            db.add_all([viewer, outsider])
            db.add(
                WorkspaceMember(
                    workspace_id=workspace.id,
                    user_id=viewer.id,
                    role=WorkspaceRole.VIEWER,
                    permissions_json='["VIEW_ASSETS"]',
                )
            )
            db.commit()
        owner_client = TestClient(_build_closeout_app(sessions, owner))
        viewer_client = TestClient(_build_closeout_app(sessions, viewer))
        outsider_client = TestClient(_build_closeout_app(sessions, outsider))
        uploaded = upload_closeout_file(owner_client, workspace.id, task.id, "测试报告.pdf")
        task_url = f"/api/workspaces/{workspace.id}/tasks/{task.id}"
        assert (
            viewer_client.post(f"{task_url}/closeout/attachments", files={"file": ("x.pdf", b"x")}).status_code == 403
        )
        completed = owner_client.post(
            f"{task_url}/closeout/complete",
            json={
                "landing_method": "HUMAN_ADJUSTED",
                "completion_summary": "Verified",
                "evidence_attachments": [{"attachment_id": uploaded["id"]}],
            },
        )
        assert completed.status_code == 200, completed.text
        evidence_id = completed.json()["evidence_ids"][0]
        evidence_url = f"/api/workspaces/{workspace.id}/workspace-assets/tasks/{task.id}/evidence"
        file_url = f"{evidence_url}/{evidence_id}/attachments/{uploaded['id']}"
        assert viewer_client.get(f"{evidence_url}/{evidence_id}").json()["attachments"] == [uploaded]
        received = viewer_client.get(file_url)
        assert received.status_code == 200
        assert received.content == b"build output"
        assert received.headers["content-disposition"].startswith("attachment; filename*=")
        assert received.headers["content-type"] == "application/pdf"
        assert outsider_client.get(file_url).status_code == 403
        assert viewer_client.get(file_url.replace(evidence_id, "other-evidence")).status_code == 404
        assert viewer_client.get(file_url.replace(f"/tasks/{task.id}/", "/tasks/other-task/")).status_code == 404
        assert viewer_client.get(f"/api/upload/files/{uploaded['id']}").status_code == 404
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "action,status,fields",
    [
        ("complete", "COMPLETED", {"completion_summary": "Accepted externally", "landing_method": "HUMAN_ADJUSTED"}),
        (
            "fail",
            "FAILED",
            {"failure_summary": "Delivery blocked", "failure_stage": "CODING", "failure_reason": "OTHER"},
        ),
    ],
)
def test_closeout_rolls_back_all_records_and_replays_committed_receipt(monkeypatch, action, status, fields):
    engine, sessions = _build_db()
    try:
        with _session(sessions) as db:
            user, workspace, task = _seed_workspace(db)

        client = TestClient(_build_closeout_app(sessions, user), raise_server_exceptions=False)
        endpoint = f"/api/workspaces/{workspace.id}/tasks/{task.id}/closeout/{action}"
        uploaded = upload_closeout_file(client, workspace.id, task.id)
        request = {
            **fields,
            "evidence_attachments": [{"attachment_id": uploaded["id"]}],
        }

        def reject_after_write(write):
            def reject(db, *args, **kwargs):
                result = write(db, *args, **kwargs)
                if action == "fail" or result is not None:
                    db.flush()
                    raise RuntimeError("Simulated failure before commit")
                return result

            return reject

        with monkeypatch.context() as patch:
            if action == "complete":
                patch.setattr(
                    review_service,
                    "ensure_expert_review_for_task",
                    reject_after_write(review_service.ensure_expert_review_for_task),
                )
            else:
                patch.setattr(
                    status_machine,
                    "remember_command_result",
                    reject_after_write(status_machine.remember_command_result),
                )
            assert client.post(endpoint, json=request).status_code == 500

        record_counts = {
            SddEvidence: 1,
            SddTaskFinalSummary: 1,
            SddHumanReview: int(action == "complete"),
            SddTaskProcessAuditLog: 3 if action == "complete" else 2,
            SddDashboardMetric: 1,
            TaskStatusEvent: 1,
            TaskEventOutbox: 1,
            TaskAwarenessEvent: 1,
        }
        with _session(sessions) as db:
            task = db.get(SddTask, task.id)
            assert task.status == TaskStatus.RUNNING
            assert task.business_state == "TASK_IN_PROGRESS"
            assert task.status_seq == 0
            assert all(db.query(model).count() == 0 for model in record_counts)
            pending = db.get(TaskEvidenceAttachment, uploaded["id"])
            assert pending.evidence_id is None
            assert evidence_attachments.attachment_path(pending).read_bytes() == b"build output"

        from app.domains.task.services import task_event_publisher

        with monkeypatch.context() as patch:
            patch.setattr(task_event_publisher, "wake", Mock(side_effect=RuntimeError("Response lost after commit")))
            assert client.post(endpoint, json=request).status_code == 500

        with _session(sessions) as db:
            original = status_machine.receipt(db, task.id, f"closeout:{action.upper()}")
            assert original is not None
            assert original["status"] == status
        replay = client.post(endpoint, json=request)
        assert replay.status_code == 200, replay.text
        assert replay.json() == original
        with _session(sessions) as db:
            assert {model: db.query(model).count() for model in record_counts} == record_counts
            assert db.get(TaskEvidenceAttachment, uploaded["id"]).evidence_id == original["evidence_ids"][0]
            assert db.query(SddTaskFinalSummary).one().final_evidence_ids_json == original["evidence_ids"]
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "action,expected_status,fields",
    [
        ("complete", "COMPLETED", {"completion_summary": "Accepted externally", "landing_method": "HUMAN_ADJUSTED"}),
        (
            "fail",
            "FAILED",
            {"failure_summary": "Delivery blocked", "failure_stage": "CODING", "failure_reason": "OTHER"},
        ),
    ],
)
@pytest.mark.parametrize(
    "location,phase,snapshot_id",
    [("SERVER", "DELIVERY_PENDING", None), ("SERVER", "CONFLICT_PENDING", "cloud"), ("LOCAL", None, None)],
)
def test_closeout_records_result_while_code_work_is_blocked(
    monkeypatch, action, expected_status, fields, location, phase, snapshot_id
):
    probe = Mock(side_effect=AssertionError("Closeout must not probe local execution resources"))
    monkeypatch.setattr(local_resources, "require_online", probe)
    engine, sessions = _build_db()
    try:
        with _session(sessions) as db:
            user, workspace, task = _seed_workspace(db)
            task.execution_location = location
            if phase:
                task.task_meta_json = {"repository_update": {"state": "RECOVERY_REQUIRED"}}
                db.add(
                    CollaborationState(
                        task_id=task.id,
                        sync_phase=phase,
                        snapshot_id=snapshot_id,
                        session_generation=task.session_generation,
                        session_revision=task.session_revision,
                        repository_set_digest="unresolved",
                        binding_id="binding",
                        driver_user_id=user.id,
                        client_id="desktop",
                        instance_id="instance",
                        lease_expires_at=datetime.utcnow() - timedelta(minutes=1),
                    )
                )
            db.commit()

        client = TestClient(_build_closeout_app(sessions, user))
        endpoint = f"/api/workspaces/{workspace.id}/tasks/{task.id}/closeout/{action}"
        uploaded = upload_closeout_file(client, workspace.id, task.id)
        request = {
            **fields,
            "evidence_attachments": [{"attachment_id": uploaded["id"]}],
        }
        assert client.post(endpoint, json={**request, "confirmed_server_snapshot_id": "stale"}).status_code == 422
        assert (
            client.post(
                endpoint,
                json={**request, "evidence_attachments": [{"attachment_id": uploaded["id"], "source_path": "old.log"}]},
            ).status_code
            == 422
        )
        response = client.post(endpoint, json=request)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == expected_status
        assert "confirmed_server_snapshot_id" not in response.json()
        assert client.post(endpoint, json=request).json() == response.json()
        probe.assert_not_called()
        with _session(sessions) as db:
            assert db.get(SddTask, task.id).status.value == expected_status
            assert db.query(SddTaskFinalSummary).one().review_checklist_json is None
            assert "collaboration" not in db.query(SddEvidence).one().source_metadata_json
            if phase:
                collaboration = db.get(CollaborationState, task.id)
                assert (collaboration.sync_phase, collaboration.snapshot_id) == (phase, snapshot_id)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "action,fields",
    [
        ("complete", {"completion_summary": "Accepted externally", "landing_method": "HUMAN_ADJUSTED"}),
        ("fail", {"failure_summary": "Delivery blocked", "failure_stage": "CODING", "failure_reason": "OTHER"}),
    ],
)
def test_closeout_requires_idle_agent_and_consent_from_the_current_host_owner(action, fields):
    engine, sessions = _build_db()
    try:
        with _session(sessions) as db:
            user, workspace, task = _seed_workspace(db)
            other = User(
                id="host",
                display_name="Other host",
                email="host@example.com",
                hashed_password="x",
                avatar_url="/avatars/host.png",
            )
            db.add(other)
            db.add(
                CollaborationState(
                    task_id=task.id,
                    sync_phase="CONFLICT_PENDING",
                    snapshot_id="cloud",
                    session_generation=task.session_generation,
                    session_revision=task.session_revision,
                    repository_set_digest="digest",
                    binding_id="binding",
                    driver_user_id=other.id,
                    client_id="desktop",
                    instance_id="instance",
                    lease_epoch=7,
                    lease_expires_at=datetime.utcnow() + timedelta(minutes=5),
                )
            )
            job = SddAiJob(
                id="active",
                workspace_id=workspace.id,
                task_id=task.id,
                creator_id=user.id,
                channel=AiJobChannel.TASK_CHAT,
                status=AiJobStatus.RUNNING,
                queue_key=f"TASK_CHAT:{task.id}",
            )
            db.add(job)
            db.commit()

        client = TestClient(_build_closeout_app(sessions, user))
        task_path = f"/api/workspaces/{workspace.id}/tasks/{task.id}"
        endpoint = f"{task_path}/closeout/{action}"
        consent = {**fields, "disconnect_collaboration_lease_epoch": 7}
        response = client.post(endpoint, json=consent)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "CLOSEOUT_AGENT_ACTIVE"
        with _session(sessions) as db:
            db.get(SddAiJob, job.id).status = AiJobStatus.SUCCESS
            db.commit()

        response = client.post(endpoint, json=consent)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "CLOSEOUT_COLLABORATION_CONNECTED"
        state = client.get(f"{task_path}/collaboration").json()
        assert state["driver_user_id"] == "host"
        assert state["driver_profile"] == {
            "display_name": "Other host",
            "avatar_url": "/avatars/host.png",
            "avatar_svg": None,
        }
        with _session(sessions) as db:
            state = db.get(CollaborationState, task.id)
            assert state.lease_epoch == 7
            assert db.query(SddTaskFinalSummary).count() == 0
            state.driver_user_id = user.id
            db.commit()

        assert client.post(endpoint, json=fields).status_code == 409
        assert client.post(endpoint, json={**consent, "disconnect_collaboration_lease_epoch": 6}).status_code == 409
        invalid = {**consent, "evidence_attachments": [{"filename": "missing-reference.txt"}]}
        assert client.post(endpoint, json=invalid).status_code == 422
        assert client.get(f"{task_path}/collaboration").json()["driver_connected"] is True
        result = client.post(endpoint, json=consent)
        assert result.status_code == 200, result.text
        assert result.json()["status"] == ("COMPLETED" if action == "complete" else "FAILED")
        assert client.post(endpoint, json=fields).json() == result.json()
        state = client.get(f"{task_path}/collaboration").json()
        assert state["driver_connected"] is False
        assert state["lease_epoch"] == 8
        assert state["snapshot_id"] == "cloud"
        assert state["sync_phase"] == "CONFLICT_PENDING"
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
            "landing_method": "HUMAN_ASSISTED_DIAGNOSIS",
            "requirement_id": "parent",
        }
        assert client.post(endpoint, json=payload).status_code == 409
        payload["requirement_id"] = "foreign-or-missing"
        assert client.post(endpoint, json=payload).status_code == 404
        with _session(sessions) as db:
            assert db.get(SddTask, task.id).status != TaskStatus.COMPLETED
            assert db.query(SddTaskRequirement).count() == 0
            assert db.query(SddTaskFinalSummary).count() == 0
        payload["requirement_id"] = "leaf"
        first = client.post(endpoint, json=payload)
        assert first.status_code == 200
        duplicate = client.post(endpoint, json=payload)
        assert duplicate.status_code == 200
        assert duplicate.json() == first.json()
        with _session(sessions) as db:
            assert db.get(SddTask, task.id).status == TaskStatus.COMPLETED
            assert db.query(SddTaskRequirement).one().requirement_id == "leaf"
            assert db.query(SddRequirementAuditLog).one().source_metadata_json["created_from"] == "task_closeout"
        detail = client.get(f"/api/workspaces/{workspace.id}/workspace-assets/requirements/leaf").json()
        assert detail["linked_tasks"][0]["task_id"] == task.id
    finally:
        engine.dispose()
