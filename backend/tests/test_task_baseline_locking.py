import os
import sys
from datetime import datetime

from fastapi.testclient import TestClient


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.dirname(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

from app.domains.task.models.task import SddTask, TaskStatus  # noqa: E402
from app.domains.workspace_asset.models.workspace_asset import (  # noqa: E402
    EvidenceSourceType,
    EvidenceStatus,
    EvidenceType,
    HumanReviewOutcome,
    HumanReviewStatus,
    RequirementStatus,
    SddEvidence,
    SddHumanReview,
    SddRequirement,
    SddTaskBaseline,
    SddTaskFinalSummary,
    SddTaskRequirement,
    TaskFinalStatus,
    TaskRequirementRelationType,
)
from test_workspace_asset_boundary import _build_app, _build_db, _seed_workspace, _session  # noqa: E402


def _seed_baselined_task(db, workspace_id: str, task_id: str):
    user, workspace, task = _seed_workspace(db, workspace_id=workspace_id, task_id=task_id)
    task.status = TaskStatus.BASELINED
    task.baseline_version = 1
    requirement = SddRequirement(
        id=f"req-{task_id}",
        workspace_id=workspace.id,
        created_by_id=user.id,
        title="Frozen requirement",
        status=RequirementStatus.ACTIVE,
    )
    link = SddTaskRequirement(
        id=f"link-{task_id}",
        workspace_id=workspace.id,
        requirement_id=requirement.id,
        task_id=task.id,
        relation_type=TaskRequirementRelationType.COVERS,
        created_by_id=user.id,
    )
    review = SddHumanReview(
        id=f"review-{task_id}",
        workspace_id=workspace.id,
        task_id=task.id,
        reviewer_id=user.id,
        status=HumanReviewStatus.CLOSED,
        outcome=HumanReviewOutcome.ACCEPT,
        title="Accepted expert review",
        review_type="EXPERT_FINAL_REVIEW",
    )
    evidence = SddEvidence(
        id=f"evidence-{task_id}",
        workspace_id=workspace.id,
        task_id=task.id,
        requirement_id=requirement.id,
        created_by_id=user.id,
        confirmed_by_id=user.id,
        confirmed_at=datetime.utcnow(),
        status=EvidenceStatus.CONFIRMED,
        evidence_type=EvidenceType.BUSINESS,
        source_type=EvidenceSourceType.HUMAN_CONFIRMATION,
        source_ref="manual-confirmation",
        title="Manual confirmation",
    )
    summary = SddTaskFinalSummary(
        id=f"summary-{task_id}",
        workspace_id=workspace.id,
        task_id=task.id,
        author_id=user.id,
        final_status=TaskFinalStatus.VERIFIED,
        summary="Verified before freeze.",
        final_evidence_ids_json=[evidence.id],
        human_confirmation_review_id=review.id,
    )
    snapshot = {
        "version": 1,
        "task": {"id": task.id, "status": "DONE"},
        "summary": {"id": summary.id, "final_status": "VERIFIED"},
        "evidence_ids": [evidence.id],
        "review_ids": [review.id],
    }
    baseline = SddTaskBaseline(
        id=f"baseline-{task_id}",
        workspace_id=workspace.id,
        task_id=task.id,
        summary_id=summary.id,
        version=1,
        snapshot_json=snapshot,
        baselined_by_id=user.id,
    )
    task.final_summary = summary
    task.baseline_snapshot_json = snapshot
    db.add_all([requirement, link, review, evidence, summary, baseline])
    db.commit()
    return user, workspace, task, requirement


def test_baselined_task_blocks_writes_but_allows_final_workflow_reads():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, _workspace, _task, requirement = _seed_baselined_task(
                db,
                workspace_id="ws-baseline-lock",
                task_id="task-baseline-lock",
            )

        client = TestClient(_build_app(SessionLocal, user))

        workflow = client.get(
            "/api/workspaces/ws-baseline-lock/workspace-assets/tasks/task-baseline-lock/final-workflow"
        )
        assert workflow.status_code == 200, workflow.text
        body = workflow.json()
        assert body["readonly"] is True
        assert body["task"]["status"] == "BASELINED"
        assert body["baseline"]["version"] == 1
        assert body["available_actions"] == []

        evidence_write = client.post(
            "/api/workspaces/ws-baseline-lock/workspace-assets/tasks/task-baseline-lock/evidence",
            json={
                "requirement_id": requirement.id,
                "evidence_type": "CODE",
                "source_type": "COMMIT",
                "source_uri": "https://example.com/commit/locked",
                "title": "Should be locked",
            },
        )
        assert evidence_write.status_code == 403
        assert "baselined" in evidence_write.json()["detail"].lower()

        workflow_write = client.post(
            "/api/workspaces/ws-baseline-lock/workspace-assets/tasks/task-baseline-lock/final-workflow/clarifications",
            json={
                "question": "Can this frozen task be changed?",
                "blocking_level": "BLOCKING",
            },
        )
        assert workflow_write.status_code == 403
        assert "baselined" in workflow_write.json()["detail"].lower()

        summary_write = client.put(
            "/api/workspaces/ws-baseline-lock/workspace-assets/tasks/task-baseline-lock/final-summary",
            json={
                "final_status": "PARTIAL",
                "summary": "Attempt to mutate frozen summary.",
            },
        )
        assert summary_write.status_code == 403
        assert "baselined" in summary_write.json()["detail"].lower()

        detail = client.get("/api/workspaces/ws-baseline-lock/workspace-assets/tasks/task-baseline-lock")
        assert detail.status_code == 200, detail.text
        assert detail.json()["task"]["status"] == "BASELINED"
    finally:
        engine.dispose()
