import os
import sys
from contextlib import contextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.database import Base  # noqa: E402

# Import all model modules so SQLAlchemy mappers initialize correctly
import app.domains.api_mock.models.api_mock  # noqa: F401
import app.domains.task.models.test_result  # noqa: F401

from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.asset.models.asset import AssetType, SddAsset
from app.domains.auth.models.user import (
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.workspace_asset.models.workspace_asset import (
    AiOutputType,
    ClarificationStatus,
    DecisionStatus,
    EvidenceSourceType,
    EvidenceStatus,
    HumanDeltaStatus,
    HumanReviewStatus,
    KnowledgeAssetStatus,
    KnowledgeAssetType,
    RequirementStatus,
    SddAiOutput,
    SddClarification,
    SddDecision,
    SddEvidence,
    SddHumanDelta,
    SddHumanReview,
    SddKnowledgeAsset,
    SddRequirement,
    SddTaskRequirement,
    TaskRequirementRelationType,
)
from app.domains.workspace_asset.routers import workspace_asset as workspace_asset_router
from app.domains.workspace_asset.services import workspace_asset_service  # noqa: E402


def _build_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, SessionLocal


@contextmanager
def _session(SessionLocal):
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _seed_workspace(db, workspace_id="ws-1", task_id="task-1"):
    user = User(id="user-1", email="user@example.com", hashed_password="x", display_name="User")
    workspace = Workspace(id=workspace_id, name="Workspace", owner_id=user.id, project_path="G:/repo")
    member = WorkspaceMember(
        id=f"member-{workspace_id}",
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.OWNER,
        permissions_json="[]",
        is_expert=True,
    )
    task = SddTask(
        id=task_id,
        workspace_id=workspace.id,
        creator_id=user.id,
        name="Implement checkout",
        description="Task process boundary",
        project_path="G:/repo",
        status=TaskStatus.PLANNING,
    )
    db.add_all([user, workspace, member, task])
    db.commit()
    return user, workspace, task


def test_workspace_asset_models_express_minimum_domain_boundaries():
    engine, SessionLocal = _build_db()
    try:
        assert "sdd_requirements" in Base.metadata.tables
        assert "sdd_evidence" in Base.metadata.tables
        assert "sdd_knowledge_assets" in Base.metadata.tables
        assert "sdd_traceability" not in Base.metadata.tables

        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db)
            requirement = SddRequirement(
                id="req-1",
                workspace_id=workspace.id,
                created_by_id=user.id,
                title="Checkout must validate payment state",
                status=RequirementStatus.ACTIVE,
                source_kind="manual",
                source_ref="REQ-1",
            )
            link = SddTaskRequirement(
                id="link-1",
                workspace_id=workspace.id,
                requirement_id=requirement.id,
                task_id=task.id,
                relation_type=TaskRequirementRelationType.COVERS,
                created_by_id=user.id,
            )
            spec_asset = SddAsset(
                id="spec-1",
                workspace_id=workspace.id,
                task_id=task.id,
                creator_id=user.id,
                asset_type=AssetType.SPEC,
                name="Checkout validation spec",
                content_text="Validate payment state before checkout completion.",
                content_json={
                    "requirement_understanding": "Payment state must be validated.",
                    "acceptance_criteria": ["Reject invalid payment state."],
                },
            )
            plan_asset = SddAsset(
                id="plan-1",
                workspace_id=workspace.id,
                task_id=task.id,
                creator_id=user.id,
                asset_type=AssetType.PLAN,
                name="Checkout implementation plan",
                content_text="Update checkout service and run unit tests.",
                content_json={
                    "implementation_steps": ["Update checkout service."],
                    "verification_methods": ["Run payment-state tests."],
                },
            )
            ai_job = SddAiJob(
                id="job-1",
                workspace_id=workspace.id,
                task_id=task.id,
                channel=AiJobChannel.TASK_CHAT,
                queue_key="task:task-1",
                status=AiJobStatus.SUCCESS,
                progress=100,
                prompt_text="Implement checkout validation for payment state.",
                result_json={"output_summary": "Proposed checkout validation patch."},
                creator_id=user.id,
            )
            ai_output = SddAiOutput(
                id="output-1",
                workspace_id=workspace.id,
                task_id=task.id,
                ai_job_id=ai_job.id,
                output_type=AiOutputType.PATCH,
                title="AI patch proposal",
            )
            review = SddHumanReview(
                id="review-1",
                workspace_id=workspace.id,
                task_id=task.id,
                reviewer_id=user.id,
                status=HumanReviewStatus.RESOLVED,
                title="Manual review",
            )
            delta = SddHumanDelta(
                id="delta-1",
                workspace_id=workspace.id,
                task_id=task.id,
                ai_output_id=ai_output.id,
                review_id=review.id,
                created_by_id=user.id,
                status=HumanDeltaStatus.CONFIRMED,
                title="Manual final adjustment",
                diff_ref_json={"path": "src/checkout.ts"},
            )
            evidence = SddEvidence(
                id="evidence-1",
                workspace_id=workspace.id,
                requirement_id=requirement.id,
                task_id=task.id,
                ai_job_id=ai_job.id,
                human_delta_id=delta.id,
                created_by_id=user.id,
                status=EvidenceStatus.CONFIRMED,
                source_type=EvidenceSourceType.COMMIT,
                source_uri="https://example.com/repo/commit/abc123",
                source_ref="abc123",
                title="Commit abc123",
            )
            knowledge = SddKnowledgeAsset(
                id="knowledge-1",
                workspace_id=workspace.id,
                promoted_by_id=user.id,
                source_task_id=task.id,
                source_human_delta_id=delta.id,
                source_evidence_id=evidence.id,
                asset_type=KnowledgeAssetType.FRAMEWORK_PATTERN,
                status=KnowledgeAssetStatus.DRAFT,
                title="Checkout validation pattern",
            )
            db.add_all([requirement, link, spec_asset, plan_asset, ai_job, ai_output, review, delta, evidence, knowledge])
            db.commit()

            detail = workspace_asset_service.get_task_detail(db, workspace.id, task.id)
            assert detail is not None
            assert detail.task.requirement_count == 1
            assert detail.task.coverage_status == "waiting_human_confirmation"
            assert detail.process_summary.risk_status == "not_available"
            assert detail.requirement_links[0].relation_type == "COVERS"
            assert detail.evidence[0].source.source_type == "COMMIT"
            assert detail.evidence[0].source.source_ref == "abc123"
            assert detail.human_deltas[0].ai_output_id == "output-1"
            assert detail.human_deltas[0].review_id == "review-1"
            assert detail.specs[0].content_text == "Validate payment state before checkout completion."
            assert detail.specs[0].content_json["requirement_understanding"] == "Payment state must be validated."
            assert detail.plans[0].content_json["implementation_steps"] == ["Update checkout service."]
            assert detail.ai_runs[0].input_summary == "Implement checkout validation for payment state."
            assert detail.ai_runs[0].output_summary == "Proposed checkout validation patch."
            assert detail.ai_runs[0].adoption_status == "not_available"

            requirements_response = workspace_asset_service.list_requirements(db, workspace.id)
            linked_task = requirements_response.items[0].linked_tasks[0]
            assert linked_task.task_id == task.id
            assert linked_task.relation_type == "COVERS"
            assert linked_task.coverage_status == "waiting_human_confirmation"

            client = TestClient(_build_app(SessionLocal, user))
            requirements_api = client.get("/api/workspaces/ws-1/workspace-assets/requirements")
            assert requirements_api.status_code == 200
            api_linked_task = requirements_api.json()["items"][0]["linked_tasks"][0]
            assert api_linked_task["task_id"] == task.id
            assert api_linked_task["relation_type"] == "COVERS"
            assert api_linked_task["coverage_status"] == "waiting_human_confirmation"

            traceability = workspace_asset_service.get_traceability(db, workspace.id)
            view_totals = {view.key: view.total for view in traceability.views}
            assert view_totals["spec_coverage_matrix"] == 1
            assert view_totals["evidence_registry"] == 1
            assert view_totals["human_delta_dashboard"] == 1
            assert view_totals["risk_board"] == 0
            matrix = next(view for view in traceability.views if view.key == "spec_coverage_matrix")
            matrix_row = matrix.items[0]
            assert matrix_row["requirement_id"] == requirement.id
            assert matrix_row["requirement_title"] == requirement.title
            assert matrix_row["task_id"] == task.id
            assert matrix_row["task_name"] == task.name
            assert matrix_row["spec_status"] == "available"
            assert matrix_row["plan_status"] == "available"
            assert matrix_row["ai_run_status"] == "available"
            assert matrix_row["human_review_status"] == "available"
            assert matrix_row["human_delta_status"] == "available"
            assert matrix_row["evidence_status"] == "available"
            assert matrix_row["coverage_status"] == "human_modified"
            assert matrix_row["trace_refs"]["human_delta_ids"] == ["delta-1"]

            knowledge_response = workspace_asset_service.list_knowledge_assets(db, workspace.id)
            assert knowledge_response.total == 1
            assert knowledge_response.items[0].source_human_delta_id == "delta-1"
    finally:
        engine.dispose()


