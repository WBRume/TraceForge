"""追溯视图：Spec Coverage 矩阵、Evidence Registry、Human Delta 看板。

覆盖状态机（rejected > need_clarification > verified > human_modified >
evidence_missing > in_progress > spec_covered > missing）只在本模块定义。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session, selectinload

from app.domains.asset.models.asset import AssetType, SddAsset
from app.domains.task.models.task import SddPlanNode, SddTask
from app.domains.workspace_asset.models.workspace_asset import (
    ClarificationStatus,
    DecisionStatus,
    HumanReviewOutcome,
    SddEvidence,
    SddHumanDelta,
    SddRequirement,
    SddTaskRequirement,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    SpecCoverageMatrixItem,
    SpecCoverageMatrixTraceRefs,
    TraceabilityViewResponse,
    WorkspaceAssetsTraceabilityResponse,
)
from app.domains.workspace_asset.services.common.primitives import (
    collection_state,
    dedupe_by_id,
    enum_value,
    is_human_confirmation,
    make_connection,
)


def _evidence_registry_items(evidence_items: List[SddEvidence]) -> List[Dict[str, Any]]:
    from app.domains.workspace_asset.services.common.process_presenters import external_evidence_ref

    return [
        {
            "id": item.id,
            "requirement_id": item.requirement_id,
            "task_id": item.task_id,
            "ai_job_id": item.ai_job_id,
            "status": enum_value(item.status),
            "source": external_evidence_ref(item).model_dump(),
            "title": item.title,
        }
        for item in evidence_items
    ]


def _human_delta_dashboard_items(deltas: List[SddHumanDelta]) -> List[Dict[str, Any]]:
    return [
        {
            "id": item.id,
            "task_id": item.task_id,
            "proposal_id": item.proposal_id,
            "final_evidence_id": item.final_evidence_id,
            "status": enum_value(item.status),
            "changed_files_count": item.changed_files_count,
            "insertions": item.insertions,
            "deletions": item.deletions,
            "decision_count": len(item.decisions or []),
        }
        for item in deltas
    ]


def _task_assets(task: Optional[SddTask], asset_type: AssetType) -> List[SddAsset]:
    if not task:
        return []
    return [item for item in (task.assets or []) if enum_value(item.asset_type) == asset_type.value]


def _has_rejected_review(task: Optional[SddTask]) -> bool:
    if not task:
        return False
    rejected_values = {"reject", "rejected", "request_changes", "changes_requested"}
    for review in task.human_reviews or []:
        if enum_value(review.outcome) == HumanReviewOutcome.REJECT.value:
            return True
        if (review.review_type or "").strip().lower() in rejected_values:
            return True
        source_ref = review.source_ref_json if isinstance(review.source_ref_json, dict) else {}
        for key in ("status", "decision", "result", "outcome"):
            if str(source_ref.get(key, "")).strip().lower() in rejected_values:
                return True
    return False


def matrix_coverage_status(
    *,
    task: Optional[SddTask],
    specs: List[SddAsset],
    plans: List[SddAsset],
    plan_nodes: List[SddPlanNode],
    evidence_items: List[SddEvidence],
) -> tuple[str, str]:
    if not task:
        return "missing", "Requirement is not linked to a Task yet."

    decisions = list(task.decisions or [])
    clarifications = list(task.clarifications or [])
    ai_runs = list(task.ai_jobs or [])
    reviews = list(task.human_reviews or [])
    deltas = list(task.human_deltas or [])
    has_rejection = any(enum_value(item.status) == DecisionStatus.REJECTED.value for item in decisions)
    if has_rejection or _has_rejected_review(task):
        return "rejected", "Rejected status is traceable to a real Human Review or Decision."
    if any(enum_value(item.status) == ClarificationStatus.OPEN.value for item in clarifications):
        return "need_clarification", "Open Clarification exists for this Requirement and Task path."
    if any(is_human_confirmation(item) for item in evidence_items):
        return "verified", "Verified requires confirmed Evidence and a real human confirmation."
    if deltas:
        return "human_modified", "Human Delta exists and can be traced from this Task."

    process_after_spec = bool(plans or plan_nodes or ai_runs or reviews or decisions or clarifications)
    if process_after_spec and not evidence_items:
        return "evidence_missing", "Process records exist, but no real Evidence reference is attached."
    if plans or plan_nodes or ai_runs or reviews:
        return "in_progress", "Task process records exist, but verification is not complete."
    if specs:
        return "spec_covered", "A real Spec exists, but this is not a verified coverage conclusion."
    return "missing", "No traceable process asset is connected for this Requirement and Task path."


def _coverage_matrix_row(
    requirement: SddRequirement,
    link: Optional[SddTaskRequirement],
) -> SpecCoverageMatrixItem:
    task = link.task if link else None
    specs = _task_assets(task, AssetType.SPEC)
    plan_assets = _task_assets(task, AssetType.PLAN)
    plan_nodes = list(task.plan_nodes or []) if task else []
    ai_runs = list(task.ai_jobs or []) if task else []
    reviews = list(task.human_reviews or []) if task else []
    deltas = list(task.human_deltas or []) if task else []
    evidence_items = dedupe_by_id([
        *(requirement.evidence_items or []),
        *((task.evidence_items or []) if task else []),
    ])
    decisions = list(task.decisions or []) if task else []
    clarifications = list(task.clarifications or []) if task else []
    coverage_status_value, coverage_reason = matrix_coverage_status(
        task=task,
        specs=specs,
        plans=plan_assets,
        plan_nodes=plan_nodes,
        evidence_items=evidence_items,
    )

    row_id = f"{requirement.id}:{link.task_id if link else 'no-task'}"
    return SpecCoverageMatrixItem(
        id=row_id,
        requirement_id=requirement.id,
        requirement_title=requirement.title,
        task_id=link.task_id if link else None,
        task_name=task.name if task else None,
        relation_type=enum_value(link.relation_type) if link else None,
        spec_status="available" if specs else "empty",
        plan_status="available" if plan_assets or plan_nodes else "empty",
        ai_run_status="available" if ai_runs else "empty",
        human_review_status="available" if reviews else "empty",
        human_delta_status="available" if deltas else "empty",
        evidence_status="available" if evidence_items else "empty",
        coverage_status=coverage_status_value,
        coverage_reason=coverage_reason,
        trace_refs=SpecCoverageMatrixTraceRefs(
            spec_ids=[item.id for item in specs],
            plan_ids=[item.id for item in [*plan_assets, *plan_nodes]],
            ai_run_ids=[item.id for item in ai_runs],
            human_review_ids=[item.id for item in reviews],
            human_delta_ids=[item.id for item in deltas],
            evidence_ids=[item.id for item in evidence_items],
            decision_ids=[item.id for item in decisions],
            clarification_ids=[item.id for item in clarifications],
        ),
    )


def _coverage_matrix_items(requirements: List[SddRequirement]) -> List[Dict[str, Any]]:
    rows: List[SpecCoverageMatrixItem] = []
    for requirement in requirements:
        links = list(requirement.task_links or [])
        if not links:
            rows.append(_coverage_matrix_row(requirement, None))
            continue
        rows.extend(_coverage_matrix_row(requirement, link) for link in links)
    return [item.model_dump() for item in rows]


def get_traceability(db: Session, workspace_id: str) -> WorkspaceAssetsTraceabilityResponse:
    requirements = (
        db.query(SddRequirement)
        .options(
            selectinload(SddRequirement.evidence_items),
            selectinload(SddRequirement.task_links)
            .selectinload(SddTaskRequirement.task)
            .selectinload(SddTask.assets),
            selectinload(SddRequirement.task_links)
            .selectinload(SddTaskRequirement.task)
            .selectinload(SddTask.plan_nodes),
            selectinload(SddRequirement.task_links)
            .selectinload(SddTaskRequirement.task)
            .selectinload(SddTask.ai_jobs),
            selectinload(SddRequirement.task_links)
            .selectinload(SddTaskRequirement.task)
            .selectinload(SddTask.human_reviews),
            selectinload(SddRequirement.task_links)
            .selectinload(SddTaskRequirement.task)
            .selectinload(SddTask.human_deltas),
            selectinload(SddRequirement.task_links)
            .selectinload(SddTaskRequirement.task)
            .selectinload(SddTask.evidence_items),
            selectinload(SddRequirement.task_links)
            .selectinload(SddTaskRequirement.task)
            .selectinload(SddTask.decisions),
            selectinload(SddRequirement.task_links)
            .selectinload(SddTaskRequirement.task)
            .selectinload(SddTask.clarifications),
        )
        .filter(SddRequirement.workspace_id == workspace_id)
        .order_by(SddRequirement.created_at.desc())
        .all()
    )
    links = (
        db.query(SddTaskRequirement)
        .filter(SddTaskRequirement.workspace_id == workspace_id)
        .order_by(SddTaskRequirement.created_at.desc())
        .all()
    )
    evidence_items = (
        db.query(SddEvidence)
        .filter(SddEvidence.workspace_id == workspace_id)
        .order_by(SddEvidence.created_at.desc())
        .all()
    )
    deltas = (
        db.query(SddHumanDelta)
        .options(selectinload(SddHumanDelta.decisions))
        .filter(SddHumanDelta.workspace_id == workspace_id)
        .order_by(SddHumanDelta.created_at.desc())
        .all()
    )

    coverage_items = _coverage_matrix_items(requirements)
    evidence_registry_items = _evidence_registry_items(evidence_items)
    delta_items = _human_delta_dashboard_items(deltas)
    return WorkspaceAssetsTraceabilityResponse(
        workspace_id=workspace_id,
        views=[
            TraceabilityViewResponse(
                key="spec_coverage_matrix",
                title="Spec Coverage Matrix",
                view_type="derived_matrix",
                items=coverage_items,
                total=len(coverage_items),
                state=collection_state(len(coverage_items), "Waiting for Requirement and Task links."),
            ),
            TraceabilityViewResponse(
                key="evidence_registry",
                title="Evidence Registry",
                view_type="derived_registry",
                items=evidence_registry_items,
                total=len(evidence_registry_items),
                state=collection_state(len(evidence_registry_items), "Waiting for real Evidence references."),
            ),
            TraceabilityViewResponse(
                key="human_delta_dashboard",
                title="Human Delta Dashboard",
                view_type="derived_dashboard",
                items=delta_items,
                total=len(delta_items),
                state=collection_state(len(delta_items), "Waiting for Human Delta records."),
            ),
            TraceabilityViewResponse(
                key="risk_board",
                title="Risk Board",
                view_type="derived_board",
                items=[],
                total=0,
                state=collection_state(0, "Risk Board requires real task, evidence and review signals."),
            ),
        ],
        connection_status=[
            make_connection(
                "traceable_assets",
                "Traceable assets",
                "AVAILABLE" if any([requirements, links, evidence_items, deltas]) else "EMPTY",
                "Traceability is derived from real asset records."
                if any([requirements, links, evidence_items, deltas])
                else "Waiting for real Requirement, Task, Evidence and Review records.",
            )
        ],
    )
