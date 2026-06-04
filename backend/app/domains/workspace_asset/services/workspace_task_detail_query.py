"""
Lightweight Task Detail summary query service.

Provides a fast summary endpoint that avoids loading full sub-table entities.
All counts use database COUNT queries instead of len() on loaded collections.
"""

from __future__ import annotations

from typing import Any, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.domains.ai.models.ai_job import SddAiJob
from app.domains.asset.models.asset import AssetType, SddAsset
from app.domains.auth.models.user import User
from app.domains.task.models.task import SddPlanNode, SddTask
from app.domains.workspace_asset.models.workspace_asset import (
    EvidenceSourceType,
    EvidenceStatus,
    SddAiOutput,
    SddClarification,
    SddDecision,
    SddEvidence,
    SddHumanDelta,
    SddHumanReview,
    SddTaskFinalSummary,
    SddTaskProcessAuditLog,
    SddTaskRequirement,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    TaskDetailSummaryResponse,
    TaskProcessSummary,
    TaskRequirementLinkResponse,
    TaskSummary,
    WorkspaceAssetConnectionStatus,
)


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _count(db: Session, model: Any, workspace_id: str, **filters: Any) -> int:
    query = db.query(func.count(model.id)).filter(model.workspace_id == workspace_id)
    for field, value in filters.items():
        query = query.filter(getattr(model, field) == value)
    return int(query.scalar() or 0)


def _connection(key: str, label: str, state: str, detail: str) -> WorkspaceAssetConnectionStatus:
    return WorkspaceAssetConnectionStatus(key=key, label=label, state=state, detail=detail)


def _coverage_status_from_db(db: Session, workspace_id: str, task_id: str, requirement_count: int) -> str:
    """Compute coverage status using targeted DB queries instead of loading all evidence."""
    if requirement_count <= 0:
        return "not_available"

    # Check if there are any confirmed evidence items
    confirmed_count = (
        db.query(func.count(SddEvidence.id))
        .filter(
            SddEvidence.workspace_id == workspace_id,
            SddEvidence.task_id == task_id,
            SddEvidence.status == EvidenceStatus.CONFIRMED,
        )
        .scalar()
        or 0
    )
    if confirmed_count == 0:
        return "waiting_evidence"

    # Check if there is a confirmed HUMAN_CONFIRMATION evidence
    human_confirmation_count = (
        db.query(func.count(SddEvidence.id))
        .filter(
            SddEvidence.workspace_id == workspace_id,
            SddEvidence.task_id == task_id,
            SddEvidence.status == EvidenceStatus.CONFIRMED,
            SddEvidence.source_type == EvidenceSourceType.HUMAN_CONFIRMATION,
            SddEvidence.confirmed_by_id.isnot(None),
            SddEvidence.confirmed_at.isnot(None),
        )
        .scalar()
        or 0
    )
    if human_confirmation_count == 0:
        return "waiting_human_confirmation"

    return "verified"