def _build_app(SessionLocal, user):
    def _override_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(workspace_asset_router.router, prefix="/api")
    app.dependency_overrides[workspace_asset_router.get_db] = _override_db
    app.dependency_overrides[workspace_asset_router.get_current_user] = lambda: user
    return app


def test_spec_coverage_matrix_derives_conservative_statuses():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, _task = _seed_workspace(db, workspace_id="ws-matrix", task_id="task-human-delta")

            requirements = [
                SddRequirement(
                    id="req-missing",
                    workspace_id=workspace.id,
                    created_by_id=user.id,
                    title="Requirement without task",
                    status=RequirementStatus.ACTIVE,
                ),
                SddRequirement(
                    id="req-spec",
                    workspace_id=workspace.id,
                    created_by_id=user.id,
                    title="Requirement with spec",
                    status=RequirementStatus.ACTIVE,
                ),
                SddRequirement(
                    id="req-evidence-missing",
                    workspace_id=workspace.id,
                    created_by_id=user.id,
                    title="Requirement waiting evidence",
                    status=RequirementStatus.ACTIVE,
                ),
                SddRequirement(
                    id="req-clarification",
                    workspace_id=workspace.id,
                    created_by_id=user.id,
                    title="Requirement needing clarification",
                    status=RequirementStatus.ACTIVE,
                ),
                SddRequirement(
                    id="req-rejected",
                    workspace_id=workspace.id,
                    created_by_id=user.id,
                    title="Requirement rejected by decision",
                    status=RequirementStatus.ACTIVE,
                ),
                SddRequirement(
                    id="req-verified",
                    workspace_id=workspace.id,
                    created_by_id=user.id,
                    title="Requirement with human confirmation",
                    status=RequirementStatus.ACTIVE,
                ),
            ]
            tasks = [
                SddTask(
                    id="task-spec",
                    workspace_id=workspace.id,
                    creator_id=user.id,
                    name="Spec only task",
                    project_path="G:/repo",
                    status=TaskStatus.PLANNING,
                ),
                SddTask(
                    id="task-evidence-missing",
                    workspace_id=workspace.id,
                    creator_id=user.id,
                    name="Plan without evidence task",
                    project_path="G:/repo",
                    status=TaskStatus.PLANNING,
                ),
                SddTask(
                    id="task-clarification",
                    workspace_id=workspace.id,
                    creator_id=user.id,
                    name="Clarification task",
                    project_path="G:/repo",
                    status=TaskStatus.PLANNING,
                ),
                SddTask(
                    id="task-rejected",
                    workspace_id=workspace.id,
                    creator_id=user.id,
                    name="Rejected task",
                    project_path="G:/repo",
                    status=TaskStatus.REVIEWING,
                ),
                SddTask(
                    id="task-verified",
                    workspace_id=workspace.id,
                    creator_id=user.id,
                    name="Verified task",
                    project_path="G:/repo",
                    status=TaskStatus.REVIEWING,
                ),
            ]
            links = [
                SddTaskRequirement(
                    id="link-human-delta",
                    workspace_id=workspace.id,
                    requirement_id="req-spec",
                    task_id="task-human-delta",
                    relation_type=TaskRequirementRelationType.COVERS,
                    created_by_id=user.id,
                ),
                SddTaskRequirement(
                    id="link-spec",
                    workspace_id=workspace.id,
                    requirement_id="req-spec",
                    task_id="task-spec",
                    relation_type=TaskRequirementRelationType.COVERS,
                    created_by_id=user.id,
                ),
                SddTaskRequirement(
                    id="link-evidence-missing",
                    workspace_id=workspace.id,
                    requirement_id="req-evidence-missing",
                    task_id="task-evidence-missing",
                    relation_type=TaskRequirementRelationType.COVERS,
                    created_by_id=user.id,
                ),
                SddTaskRequirement(
                    id="link-clarification",
                    workspace_id=workspace.id,
                    requirement_id="req-clarification",
                    task_id="task-clarification",
                    relation_type=TaskRequirementRelationType.COVERS,
                    created_by_id=user.id,
                ),
                SddTaskRequirement(
                    id="link-rejected",
                    workspace_id=workspace.id,
                    requirement_id="req-rejected",
                    task_id="task-rejected",
                    relation_type=TaskRequirementRelationType.COVERS,
                    created_by_id=user.id,
                ),
                SddTaskRequirement(
                    id="link-verified",
                    workspace_id=workspace.id,
                    requirement_id="req-verified",
                    task_id="task-verified",
                    relation_type=TaskRequirementRelationType.COVERS,
                    created_by_id=user.id,
                ),
            ]
            spec_asset = SddAsset(
                id="matrix-spec-asset",
                workspace_id=workspace.id,
                task_id="task-spec",
                creator_id=user.id,
                asset_type=AssetType.SPEC,
                name="Spec asset",
            )
            plan_asset = SddAsset(
                id="matrix-plan-asset",
                workspace_id=workspace.id,
                task_id="task-evidence-missing",
                creator_id=user.id,
                asset_type=AssetType.PLAN,
                name="Plan asset",
            )
            delta = SddHumanDelta(
                id="matrix-delta",
                workspace_id=workspace.id,
                task_id="task-human-delta",
                created_by_id=user.id,
                status=HumanDeltaStatus.CONFIRMED,
                title="Human modified implementation",
            )
            clarification = SddClarification(
                id="matrix-clarification",
                workspace_id=workspace.id,
                task_id="task-clarification",
                status=ClarificationStatus.OPEN,
                question="Which payment states are valid?",
            )
            decision = SddDecision(
                id="matrix-decision",
                workspace_id=workspace.id,
                task_id="task-rejected",
                status=DecisionStatus.REJECTED,
                title="Reject current approach",
            )
            ordinary_evidence = SddEvidence(
                id="matrix-ordinary-evidence",
                workspace_id=workspace.id,
                requirement_id="req-rejected",
                task_id="task-rejected",
                status=EvidenceStatus.CONFIRMED,
                source_type=EvidenceSourceType.COMMIT,
                source_uri="https://example.com/commit/rejected",
            )
            human_confirmation = SddEvidence(
                id="matrix-human-confirmation",
                workspace_id=workspace.id,
                requirement_id="req-verified",
                task_id="task-verified",
                created_by_id=user.id,
                confirmed_by_id=user.id,
                status=EvidenceStatus.CONFIRMED,
                source_type=EvidenceSourceType.HUMAN_CONFIRMATION,
                source_ref="manual-confirmation-1",
                confirmed_at=datetime.utcnow(),
            )
            db.add_all([
                *requirements,
                *tasks,
                *links,
                spec_asset,
                plan_asset,
                delta,
                clarification,
                decision,
                ordinary_evidence,
                human_confirmation,
            ])
            db.commit()

            traceability = workspace_asset_service.get_traceability(db, workspace.id)
            matrix = next(view for view in traceability.views if view.key == "spec_coverage_matrix")
            rows = {item["id"]: item for item in matrix.items}

            assert rows["req-missing:no-task"]["coverage_status"] == "missing"
            assert rows["req-spec:task-spec"]["coverage_status"] == "spec_covered"
            assert rows["req-evidence-missing:task-evidence-missing"]["coverage_status"] == "evidence_missing"
            assert rows["req-clarification:task-clarification"]["coverage_status"] == "need_clarification"
            assert rows["req-rejected:task-rejected"]["coverage_status"] == "rejected"
            assert rows["req-rejected:task-rejected"]["coverage_status"] != "verified"
            assert rows["req-verified:task-verified"]["coverage_status"] == "verified"
            assert rows["req-spec:task-human-delta"]["coverage_status"] == "human_modified"
            assert rows["req-spec:task-human-delta"]["trace_refs"]["human_delta_ids"] == ["matrix-delta"]
            assert rows["req-verified:task-verified"]["trace_refs"]["evidence_ids"] == ["matrix-human-confirmation"]
    finally:
        engine.dispose()


