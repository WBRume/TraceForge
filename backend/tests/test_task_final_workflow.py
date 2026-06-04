import os
import sys

from fastapi.testclient import TestClient


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.dirname(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob  # noqa: E402
from app.domains.asset.models.asset import AssetType, SddAsset  # noqa: E402
from app.domains.task.models.task import SddTask, TaskStatus  # noqa: E402
from app.domains.workspace_asset.models.workspace_asset import (  # noqa: E402
    AiOutputType,
    DecisionStatus,
    EvidenceSourceType,
    EvidenceStatus,
    EvidenceType,
    HumanDeltaStatus,
    HumanReviewStatus,
    RequirementStatus,
    SddAiOutput,
    SddClarification,
    SddDecision,
    SddEvidence,
    SddHumanDelta,
    SddHumanReview,
    SddRequirement,
    SddReviewClarificationLink,
    SddTaskBaseline,
    SddTaskRequirement,
    TaskRequirementRelationType,
)
from test_workspace_asset_boundary import _build_app, _build_db, _seed_workspace, _session  # noqa: E402


def _seed_done_task_with_requirement(db, workspace_id: str, task_id: str):
    user, workspace, task = _seed_workspace(db, workspace_id=workspace_id, task_id=task_id)
    task.status = TaskStatus.DONE
    requirement = SddRequirement(
        id=f"req-{task_id}",
        workspace_id=workspace.id,
        created_by_id=user.id,
        title="Final workflow requirement",
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
    db.add_all([requirement, link])
    db.commit()
    return user, workspace, task, requirement


def _create_human_confirmation_evidence(client: TestClient, workspace_id: str, task_id: str, requirement_id: str) -> str:
    response = client.post(
        f"/api/workspaces/{workspace_id}/workspace-assets/tasks/{task_id}/evidence",
        json={
            "requirement_id": requirement_id,
            "evidence_type": "BUSINESS",
            "source_type": "HUMAN_CONFIRMATION",
            "source_ref": "manual-confirmation",
            "title": "Manual confirmation",
            "confirmed": True,
        },
    )
    assert response.status_code == 201, response.text
    evidence = client.get(f"/api/workspaces/{workspace_id}/workspace-assets/tasks/{task_id}/evidence")
    assert evidence.status_code == 200, evidence.text
    return evidence.json()["items"][0]["id"]


def _seed_preview_targets(db, workspace_id: str, task_id: str):
    user, workspace, task, requirement = _seed_done_task_with_requirement(db, workspace_id, task_id)
    spec = SddAsset(
        id=f"spec-{task_id}",
        workspace_id=workspace.id,
        task_id=task.id,
        creator_id=user.id,
        asset_type=AssetType.SPEC,
        name="Final owner spec",
        content_text="Owner-facing final state spec.",
        content_json={"acceptance": ["Owner can clarify concrete content."]},
    )
    plan = SddAsset(
        id=f"plan-{task_id}",
        workspace_id=workspace.id,
        task_id=task.id,
        creator_id=user.id,
        asset_type=AssetType.PLAN,
        name="Final owner plan",
        content_text="Review clarification context before baseline.",
        content_json={"steps": ["Open clarification context."]},
    )
    task_file = SddAsset(
        id=f"task-file-{task_id}",
        workspace_id=workspace.id,
        task_id=task.id,
        creator_id=user.id,
        asset_type=AssetType.ERROR_STACK,
        name="Runtime note",
        content_text="Runtime note for the task owner.",
        source_file_name="runtime.log",
    )
    diff_asset = SddAsset(
        id=f"diff-{task_id}",
        workspace_id=workspace.id,
        task_id=task.id,
        creator_id=user.id,
        asset_type=AssetType.CODE_DIFF,
        name="Human delta diff",
        content_text="diff --git a/src/checkout.ts b/src/checkout.ts\n+owner change\n-old change\n",
        content_json={
            "file_diffs": [
                {
                    "file_path": "src/checkout.ts",
                    "change_type": "modified",
                    "insertions": 1,
                    "deletions": 1,
                    "hunks": [],
                    "comparison_type": "human_only",
                }
            ]
        },
    )
    ai_job = SddAiJob(
        id=f"job-{task_id}",
        workspace_id=workspace.id,
        task_id=task.id,
        channel=AiJobChannel.TASK_CHAT,
        queue_key=f"task:{task.id}",
        status=AiJobStatus.SUCCESS,
        progress=100,
        prompt_text="Create final state context.",
        creator_id=user.id,
    )
    ai_output = SddAiOutput(
        id=f"ai-output-{task_id}",
        workspace_id=workspace.id,
        task_id=task.id,
        ai_job_id=ai_job.id,
        output_type=AiOutputType.PATCH,
        title="AI patch proposal",
        content_text="AI changed checkout validation.",
        content_json={"files": ["src/checkout.ts"]},
    )
    evidence = SddEvidence(
        id=f"evidence-{task_id}",
        workspace_id=workspace.id,
        task_id=task.id,
        requirement_id=requirement.id,
        created_by_id=user.id,
        confirmed_by_id=user.id,
        status=EvidenceStatus.CONFIRMED,
        evidence_type=EvidenceType.BUSINESS,
        source_type=EvidenceSourceType.HUMAN_CONFIRMATION,
        source_ref="manual-confirmation",
        title="Manual confirmation",
        summary="Owner confirmed the final state.",
    )
    delta = SddHumanDelta(
        id=f"delta-{task_id}",
        workspace_id=workspace.id,
        task_id=task.id,
        created_by_id=user.id,
        status=HumanDeltaStatus.READY,
        diff_asset_id=diff_asset.id,
        changed_files_count=1,
        insertions=1,
        deletions=1,
        comparison_summary="Owner adjusted checkout validation after AI.",
        change_category="Human adjustment",
    )
    decision = SddDecision(
        id=f"decision-{task_id}",
        workspace_id=workspace.id,
        task_id=task.id,
        requirement_id=requirement.id,
        status=DecisionStatus.ACCEPTED,
        title="Keep owner change",
        body="The owner change is part of the final state.",
        rationale="It resolves the final checkout ambiguity.",
        impact_scope="checkout",
        source_evidence_id=evidence.id,
    )
    other_task = SddTask(
        id=f"other-{task_id}",
        workspace_id=workspace.id,
        creator_id=user.id,
        name="Other task",
        description="Not the preview task",
        project_path="G:/repo",
        status=TaskStatus.DONE,
    )
    other_evidence = SddEvidence(
        id=f"other-evidence-{task_id}",
        workspace_id=workspace.id,
        task_id=other_task.id,
        created_by_id=user.id,
        status=EvidenceStatus.CONFIRMED,
        evidence_type=EvidenceType.BUSINESS,
        source_type=EvidenceSourceType.HUMAN_CONFIRMATION,
        title="Other task evidence",
    )
    db.add_all([
        spec,
        plan,
        task_file,
        diff_asset,
        ai_job,
        ai_output,
        evidence,
        delta,
        decision,
        other_task,
        other_evidence,
    ])
    db.commit()
    return user, {
        "SPEC": spec.id,
        "PLAN": plan.id,
        "AI_CHANGE": ai_output.id,
        "HUMAN_DELTA": delta.id,
        "EVIDENCE": evidence.id,
        "DECISION": decision.id,
        "TASK_FILE": task_file.id,
        "OTHER_EVIDENCE": other_evidence.id,
    }


def test_final_workflow_review_target_preview_reads_each_target_type_and_respects_task_boundary():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, target_ids = _seed_preview_targets(db, "ws-preview", "task-preview")

        client = TestClient(_build_app(SessionLocal, user))
        for target_type in ("SPEC", "PLAN", "AI_CHANGE", "HUMAN_DELTA", "EVIDENCE", "DECISION", "TASK_FILE"):
            response = client.get(
                f"/api/workspaces/ws-preview/workspace-assets/tasks/task-preview/final-workflow/review-targets/{target_type}/{target_ids[target_type]}/preview"
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["target"]["target_type"] == target_type
            assert body["target"]["target_id"] == target_ids[target_type]
            assert body["title"]
            assert body["metadata"]

        delta_response = client.get(
            f"/api/workspaces/ws-preview/workspace-assets/tasks/task-preview/final-workflow/review-targets/HUMAN_DELTA/{target_ids['HUMAN_DELTA']}/preview"
        )
        delta_body = delta_response.json()
        diff_block = next(block for block in delta_body["blocks"] if block["kind"] == "file_diffs")
        assert diff_block["file_diffs"][0]["file_path"] == "src/checkout.ts"
        assert "owner change" in diff_block["diff_text"]

        wrong_task = client.get(
            f"/api/workspaces/ws-preview/workspace-assets/tasks/task-preview/final-workflow/review-targets/EVIDENCE/{target_ids['OTHER_EVIDENCE']}/preview"
        )
        assert wrong_task.status_code == 404

        bad_type = client.get(
            "/api/workspaces/ws-preview/workspace-assets/tasks/task-preview/final-workflow/review-targets/BAD_TYPE/anything/preview"
        )
        assert bad_type.status_code == 422

        with _session(SessionLocal) as db:
            task = db.get(SddTask, "task-preview")
            task.status = TaskStatus.BASELINED
            task.baseline_version = 1
            db.commit()

        frozen_read = client.get(
            f"/api/workspaces/ws-preview/workspace-assets/tasks/task-preview/final-workflow/review-targets/HUMAN_DELTA/{target_ids['HUMAN_DELTA']}/preview"
        )
        assert frozen_read.status_code == 200, frozen_read.text
    finally:
        engine.dispose()


def test_final_workflow_uses_multiple_review_items_and_message_driven_clarification():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, _workspace, _task, requirement = _seed_done_task_with_requirement(
                db,
                workspace_id="ws-final-workflow",
                task_id="task-final-workflow",
            )

        client = TestClient(_build_app(SessionLocal, user))
        evidence_id = _create_human_confirmation_evidence(
            client,
            "ws-final-workflow",
            "task-final-workflow",
            requirement.id,
        )

        workflow = client.get(
            "/api/workspaces/ws-final-workflow/workspace-assets/tasks/task-final-workflow/final-workflow"
        )
        assert workflow.status_code == 200, workflow.text
        body = workflow.json()
        assert body["task"]["status"] == "DONE"
        assert body["task"]["coverage_status"] == "verified"
        assert body["can_write_final_workflow"] is True
        assert body["can_resolve_clarification"] is True
        assert [step["key"] for step in body["steps"]] == [
            "expert_review",
            "clarification",
            "final_summary",
            "baseline",
        ]
        assert len(body["reviews"]) == 1
        assert body["reviews"][0]["review_type"] == "EXPERT_FINAL_REVIEW"
        assert body["reviews"][0]["derived_status"] == "CLEAR"
        assert body["review_targets"]["EVIDENCE"][0]["target_id"] == evidence_id
        seed_review_id = body["reviews"][0]["id"]

        second_review = client.post(
            "/api/workspaces/ws-final-workflow/workspace-assets/tasks/task-final-workflow/final-workflow/reviews",
            json={
                "title": "Evidence and delta review",
                "body": "Check final evidence against delivery expectations.",
                "priority": "HIGH",
                "target_refs": [
                    {
                        "target_type": "EVIDENCE",
                        "target_id": evidence_id,
                        "label": "Manual confirmation",
                    }
                ],
            },
        )
        assert second_review.status_code == 201, second_review.text
        body = second_review.json()
        assert len(body["reviews"]) == 2
        review = next(item for item in body["reviews"] if item["title"] == "Evidence and delta review")
        review_id = review["id"]
        assert review["target_refs"][0]["target_type"] == "EVIDENCE"
        assert review["derived_status"] == "WAITING_ANSWER"
        assert len(body["clarifications"]) == 1
        clarification_id = body["clarifications"][0]["id"]
        assert body["clarifications"][0]["source_review_id"] == review_id
        assert body["clarifications"][0]["status"] == "OPEN"
        assert body["clarifications"][0]["question"] == "Evidence and delta review\n\nCheck final evidence against delivery expectations."
        assert len(body["clarification_threads"][clarification_id]) == 1

        old_start = client.post(
            f"/api/workspaces/ws-final-workflow/workspace-assets/tasks/task-final-workflow/final-workflow/reviews/{review_id}/start"
        )
        assert old_start.status_code == 404
        old_outcome = client.post(
            f"/api/workspaces/ws-final-workflow/workspace-assets/tasks/task-final-workflow/final-workflow/reviews/{review_id}/submit-outcome",
            json={"outcome": "ACCEPT"},
        )
        assert old_outcome.status_code == 404

        answered = client.post(
            f"/api/workspaces/ws-final-workflow/workspace-assets/tasks/task-final-workflow/final-workflow/clarifications/{clarification_id}/messages",
            json={
                "entry_type": "ANSWER",
                "body": "Owner workflow is the only final-state flow for v1.",
                "change_reason": "Human answered expert clarification.",
            },
        )
        assert answered.status_code == 201, answered.text
        answered_body = answered.json()
        assert answered_body["clarifications"][0]["status"] == "ANSWERED"
        review_after_answer = next(item for item in answered_body["reviews"] if item["id"] == review_id)
        assert review_after_answer["derived_status"] == "ANSWERED_REVIEWING"
        assert len(answered_body["clarification_threads"][clarification_id]) == 2

        blocked_verify = client.put(
            "/api/workspaces/ws-final-workflow/workspace-assets/tasks/task-final-workflow/final-workflow/final-summary",
            json={
                "final_status": "VERIFIED",
                "summary": "Should still be blocked because the answer is not confirmed.",
                "final_evidence_ids": [evidence_id],
            },
        )
        assert blocked_verify.status_code == 409

        old_accept = client.post(
            f"/api/workspaces/ws-final-workflow/workspace-assets/tasks/task-final-workflow/final-workflow/clarifications/{clarification_id}/accept",
            json={},
        )
        assert old_accept.status_code == 404
        old_reject = client.post(
            f"/api/workspaces/ws-final-workflow/workspace-assets/tasks/task-final-workflow/final-workflow/clarifications/{clarification_id}/reject",
            json={},
        )
        assert old_reject.status_code == 404

        confirmed = client.post(
            f"/api/workspaces/ws-final-workflow/workspace-assets/tasks/task-final-workflow/final-workflow/clarifications/{clarification_id}/messages",
            json={
                "entry_type": "CONFIRM_RESOLUTION",
                "body": "Answer confirmed for final workflow.",
                "change_reason": "Expert confirmed clarification resolution.",
            },
        )
        assert confirmed.status_code == 201, confirmed.text
        confirmed_body = confirmed.json()
        assert confirmed_body["clarifications"][0]["status"] == "ACCEPTED"
        review_after_confirm = next(item for item in confirmed_body["reviews"] if item["id"] == review_id)
        assert review_after_confirm["derived_status"] == "CLEAR"

        verified = client.put(
            "/api/workspaces/ws-final-workflow/workspace-assets/tasks/task-final-workflow/final-workflow/final-summary",
            json={
                "final_status": "VERIFIED",
                "summary": "Final state verified with expert review and confirmed clarification.",
                "remaining_risk": "Decision completeness is advisory in v1.",
                "next_steps": "Use baseline snapshot for future read-only review.",
                "final_evidence_ids": [evidence_id],
                "human_confirmation_review_id": seed_review_id,
                "review_checklist": {"expert_review": "clear"},
                "clarification_summary": {"blocking": "confirmed"},
                "delta_summary": {"human_delta_count": 0},
                "decision_summary": {"decision_count": 0, "hard_blocking": False},
                "change_reason": "Final summary verified.",
            },
        )
        assert verified.status_code == 200, verified.text
        verified_body = verified.json()
        assert verified_body["readonly"] is True
        assert verified_body["task"]["status"] == "BASELINED"
        assert verified_body["task"]["baseline_version"] == 1
        assert verified_body["final_summary"]["final_status"] == "VERIFIED"
        assert verified_body["baseline"]["version"] == 1
        assert {item["derived_status"] for item in verified_body["reviews"]} == {"CLOSED"}
        assert all(item["status"] != "block" for item in verified_body["checklist"])

        with _session(SessionLocal) as db:
            task = db.get(SddTask, "task-final-workflow")
            review = db.get(SddHumanReview, review_id)
            clarification_row = db.get(SddClarification, clarification_id)
            baseline = db.query(SddTaskBaseline).filter(SddTaskBaseline.task_id == task.id).one()
            link_count = (
                db.query(SddReviewClarificationLink)
                .filter(
                    SddReviewClarificationLink.review_id == review_id,
                    SddReviewClarificationLink.clarification_id == clarification_id,
                )
                .count()
            )
            assert task.status == TaskStatus.BASELINED
            assert task.baseline_version == 1
            assert review.status == HumanReviewStatus.CLOSED
            assert clarification_row.status.value == "ACCEPTED"
            assert baseline.snapshot_json["summary"]["id"] == task.final_summary.id
            assert link_count == 1
    finally:
        engine.dispose()