def _task_summary_from_counts(db: Session, task: SddTask) -> TaskSummary:
    """Build TaskSummary using COUNT queries instead of loading collections."""
    ws_id = task.workspace_id
    task_id = task.id

    requirement_count = _count(db, SddTaskRequirement, ws_id, task_id=task_id)
    spec_count = _count(db, SddAsset, ws_id, task_id=task_id, asset_type=AssetType.SPEC)
    plan_asset_count = _count(db, SddAsset, ws_id, task_id=task_id, asset_type=AssetType.PLAN)
    plan_node_count = _count(db, SddPlanNode, ws_id, task_id=task_id)
    ai_run_count = _count(db, SddAiJob, ws_id, task_id=task_id)
    human_review_count = _count(db, SddHumanReview, ws_id, task_id=task_id)
    human_delta_count = _count(db, SddHumanDelta, ws_id, task_id=task_id)
    evidence_count = _count(db, SddEvidence, ws_id, task_id=task_id)
    decision_count = _count(db, SddDecision, ws_id, task_id=task_id)
    clarification_count = _count(db, SddClarification, ws_id, task_id=task_id)

    coverage_status = _coverage_status_from_db(db, ws_id, task_id, requirement_count)

    creator_display_name = None
    if task.creator_id:
        creator = db.query(User.display_name).filter(User.id == task.creator_id).first()
        if creator:
            creator_display_name = creator[0]

    return TaskSummary(
        id=task.id,
        workspace_id=task.workspace_id,
        creator_id=task.creator_id,
        creator_display_name=creator_display_name,
        name=task.name,
        description=task.description,
        status=_enum_value(task.status),
        current_phase=task.current_phase,
        requirement_count=requirement_count,
        spec_count=spec_count,
        plan_count=plan_asset_count + plan_node_count,
        ai_run_count=ai_run_count,
        human_review_count=human_review_count,
        human_delta_count=human_delta_count,
        evidence_count=evidence_count,
        decision_count=decision_count,
        clarification_count=clarification_count,
        coverage_status=coverage_status,
        baseline_version=int(task.baseline_version or 0),
        baselined_at=task.baselined_at,
        baselined_by_id=task.baselined_by_id,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _task_requirement_link(link: SddTaskRequirement) -> TaskRequirementLinkResponse:
    from app.domains.workspace_asset.services.workspace_asset_service import _requirement_summary

    return TaskRequirementLinkResponse(
        id=link.id,
        requirement_id=link.requirement_id,
        task_id=link.task_id,
        relation_type=_enum_value(link.relation_type),
        requirement=_requirement_summary(link.requirement) if link.requirement else None,
        created_at=link.created_at,
    )


def get_task_detail_summary(
    db: Session,
    workspace_id: str,
    task_id: str,
) -> Optional[TaskDetailSummaryResponse]:
    """
    Lightweight task detail summary for initial page load.

    Only loads SddTask + requirement_links. All other counts use COUNT queries.
    Does NOT load human_reviews, human_deltas, evidence, decisions,
    clarifications, final_summary, process_audit_logs, change_proposals, etc.
    """
    task = (
        db.query(SddTask)
        .options(
            selectinload(SddTask.requirement_links).selectinload(SddTaskRequirement.requirement),
        )
        .filter(SddTask.workspace_id == workspace_id, SddTask.id == task_id)
        .first()
    )
    if not task:
        return None

    task_summary = _task_summary_from_counts(db, task)
    requirement_links = sorted(task.requirement_links or [], key=lambda item: item.created_at, reverse=True)

    # Process summary using count-based status checks
    spec_count = task_summary.spec_count
    plan_count = task_summary.plan_count
    ai_run_count = task_summary.ai_run_count
    review_count = task_summary.human_review_count
    delta_count = task_summary.human_delta_count
    evidence_count = task_summary.evidence_count

    process_summary = TaskProcessSummary(
        spec_status="available" if spec_count > 0 else "empty",
        plan_status="available" if plan_count > 0 else "empty",
        ai_run_status="available" if ai_run_count > 0 else "empty",
        human_review_status="available" if review_count > 0 else "empty",
        human_delta_status="available" if delta_count > 0 else "empty",
        evidence_status="available" if evidence_count > 0 else "empty",
        coverage_status=task_summary.coverage_status,
        risk_status="not_available",
    )

    has_any_process = any([spec_count, plan_count, ai_run_count, review_count, delta_count, evidence_count])
    connection_status = [
        _connection(
            "task_process_assets",
            "Task process assets",
            "AVAILABLE" if has_any_process else "EMPTY",
            "Real process records are available."
            if has_any_process
            else "No process assets are connected for this task yet.",
        ),
        _connection(
            "coverage_verification",
            "Coverage verification",
            "AVAILABLE" if task_summary.coverage_status == "verified" else "EMPTY",
            "Verified coverage is backed by confirmed Evidence and human confirmation."
            if task_summary.coverage_status == "verified"
            else "Coverage cannot be verified without real Evidence and human confirmation.",
        ),
    ]

    return TaskDetailSummaryResponse(
        task=task_summary,
        requirement_links=[_task_requirement_link(link) for link in requirement_links],
        process_summary=process_summary,
        connection_status=connection_status,
    )