def test_workspace_asset_read_only_api_returns_real_empty_boundaries():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, _task = _seed_workspace(db, workspace_id="ws-empty", task_id="task-empty")
            db.query(SddTask).filter(SddTask.id == "task-empty").delete()
            db.commit()

        client = TestClient(_build_app(SessionLocal, user))

        overview = client.get("/api/workspaces/ws-empty/workspace-assets/overview")
        assert overview.status_code == 200
        assert overview.json()["task_count"] == 0
        assert overview.json()["coverage_status"] == "not_available"

        requirements = client.get("/api/workspaces/ws-empty/workspace-assets/requirements")
        assert requirements.status_code == 200
        assert requirements.json()["total"] == 0
        assert requirements.json()["connection_status"][0]["state"] == "NOT_CONNECTED"

        tasks = client.get("/api/workspaces/ws-empty/workspace-assets/tasks")
        assert tasks.status_code == 200
        assert tasks.json()["state"]["empty"] is True

        traceability = client.get("/api/workspaces/ws-empty/workspace-assets/traceability")
        assert traceability.status_code == 200
        assert {view["key"] for view in traceability.json()["views"]} == {
            "spec_coverage_matrix",
            "evidence_registry",
            "human_delta_dashboard",
            "risk_board",
        }
    finally:
        engine.dispose()

def test_workspace_asset_tasks_pagination_and_filtering():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, _task = _seed_workspace(db, workspace_id="ws-tasks", task_id="task-1")
            tasks = [
                SddTask(
                    id=f"task-multi-{i}",
                    workspace_id=workspace.id,
                    creator_id=user.id,
                    name=f"Filterable task {i}",
                    project_path="G:/repo",
                    status=TaskStatus.DONE if i % 2 == 0 else TaskStatus.PLANNING,
                    current_phase="CODING" if i % 2 == 0 else "TESTING"
                )
                for i in range(5)
            ]
            db.add_all(tasks)
            db.commit()

        client = TestClient(_build_app(SessionLocal, user))

        res1 = client.get("/api/workspaces/ws-tasks/workspace-assets/tasks?page=1&page_size=2")
        assert res1.status_code == 200
        assert len(res1.json()["items"]) == 2
        assert res1.json()["total"] == 6  # 5 + 1 from seed
        assert res1.json()["page"] == 1

        res2 = client.get("/api/workspaces/ws-tasks/workspace-assets/tasks?status=DONE")
        assert res2.status_code == 200
        assert all(item["status"] == "DONE" for item in res2.json()["items"])

        res3 = client.get("/api/workspaces/ws-tasks/workspace-assets/tasks?q=Filterable task")
        assert res3.status_code == 200
        assert len(res3.json()["items"]) == 5
    finally:
        engine.dispose()

