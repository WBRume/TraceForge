"""
Workspace Assets read orchestration and Requirement write service.

Task Detail process asset writes live in workspace_task_detail_service so this
module does not absorb another process-asset workflow.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from app.database import SessionLocal
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.asset.models.asset import AssetType, SddAsset
from app.domains.task.models.task import SddPlanNode, SddTask
from app.domains.workflow.models.task_change import (
    SddTaskChangeProposal,
)
from app.domains.auth.models.user import Workspace
from app.domains.workspace_asset.models.workspace_asset import (
    ClarificationStatus,
    DecisionStatus,
    EvidenceSourceType,
    EvidenceStatus,
    HumanReviewOutcome,
    RequirementAuditAction,
    RequirementImportBatchStatus,
    RequirementImportItemStatus,
    RequirementStatus,
    SddAiOutput,
    SddClarification,
    SddDecision,
    SddEvidence,
    SddHumanDelta,
    SddHumanReview,
    SddKnowledgeAsset,
    SddRequirement,
    SddRequirementAuditLog,
    SddRequirementImportBatch,
    SddRequirementImportItem,
    SddTaskRequirement,
    TaskRequirementRelationType,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    AiOutputResponse,
    AiRunSummary,
    ClarificationResponse,
    DecisionResponse,
    EvidenceResponse,
    ExternalEvidenceRef,
    HumanDeltaResponse,
    HumanReviewResponse,
    KnowledgeAssetResponse,
    PlanNodeAssetSummary,
    RequirementAuditLogResponse,
    RequirementCoverageSummary,
    RequirementCreateRequest,
    RequirementDetailResponse,
    RequirementImportBatchResponse,
    RequirementImportConfirmRequest,
    RequirementImportPreviewItem,
    RequirementPreviewJobResponse,
    RequirementSplitRequest,
    RequirementTaskLinkRequest,
    RequirementLinkedTaskResponse,
    RequirementSummary,
    RequirementUpdateRequest,
    SpecCoverageMatrixItem,
    SpecCoverageMatrixTraceRefs,
    TaskAssetSummary,
    TaskDetailResponse,
    TaskProcessSummary,
    TaskRequirementLinkResponse,
    TaskSummary,
    TraceabilityViewResponse,
    WorkspaceAssetConnectionStatus,
    WorkspaceAssetListState,
    WorkspaceAssetsKnowledgeResponse,
    WorkspaceAssetsOverviewResponse,
    WorkspaceAssetsRequirementsResponse,
    WorkspaceAssetsTasksResponse,
    WorkspaceAssetsTraceabilityResponse,
)
from app.domains.asset.services.asset_document_service import parse_document_payload
from app.domains.workspace_asset.services import workspace_task_detail_service
from app.domains.ai.services.ai_job_service import run_cli_single_turn


class WorkspaceAssetWriteError(Exception):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _count(db: Session, model: Any, workspace_id: str, **filters: Any) -> int:
    query = db.query(func.count(model.id)).filter(model.workspace_id == workspace_id)
    for field, value in filters.items():
        query = query.filter(getattr(model, field) == value)
    return int(query.scalar() or 0)


def _connection(key: str, label: str, state: str, detail: str) -> WorkspaceAssetConnectionStatus:
    return WorkspaceAssetConnectionStatus(key=key, label=label, state=state, detail=detail)


def _collection_state(total: int, message: str) -> WorkspaceAssetListState:
    return WorkspaceAssetListState(empty=total == 0, message=message if total == 0 else None)


def _short_text(value: Any, limit: int = 280) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
    else:
        text = str(value).strip()
    if not text:
        return None
    return text if len(text) <= limit else f"{text[:limit].rstrip()}..."


def _json_text(payload: Optional[Dict[str, Any]], keys: Iterable[str]) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if value:
            return _short_text(value)
    return None


def _clean_optional(value: Optional[str], *, limit: Optional[int] = None) -> Optional[str]:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return normalized[:limit] if limit else normalized


def _normalize_list(values: Optional[Iterable[Any]]) -> List[str]:
    if not values:
        return []
    result: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if text:
            result.append(text)
    return result


def _normalize_status(value: Optional[str], *, default: RequirementStatus = RequirementStatus.DRAFT) -> RequirementStatus:
    raw = str(value or default.value).strip().upper()
    try:
        return RequirementStatus(raw)
    except ValueError as exc:
        raise WorkspaceAssetWriteError(f"Unsupported requirement status: {value}", status_code=422) from exc


def _normalize_relation_type(value: Optional[str]) -> TaskRequirementRelationType:
    raw = str(value or TaskRequirementRelationType.RELATES_TO.value).strip().upper()
    try:
        return TaskRequirementRelationType(raw)
    except ValueError as exc:
        raise WorkspaceAssetWriteError(f"Unsupported requirement-task relation type: {value}", status_code=422) from exc


def _json_dict(value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return value if isinstance(value, dict) and value else None


def _payload_has_field(payload: Any, field_name: str) -> bool:
    fields_set = getattr(payload, "model_fields_set", None)
    if fields_set is None:
        fields_set = getattr(payload, "__fields_set__", set())
    return field_name in fields_set


def _requirement_snapshot(requirement: SddRequirement) -> Dict[str, Any]:
    return {
        "id": requirement.id,
        "title": requirement.title,
        "body": requirement.body,
        "status": _enum_value(requirement.status),
        "acceptance_criteria": list(requirement.acceptance_criteria_json or []),
        "priority": requirement.priority,
        "parent_requirement_id": requirement.parent_requirement_id,
        "import_batch_id": requirement.import_batch_id,
        "source_kind": requirement.source_kind,
        "source_uri": requirement.source_uri,
        "source_ref": requirement.source_ref,
        "source_metadata": requirement.source_metadata_json,
    }


def _add_requirement_audit(
    db: Session,
    *,
    workspace_id: str,
    action: RequirementAuditAction,
    actor_id: Optional[str] = None,
    requirement_id: Optional[str] = None,
    import_batch_id: Optional[str] = None,
    task_id: Optional[str] = None,
    before: Optional[Dict[str, Any]] = None,
    after: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
    source_metadata: Optional[Dict[str, Any]] = None,
) -> SddRequirementAuditLog:
    log = SddRequirementAuditLog(
        workspace_id=workspace_id,
        requirement_id=requirement_id,
        import_batch_id=import_batch_id,
        task_id=task_id,
        actor_id=actor_id,
        action=action,
        before_json=before,
        after_json=after,
        reason=_clean_optional(reason),
        source_metadata_json=_json_dict(source_metadata),
    )
    db.add(log)
    return log


def _requirement_audit_response(log: SddRequirementAuditLog) -> RequirementAuditLogResponse:
    return RequirementAuditLogResponse(
        id=log.id,
        workspace_id=log.workspace_id,
        requirement_id=log.requirement_id,
        import_batch_id=log.import_batch_id,
        task_id=log.task_id,
        actor_id=log.actor_id,
        action=_enum_value(log.action),
        before=log.before_json if isinstance(log.before_json, dict) else None,
        after=log.after_json if isinstance(log.after_json, dict) else None,
        reason=log.reason,
        source_metadata=log.source_metadata_json if isinstance(log.source_metadata_json, dict) else None,
        created_at=log.created_at,
    )


def _is_human_confirmation(evidence: SddEvidence) -> bool:
    return (
        _enum_value(evidence.source_type) == EvidenceSourceType.HUMAN_CONFIRMATION.value
        and _enum_value(evidence.status) == EvidenceStatus.CONFIRMED.value
        and bool(evidence.confirmed_by_id)
        and evidence.confirmed_at is not None
    )


def _coverage_status(requirement_count: int, evidence_items: Iterable[SddEvidence]) -> str:
    if requirement_count <= 0:
        return "not_available"

    evidence_list = list(evidence_items)
    confirmed = [
        item
        for item in evidence_list
        if _enum_value(item.status) == EvidenceStatus.CONFIRMED.value
    ]
    if not confirmed:
        return "waiting_evidence"
    if not any(_is_human_confirmation(item) for item in confirmed):
        return "waiting_human_confirmation"
    return "verified"


def _asset_summary(asset: SddAsset) -> TaskAssetSummary:
    return TaskAssetSummary(
        id=asset.id,
        asset_type=_enum_value(asset.asset_type),
        title=asset.name,
        status="AVAILABLE",
        content_text=asset.content_text,
        content_json=asset.content_json if isinstance(asset.content_json, dict) else None,
        created_at=asset.created_at,
        updated_at=None,
    )


def _plan_node_summary(node: SddPlanNode) -> PlanNodeAssetSummary:
    return PlanNodeAssetSummary(
        id=node.id,
        title=node.title,
        description=node.description,
        status=_enum_value(node.status),
        order_index=node.order_index,
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


def _ai_run_summary(job: SddAiJob) -> AiRunSummary:
    outputs = list(job.outputs or [])
    explicit_adoption_status = _json_text(job.result_json, ["adoption_status", "adoptionStatus"])
    output_titles = [item.title for item in outputs if item.title]
    return AiRunSummary(
        id=job.id,
        task_id=job.task_id,
        channel=_enum_value(job.channel),
        status=_enum_value(job.status),
        progress=job.progress,
        message=job.message,
        input_summary=_short_text(job.prompt_text)
        or _json_text(job.context_json, ["input_summary", "inputSummary", "summary", "prompt"]),
        output_summary=_json_text(job.result_json, ["output_summary", "outputSummary", "summary", "message"])
        or _short_text(", ".join(output_titles)),
        adoption_status=explicit_adoption_status or "not_available",
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def _requirement_linked_task(link: SddTaskRequirement) -> RequirementLinkedTaskResponse:
    task = link.task
    requirement_count = len(task.requirement_links or []) if task else 0
    evidence_items = list(task.evidence_items or []) if task else []
    return RequirementLinkedTaskResponse(
        link_id=link.id,
        task_id=link.task_id,
        task_name=task.name if task else "",
        task_status=_enum_value(task.status) if task else "unknown",
        current_phase=task.current_phase if task else None,
        relation_type=_enum_value(link.relation_type),
        coverage_status=_coverage_status(requirement_count, evidence_items),
        created_at=link.created_at,
    )


def _requirement_family(requirement: SddRequirement) -> List[SddRequirement]:
    members = [requirement]
    if not requirement.parent_requirement_id:
        members.extend(list(requirement.child_requirements or []))
    return members


def _requirement_task_links(requirement: SddRequirement) -> List[SddTaskRequirement]:
    return [link for member in _requirement_family(requirement) for link in (member.task_links or [])]


def _requirement_coverage_summary(requirement: SddRequirement) -> RequirementCoverageSummary:
    task_links = _requirement_task_links(requirement)
    tasks = [link.task for link in task_links if link.task]
    evidence_items = _dedupe_by_id([
        *[evidence for member in _requirement_family(requirement) for evidence in (member.evidence_items or [])],
        *[evidence for task in tasks for evidence in (task.evidence_items or [])],
    ])
    human_review_count = sum(len(task.human_reviews or []) for task in tasks)
    human_delta_count = sum(len(task.human_deltas or []) for task in tasks)
    coverage_status = _coverage_status(len(task_links), evidence_items)
    if coverage_status == "verified":
        reason = "Coverage Verified is derived from confirmed Evidence and human confirmation."
    elif coverage_status == "waiting_human_confirmation":
        reason = "Evidence exists, but human confirmation is still required before Coverage can be Verified."
    elif coverage_status == "waiting_evidence":
        reason = "Requirement has related Task records, but no confirmed Evidence is attached."
    else:
        reason = "Coverage is unavailable until the Requirement is linked to a real Task."
    return RequirementCoverageSummary(
        coverage_status=coverage_status,
        coverage_reason=reason,
        related_task_count=len(task_links),
        evidence_count=len(evidence_items),
        human_review_count=human_review_count,
        human_delta_count=human_delta_count,
    )


def _requirement_summary(
    requirement: SddRequirement,
    *,
    include_linked_tasks: bool = False,
    include_children: bool = False,
) -> RequirementSummary:
    task_links = _requirement_task_links(requirement)
    children = sorted(list(requirement.child_requirements or []), key=lambda item: item.created_at or datetime.min, reverse=True)
    child_count = len(children)
    return RequirementSummary(
        id=requirement.id,
        workspace_id=requirement.workspace_id,
        title=requirement.title,
        body=requirement.body,
        status=_enum_value(requirement.status),
        acceptance_criteria=_normalize_list(requirement.acceptance_criteria_json),
        priority=requirement.priority,
        parent_requirement_id=requirement.parent_requirement_id,
        parent_title=requirement.parent_requirement.title if requirement.parent_requirement else None,
        child_count=child_count,
        children=[
            _requirement_summary(child, include_linked_tasks=True, include_children=False)
            for child in children
        ] if include_children else [],
        can_link_task=bool(requirement.parent_requirement_id or child_count == 0),
        import_batch_id=requirement.import_batch_id,
        source_kind=requirement.source_kind,
        source_uri=requirement.source_uri,
        source_ref=requirement.source_ref,
        source_metadata=requirement.source_metadata_json if isinstance(requirement.source_metadata_json, dict) else None,
        coverage_summary=_requirement_coverage_summary(requirement),
        change_history_count=len(requirement.audit_logs or []),
        related_task_count=len(task_links),
        linked_tasks=[_requirement_linked_task(link) for link in task_links] if include_linked_tasks else [],
        created_at=requirement.created_at,
        updated_at=requirement.updated_at,
    )


def _task_requirement_link(link: SddTaskRequirement) -> TaskRequirementLinkResponse:
    return TaskRequirementLinkResponse(
        id=link.id,
        requirement_id=link.requirement_id,
        task_id=link.task_id,
        relation_type=_enum_value(link.relation_type),
        requirement=_requirement_summary(link.requirement) if link.requirement else None,
        created_at=link.created_at,
    )


def _external_evidence_ref(evidence: SddEvidence) -> ExternalEvidenceRef:
    return ExternalEvidenceRef(
        source_type=_enum_value(evidence.source_type),
        source_uri=evidence.source_uri,
        source_label=evidence.source_label,
        source_ref=evidence.source_ref,
        source_path=evidence.source_path,
        source_metadata=evidence.source_metadata_json,
    )


def _evidence_response(evidence: SddEvidence) -> EvidenceResponse:
    return EvidenceResponse(
        id=evidence.id,
        workspace_id=evidence.workspace_id,
        requirement_id=evidence.requirement_id,
        task_id=evidence.task_id,
        ai_job_id=evidence.ai_job_id,
        human_review_id=evidence.human_review_id,
        status=_enum_value(evidence.status),
        evidence_type=_enum_value(evidence.evidence_type),
        source=_external_evidence_ref(evidence),
        title=evidence.title,
        summary=evidence.summary,
        confirmed_by_id=evidence.confirmed_by_id,
        confirmed_at=evidence.confirmed_at,
        created_at=evidence.created_at,
        updated_at=evidence.updated_at,
    )


def _ai_output_response(output: SddAiOutput) -> AiOutputResponse:
    return AiOutputResponse(
        id=output.id,
        workspace_id=output.workspace_id,
        task_id=output.task_id,
        ai_job_id=output.ai_job_id,
        output_type=_enum_value(output.output_type),
        title=output.title,
        content_text=output.content_text,
        content_json=output.content_json,
        created_at=output.created_at,
    )


def _human_review_response(review: SddHumanReview) -> HumanReviewResponse:
    return workspace_task_detail_service.human_review_response(review)


def _human_delta_response(delta: SddHumanDelta) -> HumanDeltaResponse:
    return workspace_task_detail_service.human_delta_response(delta)


def _decision_response(decision: SddDecision) -> DecisionResponse:
    return workspace_task_detail_service.decision_response(decision)


def _clarification_response(clarification: SddClarification) -> ClarificationResponse:
    return workspace_task_detail_service.clarification_response(clarification)


def _final_summary_response(summary: Any) -> Any:
    return workspace_task_detail_service.final_summary_response(summary)


def _process_audit_response(log: Any) -> Any:
    return workspace_task_detail_service.process_audit_response(log)


def _knowledge_asset_response(asset: SddKnowledgeAsset) -> KnowledgeAssetResponse:
    return KnowledgeAssetResponse(
        id=asset.id,
        workspace_id=asset.workspace_id,
        asset_type=_enum_value(asset.asset_type),
        status=_enum_value(asset.status),
        title=asset.title,
        body=asset.body,
        source_task_id=asset.source_task_id,
        source_decision_id=asset.source_decision_id,
        source_human_delta_id=asset.source_human_delta_id,
        source_clarification_id=asset.source_clarification_id,
        source_review_id=asset.source_review_id,
        source_evidence_id=asset.source_evidence_id,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )


def _task_summary(db: Session, task: SddTask) -> TaskSummary:
    evidence_items = list(task.evidence_items or [])
    requirement_count = len(task.requirement_links or [])
    spec_count = _count(db, SddAsset, task.workspace_id, task_id=task.id, asset_type=AssetType.SPEC)
    plan_asset_count = _count(db, SddAsset, task.workspace_id, task_id=task.id, asset_type=AssetType.PLAN)
    plan_node_count = _count(db, SddPlanNode, task.workspace_id, task_id=task.id)
    return TaskSummary(
        id=task.id,
        workspace_id=task.workspace_id,
        creator_id=task.creator_id,
        name=task.name,
        description=task.description,
        status=_enum_value(task.status),
        current_phase=task.current_phase,
        requirement_count=requirement_count,
        spec_count=spec_count,
        plan_count=plan_asset_count + plan_node_count,
        ai_run_count=len(task.ai_jobs or []),
        human_review_count=len(task.human_reviews or []),
        human_delta_count=len(task.human_deltas or []),
        evidence_count=len(evidence_items),
        decision_count=len(task.decisions or []),
        clarification_count=len(task.clarifications or []),
        coverage_status=_coverage_status(requirement_count, evidence_items),
        baseline_version=int(task.baseline_version or 0),
        baselined_at=task.baselined_at,
        baselined_by_id=task.baselined_by_id,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _overview_connection_status(
    *,
    requirement_count: int,
    task_count: int,
    ai_run_count: int,
    evidence_count: int,
) -> List[WorkspaceAssetConnectionStatus]:
    return [
        _connection(
            "requirement_source",
            "Requirement source",
            "AVAILABLE" if requirement_count else "NOT_CONNECTED",
            "Requirement Repository has real records." if requirement_count else "Waiting for requirement source connection.",
        ),
        _connection(
            "task_records",
            "Task records",
            "AVAILABLE" if task_count else "EMPTY",
            "Real Task records are available." if task_count else "No real task process records yet.",
        ),
        _connection(
            "ai_runs",
            "AI Run records",
            "AVAILABLE" if ai_run_count else "EMPTY",
            "AI Run records are available." if ai_run_count else "No AI Run records are connected for assets yet.",
        ),
        _connection(
            "evidence_source",
            "Evidence source",
            "AVAILABLE" if evidence_count else "NOT_CONNECTED",
            "Evidence references are available." if evidence_count else "Waiting for real external evidence or human confirmation.",
        ),
        _connection(
            "coverage_verification",
            "Coverage verification",
            "EMPTY",
            "Verified coverage requires real Evidence and human confirmation.",
        ),
    ]


def get_overview(db: Session, workspace_id: str) -> WorkspaceAssetsOverviewResponse:
    requirement_count = _count(db, SddRequirement, workspace_id)
    task_count = _count(db, SddTask, workspace_id)
    ai_run_count = _count(db, SddAiJob, workspace_id)
    evidence_count = _count(db, SddEvidence, workspace_id)
    knowledge_asset_count = _count(db, SddKnowledgeAsset, workspace_id)
    return WorkspaceAssetsOverviewResponse(
        workspace_id=workspace_id,
        requirement_count=requirement_count,
        task_count=task_count,
        ai_run_count=ai_run_count,
        evidence_count=evidence_count,
        knowledge_asset_count=knowledge_asset_count,
        coverage_status="not_available",
        connection_status=_overview_connection_status(
            requirement_count=requirement_count,
            task_count=task_count,
            ai_run_count=ai_run_count,
            evidence_count=evidence_count,
        ),
    )


def _requirement_load_options() -> tuple[Any, ...]:
    return (
        selectinload(SddRequirement.parent_requirement),
        selectinload(SddRequirement.child_requirements),
        selectinload(SddRequirement.child_requirements).selectinload(SddRequirement.task_links),
        selectinload(SddRequirement.child_requirements)
        .selectinload(SddRequirement.task_links)
        .selectinload(SddTaskRequirement.task)
        .selectinload(SddTask.requirement_links),
        selectinload(SddRequirement.child_requirements)
        .selectinload(SddRequirement.task_links)
        .selectinload(SddTaskRequirement.task)
        .selectinload(SddTask.evidence_items),
        selectinload(SddRequirement.child_requirements)
        .selectinload(SddRequirement.task_links)
        .selectinload(SddTaskRequirement.task)
        .selectinload(SddTask.human_reviews),
        selectinload(SddRequirement.child_requirements)
        .selectinload(SddRequirement.task_links)
        .selectinload(SddTaskRequirement.task)
        .selectinload(SddTask.human_deltas),
        selectinload(SddRequirement.child_requirements).selectinload(SddRequirement.evidence_items),
        selectinload(SddRequirement.child_requirements).selectinload(SddRequirement.audit_logs),
        selectinload(SddRequirement.task_links)
        .selectinload(SddTaskRequirement.task)
        .selectinload(SddTask.requirement_links),
        selectinload(SddRequirement.task_links)
        .selectinload(SddTaskRequirement.task)
        .selectinload(SddTask.evidence_items),
        selectinload(SddRequirement.task_links)
        .selectinload(SddTaskRequirement.task)
        .selectinload(SddTask.human_reviews),
        selectinload(SddRequirement.task_links)
        .selectinload(SddTaskRequirement.task)
        .selectinload(SddTask.human_deltas),
        selectinload(SddRequirement.evidence_items),
        selectinload(SddRequirement.audit_logs),
    )


def _requirement_sort_key(requirement: SddRequirement, sort_by: str) -> Any:
    if sort_by == "title":
        return (requirement.title or "").lower()
    if sort_by == "status":
        return _enum_value(requirement.status)
    if sort_by == "priority":
        return requirement.priority or ""
    if sort_by == "updated_at":
        return requirement.updated_at or requirement.created_at or datetime.min
    if sort_by == "child_count":
        return len(requirement.child_requirements or [])
    if sort_by == "related_task_count":
        return len(_requirement_task_links(requirement))
    return requirement.created_at or datetime.min


def list_requirements(
    db: Session,
    workspace_id: str,
    *,
    q: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    source_kind: Optional[str] = None,
    parent_id: Optional[str] = None,
    scope: str = "tree",
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 50,
) -> WorkspaceAssetsRequirementsResponse:
    scope_value = scope if scope in {"tree", "flat", "children"} else "tree"
    sort_value = sort_by if sort_by in {
        "created_at",
        "updated_at",
        "title",
        "status",
        "priority",
        "child_count",
        "related_task_count",
    } else "created_at"
    page_value = max(1, int(page or 1))
    page_size_value = max(1, min(200, int(page_size or 50)))

    query = db.query(SddRequirement).options(*_requirement_load_options()).filter(SddRequirement.workspace_id == workspace_id)
    if scope_value == "tree":
        query = query.filter(SddRequirement.parent_requirement_id.is_(None))
    elif scope_value == "children":
        if parent_id:
            query = query.filter(SddRequirement.parent_requirement_id == parent_id)
        else:
            query = query.filter(SddRequirement.parent_requirement_id.isnot(None))
    elif parent_id:
        query = query.filter(SddRequirement.parent_requirement_id == parent_id)

    search = str(q or "").strip()
    if search:
        like = f"%{search}%"
        query = query.filter(or_(SddRequirement.title.ilike(like), SddRequirement.body.ilike(like), SddRequirement.source_ref.ilike(like)))
    if status:
        query = query.filter(SddRequirement.status == status)
    if priority:
        query = query.filter(SddRequirement.priority == priority)
    if source_kind:
        query = query.filter(SddRequirement.source_kind == source_kind)

    requirements = query.all()
    reverse = sort_order != "asc"
    requirements = sorted(requirements, key=lambda item: _requirement_sort_key(item, sort_value), reverse=reverse)
    total = len(requirements)
    offset = (page_value - 1) * page_size_value
    page_items = requirements[offset:offset + page_size_value]
    return WorkspaceAssetsRequirementsResponse(
        workspace_id=workspace_id,
        items=[
            _requirement_summary(item, include_linked_tasks=True, include_children=scope_value == "tree")
            for item in page_items
        ],
        total=total,
        page=page_value,
        page_size=page_size_value,
        scope=scope_value,
        state=_collection_state(total, "Requirement source is not connected or has no records."),
        connection_status=[
            _connection(
                "requirement_source",
                "Requirement source",
                "AVAILABLE" if total else "NOT_CONNECTED",
                "Workspace-level requirement records are available."
                if total
                else "Waiting for requirement source connection.",
            )
        ],
    )


def _get_requirement(db: Session, workspace_id: str, requirement_id: str) -> Optional[SddRequirement]:
    return (
        db.query(SddRequirement)
        .options(*_requirement_load_options())
        .filter(SddRequirement.workspace_id == workspace_id, SddRequirement.id == requirement_id)
        .first()
    )


def get_requirement_detail(db: Session, workspace_id: str, requirement_id: str) -> Optional[RequirementDetailResponse]:
    requirement = _get_requirement(db, workspace_id, requirement_id)
    if not requirement:
        return None
    links = sorted(requirement.task_links or [], key=lambda item: item.created_at, reverse=True)
    logs = sorted(requirement.audit_logs or [], key=lambda item: item.created_at, reverse=True)
    return RequirementDetailResponse(
        requirement=_requirement_summary(requirement, include_linked_tasks=True, include_children=True),
        linked_tasks=[_requirement_linked_task(link) for link in links],
        children=[
            _requirement_summary(child, include_linked_tasks=True)
            for child in sorted(list(requirement.child_requirements or []), key=lambda item: item.created_at or datetime.min, reverse=True)
        ],
        audit_logs=[_requirement_audit_response(log) for log in logs],
    )


def create_requirement(
    db: Session,
    workspace_id: str,
    actor_id: Optional[str],
    payload: RequirementCreateRequest,
) -> RequirementDetailResponse:
    title = _clean_optional(payload.title, limit=300)
    if not title:
        raise WorkspaceAssetWriteError("Requirement title is required.", status_code=422)
    parent_id = _clean_optional(payload.parent_requirement_id, limit=36)
    if parent_id:
        parent = _get_requirement(db, workspace_id, parent_id)
        if not parent:
            raise WorkspaceAssetWriteError("Parent Requirement not found.", status_code=404)
        if parent.parent_requirement_id:
            raise WorkspaceAssetWriteError("Nested child Requirements are not supported in this phase.", status_code=409)

    requirement = SddRequirement(
        workspace_id=workspace_id,
        created_by_id=actor_id,
        title=title,
        body=_clean_optional(payload.body),
        status=_normalize_status(payload.status),
        acceptance_criteria_json=_normalize_list(payload.acceptance_criteria),
        priority=_clean_optional(payload.priority, limit=40),
        parent_requirement_id=parent_id,
        source_kind=_clean_optional(payload.source_kind, limit=80),
        source_uri=_clean_optional(payload.source_uri, limit=1000),
        source_ref=_clean_optional(payload.source_ref, limit=300),
        source_metadata_json=_json_dict(payload.source_metadata),
    )
    db.add(requirement)
    db.flush()
    _add_requirement_audit(
        db,
        workspace_id=workspace_id,
        requirement_id=requirement.id,
        actor_id=actor_id,
        action=RequirementAuditAction.CREATED,
        after=_requirement_snapshot(requirement),
        reason=payload.change_reason,
    )
    db.commit()
    db.expire_all()
    detail = get_requirement_detail(db, workspace_id, requirement.id)
    if not detail:
        raise WorkspaceAssetWriteError("Requirement was created but could not be loaded.", status_code=500)
    return detail


def update_requirement(
    db: Session,
    workspace_id: str,
    requirement_id: str,
    actor_id: Optional[str],
    payload: RequirementUpdateRequest,
) -> Optional[RequirementDetailResponse]:
    requirement = _get_requirement(db, workspace_id, requirement_id)
    if not requirement:
        return None

    before = _requirement_snapshot(requirement)
    if _payload_has_field(payload, "title"):
        title = _clean_optional(payload.title, limit=300)
        if not title:
            raise WorkspaceAssetWriteError("Requirement title is required.", status_code=422)
        requirement.title = title
    if _payload_has_field(payload, "body"):
        requirement.body = _clean_optional(payload.body)
    if _payload_has_field(payload, "acceptance_criteria"):
        requirement.acceptance_criteria_json = _normalize_list(payload.acceptance_criteria)
    if _payload_has_field(payload, "priority"):
        requirement.priority = _clean_optional(payload.priority, limit=40)
    if _payload_has_field(payload, "status"):
        requirement.status = _normalize_status(payload.status)
    if _payload_has_field(payload, "source_kind"):
        requirement.source_kind = _clean_optional(payload.source_kind, limit=80)
    if _payload_has_field(payload, "source_uri"):
        requirement.source_uri = _clean_optional(payload.source_uri, limit=1000)
    if _payload_has_field(payload, "source_ref"):
        requirement.source_ref = _clean_optional(payload.source_ref, limit=300)
    if _payload_has_field(payload, "source_metadata"):
        requirement.source_metadata_json = _json_dict(payload.source_metadata)

    db.flush()
    after = _requirement_snapshot(requirement)
    if before != after:
        action = (
            RequirementAuditAction.STATUS_CHANGED
            if before.get("status") != after.get("status") and {k: v for k, v in before.items() if k != "status"} == {k: v for k, v in after.items() if k != "status"}
            else RequirementAuditAction.UPDATED
        )
        _add_requirement_audit(
            db,
            workspace_id=workspace_id,
            requirement_id=requirement.id,
            actor_id=actor_id,
            action=action,
            before=before,
            after=after,
            reason=payload.change_reason,
        )
    db.commit()
    db.expire_all()
    return get_requirement_detail(db, workspace_id, requirement.id)


def link_requirement_task(
    db: Session,
    workspace_id: str,
    requirement_id: str,
    actor_id: Optional[str],
    payload: RequirementTaskLinkRequest,
) -> Optional[RequirementDetailResponse]:
    requirement = _get_requirement(db, workspace_id, requirement_id)
    if not requirement:
        return None
    if not requirement.parent_requirement_id and requirement.child_requirements:
        raise WorkspaceAssetWriteError(
            "Parent Requirement has child Requirements; link Task to a child Requirement.",
            status_code=409,
        )
    task = db.query(SddTask).filter(SddTask.workspace_id == workspace_id, SddTask.id == payload.task_id).first()
    if not task:
        raise WorkspaceAssetWriteError("Task not found in this workspace.", status_code=404)
    existing = (
        db.query(SddTaskRequirement)
        .filter(SddTaskRequirement.requirement_id == requirement_id, SddTaskRequirement.task_id == task.id)
        .first()
    )
    if existing:
        raise WorkspaceAssetWriteError("Requirement is already linked to this Task.", status_code=409)

    link = SddTaskRequirement(
        workspace_id=workspace_id,
        requirement_id=requirement_id,
        task_id=task.id,
        relation_type=_normalize_relation_type(payload.relation_type),
        created_by_id=actor_id,
    )
    db.add(link)
    db.flush()
    _add_requirement_audit(
        db,
        workspace_id=workspace_id,
        requirement_id=requirement_id,
        task_id=task.id,
        actor_id=actor_id,
        action=RequirementAuditAction.LINKED_TASK,
        after={"task_id": task.id, "relation_type": _enum_value(link.relation_type)},
        reason=payload.change_reason,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise WorkspaceAssetWriteError("Requirement is already linked to this Task.", status_code=409) from exc
    db.expire_all()
    return get_requirement_detail(db, workspace_id, requirement_id)


def unlink_requirement_task(
    db: Session,
    workspace_id: str,
    requirement_id: str,
    task_id: str,
    actor_id: Optional[str],
    change_reason: Optional[str] = None,
) -> Optional[RequirementDetailResponse]:
    requirement = _get_requirement(db, workspace_id, requirement_id)
    if not requirement:
        return None
    link = (
        db.query(SddTaskRequirement)
        .filter(
            SddTaskRequirement.workspace_id == workspace_id,
            SddTaskRequirement.requirement_id == requirement_id,
            SddTaskRequirement.task_id == task_id,
        )
        .first()
    )
    if not link:
        raise WorkspaceAssetWriteError("Requirement-Task link not found.", status_code=404)
    before = {"task_id": link.task_id, "relation_type": _enum_value(link.relation_type)}
    db.delete(link)
    _add_requirement_audit(
        db,
        workspace_id=workspace_id,
        requirement_id=requirement_id,
        task_id=task_id,
        actor_id=actor_id,
        action=RequirementAuditAction.UNLINKED_TASK,
        before=before,
        reason=change_reason,
    )
    db.commit()
    db.expire_all()
    return get_requirement_detail(db, workspace_id, requirement_id)


_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
_SPLIT_LIST_RE = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+(.+?)\s*$")
_AC_HEADING_RE = re.compile(r"(acceptance\s+criteria|验收标准|验收条件)", re.IGNORECASE)
_CHECKBOX_RE = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+(.+?)\s*$")


def _strip_marker(text: str) -> str:
    stripped = text.strip()
    checkbox = _CHECKBOX_RE.match(stripped)
    if checkbox:
        return checkbox.group(1).strip()
    return re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", stripped).strip()


def _extract_acceptance_criteria(lines: List[str]) -> List[str]:
    criteria: List[str] = []
    in_acceptance = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _AC_HEADING_RE.search(stripped):
            in_acceptance = True
            continue
        if in_acceptance and _HEADING_RE.match(stripped):
            break
        checkbox = _CHECKBOX_RE.match(stripped)
        if checkbox:
            criteria.append(checkbox.group(1).strip())
            continue
        if in_acceptance and re.match(r"^\s*(?:[-*]|\d+[.)])\s+", stripped):
            criteria.append(_strip_marker(stripped))
    return _normalize_list(criteria)


def _segment_requirements(markdown: str) -> List[Dict[str, Any]]:
    lines = [line.rstrip() for line in str(markdown or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    non_empty = [line.strip() for line in lines if line.strip()]
    if not non_empty:
        return []

    heading_positions = [(idx, match.group(2).strip()) for idx, line in enumerate(lines) if (match := _HEADING_RE.match(line))]
    segments: List[tuple[str, List[str], str]] = []
    if heading_positions:
        for offset, (start, title) in enumerate(heading_positions):
            end = heading_positions[offset + 1][0] if offset + 1 < len(heading_positions) else len(lines)
            body_lines = lines[start + 1:end]
            segments.append((title, body_lines, f"heading:{offset + 1}"))
    else:
        item_positions = [(idx, match.group(1).strip()) for idx, line in enumerate(lines) if (match := _SPLIT_LIST_RE.match(line))]
        if len(item_positions) > 1:
            for offset, (start, title) in enumerate(item_positions):
                end = item_positions[offset + 1][0] if offset + 1 < len(item_positions) else len(lines)
                body_lines = lines[start:end]
                segments.append((title, body_lines, f"item:{offset + 1}"))
        else:
            first = non_empty[0]
            title = _strip_marker(first)
            segments.append((title, lines, "document:1"))

    items: List[Dict[str, Any]] = []
    for index, (title, body_lines, source_ref) in enumerate(segments):
        normalized_title = _clean_optional(_strip_marker(title), limit=300) or f"Requirement {index + 1}"
        body = "\n".join(line for line in body_lines).strip() or None
        items.append(
            {
                "title": normalized_title,
                "body": body,
                "acceptance_criteria": _extract_acceptance_criteria(body_lines),
                "source_ref": source_ref,
                "source_metadata": {"segment_index": index, "segment_title": normalized_title},
                "order_index": index,
            }
        )
    return items


def _import_item_response(item: SddRequirementImportItem) -> RequirementImportPreviewItem:
    metadata = item.source_metadata_json if isinstance(item.source_metadata_json, dict) else None
    return RequirementImportPreviewItem(
        id=item.id,
        title=item.title,
        body=item.body,
        acceptance_criteria=_normalize_list(item.acceptance_criteria_json),
        priority=item.priority,
        task_prompt=_clean_optional((metadata or {}).get("task_prompt")),
        source_ref=item.source_ref,
        source_metadata=metadata,
        order_index=item.order_index,
        status=_enum_value(item.status),
        requirement_id=item.requirement_id,
    )


def _import_batch_response(batch: SddRequirementImportBatch) -> RequirementImportBatchResponse:
    items = sorted(batch.items or [], key=lambda item: item.order_index)
    return RequirementImportBatchResponse(
        id=batch.id,
        workspace_id=batch.workspace_id,
        source_kind=batch.source_kind,
        source_filename=batch.source_filename,
        source_uri=batch.source_uri,
        source_ref=batch.source_ref,
        source_metadata=batch.source_metadata_json if isinstance(batch.source_metadata_json, dict) else None,
        status=_enum_value(batch.status),
        item_count=batch.item_count,
        confirmed_count=batch.confirmed_count,
        normalized_markdown=batch.normalized_markdown,
        items=[_import_item_response(item) for item in items],
        created_at=batch.created_at,
        updated_at=batch.updated_at,
    )


def _preview_job_response(db: Session, job: SddAiJob) -> RequirementPreviewJobResponse:
    context = job.context_json if isinstance(job.context_json, dict) else {}
    batch = None
    batch_id = str(context.get("preview_batch_id") or "").strip()
    if batch_id:
        loaded = _get_import_batch(db, job.workspace_id, batch_id)
        if loaded:
            batch = _import_batch_response(loaded)
    return RequirementPreviewJobResponse(
        job_id=job.id,
        workspace_id=job.workspace_id,
        status=_enum_value(job.status),
        progress=int(job.progress or 0),
        message=job.message,
        error=job.error_message,
        batch=batch,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def get_requirement_preview_job(db: Session, workspace_id: str, job_id: str) -> Optional[RequirementPreviewJobResponse]:
    job = (
        db.query(SddAiJob)
        .filter(
            SddAiJob.workspace_id == workspace_id,
            SddAiJob.id == job_id,
        )
        .first()
    )
    context = job.context_json if job and isinstance(job.context_json, dict) else {}
    if context.get("job_kind") not in {"REQUIREMENT_IMPORT_PREVIEW", "REQUIREMENT_SPLIT_PREVIEW"}:
        return None
    return _preview_job_response(db, job) if job else None


def _extract_json_object(text: str) -> Dict[str, Any]:
    candidate = str(text or "").strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE).strip()
        candidate = re.sub(r"\s*```$", "", candidate).strip()
    if not (candidate.startswith("{") and candidate.endswith("}")):
        match = re.search(r"\{[\s\S]*\}", candidate)
        if match:
            candidate = match.group(0).strip()
    parsed = json.loads(candidate)
    if not isinstance(parsed, dict):
        raise ValueError("AI preview response must be a JSON object")
    return parsed


def _normalize_ai_preview_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("AI preview response must include an items array")

    items: List[Dict[str, Any]] = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            continue
        title = _clean_optional(raw.get("title"), limit=300)
        body = _clean_optional(raw.get("body"))
        if not title:
            title = _clean_optional(str(body or "").splitlines()[0] if body else None, limit=300)
        if not title:
            continue
        source_metadata = raw.get("source_metadata") if isinstance(raw.get("source_metadata"), dict) else {}
        task_prompt = _clean_optional(raw.get("task_prompt") or raw.get("taskPrompt"))
        if task_prompt:
            source_metadata = {**source_metadata, "task_prompt": task_prompt}
        source_metadata = {
            **source_metadata,
            "ai_split": True,
            "ai_segment_index": index,
        }
        items.append(
            {
                "title": title,
                "body": body,
                "acceptance_criteria": _normalize_list(raw.get("acceptance_criteria") or raw.get("acceptanceCriteria")),
                "priority": _clean_optional(raw.get("priority"), limit=40),
                "source_ref": _clean_optional(raw.get("source_ref") or raw.get("sourceRef"), limit=300) or f"ai:{index + 1}",
                "source_metadata": source_metadata,
                "order_index": index,
            }
        )
    if not items:
        raise ValueError("AI preview did not produce valid Requirement preview items")
    return items


def _looks_like_single_requirement(markdown: str) -> bool:
    text = re.sub(r"\s+", " ", str(markdown or "")).strip()
    if not text or len(text) > 900:
        return False
    headings = [
        line for line in str(markdown or "").splitlines()
        if _HEADING_RE.match(line.strip())
    ]
    if len(headings) > 1:
        return False
    explicit_requirement_markers = re.findall(
        r"(?im)^\s*(?:REQ(?:UIREMENT)?[-_\s]*\d+|需求\s*\d+)[:：\.\)]",
        str(markdown or ""),
    )
    numbered_items = re.findall(r"(?m)^\s*\d+[\.\)]\s+\S", str(markdown or ""))
    return len(explicit_requirement_markers) <= 1 and len(numbered_items) <= 1


def _coalesce_simple_import_preview_items(
    *,
    markdown: str,
    file_name: Optional[str],
    items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if len(items) <= 1 or not _looks_like_single_requirement(markdown):
        return items
    first_item = items[0]
    source_metadata = first_item.get("source_metadata") if isinstance(first_item.get("source_metadata"), dict) else {}
    task_prompt = _clean_optional(source_metadata.get("task_prompt")) or _clean_optional(
        first_item.get("task_prompt")
    ) or f"Implement Requirement: {_direct_import_title(file_name or 'Requirement', markdown)}"
    return [
        {
            "title": _direct_import_title(file_name or "Requirement", markdown),
            "body": markdown,
            "acceptance_criteria": _extract_acceptance_criteria(str(markdown or "").splitlines()),
            "priority": _clean_optional(first_item.get("priority"), limit=40),
            "source_ref": first_item.get("source_ref") or "ai:1",
            "source_metadata": {
                **source_metadata,
                "ai_preview": True,
                "ai_split": False,
                "original_ai_item_count": len(items),
                "split_decision": "kept_single_simple_requirement",
                "task_prompt": task_prompt,
            },
            "order_index": 0,
        }
    ]


def _build_requirement_preview_prompt(
    *,
    mode: str,
    markdown: str,
    source_kind: Optional[str],
    source_ref: Optional[str],
    source_uri: Optional[str],
    file_name: Optional[str],
) -> str:
    return (
        "你是 SDD-Native Workspace Assets 的 Requirements 拆分助手。\n"
        "目标：把输入需求整理成可追踪 Requirement 预览项，并为后续创建 Task 生成提示词。\n\n"
        "硬性边界：\n"
        "1. 只输出 JSON，不要输出 Markdown 解释。\n"
        "2. 只做 Requirement 拆分，不创建 Task，不创建 Coverage，不创建 Evidence，不标记 Verified。\n"
        "3. 不修改原文业务含义，不减少文档内容。\n"
        "4. 不要为了拆分而拆分：如果输入已经是一条清晰、短小、可独立追踪的需求，必须只返回 1 个 item。\n"
        "5. 只有当原文明确包含多个可独立实现、独立验收、独立追踪的需求时，才拆成多条。\n"
        "6. 如果拆成多条，每条都必须保留理解该需求所需的背景；允许复制公共背景到多个条目。\n"
        "7. task_prompt 仅供后续创建 Task 使用，不能暗示平台会自动提交代码。\n\n"
        "输出 JSON 格式：\n"
        "{\n"
        '  "items": [\n'
        "    {\n"
        '      "title": "需求标题",\n'
        '      "body": "完整需求正文，保留必要背景",\n'
        '      "acceptance_criteria": ["验收标准，可为空数组"],\n'
        '      "priority": null,\n'
        '      "source_ref": "来源段落或编号",\n'
        '      "source_metadata": {"split_reason": "拆分理由"},\n'
        '      "task_prompt": "后续创建 Task 时可使用的实现提示词"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        f"Preview mode: {mode}\n"
        f"Source kind: {source_kind or 'document'}\n"
        f"Source file: {file_name or ''}\n"
        f"Source ref: {source_ref or ''}\n"
        f"Source uri: {source_uri or ''}\n\n"
        "输入需求正文如下：\n"
        "----- BEGIN REQUIREMENT DOCUMENT -----\n"
        f"{markdown}\n"
        "----- END REQUIREMENT DOCUMENT -----\n"
    )


def _workspace_project_path_or_error(db: Session, workspace_id: str) -> str:
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    project_path = str((workspace.project_path if workspace else "") or "").strip()
    if not project_path or not os.path.isdir(project_path):
        raise WorkspaceAssetWriteError(
            "Workspace project_path is required for AI preview and must point to an existing directory.",
            status_code=409,
        )
    return os.path.abspath(project_path)


def _create_requirement_preview_batch(
    db: Session,
    *,
    workspace_id: str,
    actor_id: Optional[str],
    file_name: Optional[str],
    markdown: str,
    source_kind: Optional[str],
    source_uri: Optional[str],
    source_ref: Optional[str],
    source_metadata: Dict[str, Any],
    items: List[Dict[str, Any]],
    audit_action: RequirementAuditAction,
    requirement_id: Optional[str] = None,
    reason: Optional[str] = None,
) -> SddRequirementImportBatch:
    batch = SddRequirementImportBatch(
        workspace_id=workspace_id,
        created_by_id=actor_id,
        source_kind=_clean_optional(source_kind, limit=80) or "document",
        source_filename=_clean_optional(file_name, limit=500),
        source_uri=_clean_optional(source_uri, limit=1000),
        source_ref=_clean_optional(source_ref, limit=300),
        source_metadata_json=source_metadata,
        normalized_markdown=markdown,
        status=RequirementImportBatchStatus.PREVIEW,
        item_count=len(items),
        confirmed_count=0,
    )
    db.add(batch)
    db.flush()
    for item_data in items:
        db.add(
            SddRequirementImportItem(
                workspace_id=workspace_id,
                batch_id=batch.id,
                title=item_data["title"],
                body=item_data.get("body"),
                acceptance_criteria_json=item_data.get("acceptance_criteria") or [],
                priority=_clean_optional(item_data.get("priority"), limit=40),
                source_ref=item_data.get("source_ref"),
                source_metadata_json=item_data.get("source_metadata"),
                order_index=int(item_data.get("order_index") or 0),
                status=RequirementImportItemStatus.PENDING,
            )
        )
    _add_requirement_audit(
        db,
        workspace_id=workspace_id,
        requirement_id=requirement_id,
        import_batch_id=batch.id,
        actor_id=actor_id,
        action=audit_action,
        after={"item_count": len(items), "source_filename": file_name},
        reason=reason,
        source_metadata=source_metadata,
    )
    return batch


def _parsed_document(file_name: str, raw: bytes) -> Dict[str, Any]:
    if not file_name.lower().endswith((".docx", ".md", ".markdown", ".txt")):
        raise WorkspaceAssetWriteError("Requirement import supports DOCX, Markdown and Text files only.", status_code=415)
    parsed = parse_document_payload(file_name, raw)
    markdown = str(parsed.get("normalized_markdown") or "").strip()
    if not markdown:
        raise WorkspaceAssetWriteError("No requirement content could be parsed from the provided document.", status_code=422)
    return parsed


def _document_metadata(parsed: Dict[str, Any], *, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "source_ext": parsed.get("source_ext"),
        "source_mime": parsed.get("source_mime"),
        "render": parsed.get("render_json"),
        **(extra or {}),
    }


def _direct_import_title(file_name: str, markdown: str) -> str:
    for line in str(markdown or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        heading = _HEADING_RE.match(stripped)
        if heading:
            return (_clean_optional(heading.group(2), limit=300) or "Imported Requirement")
        return (_clean_optional(_strip_marker(stripped), limit=300) or "Imported Requirement")
    base = os.path.splitext(os.path.basename(file_name or ""))[0]
    return _clean_optional(base, limit=300) or "Imported Requirement"


def create_requirement_direct_import(
    db: Session,
    workspace_id: str,
    actor_id: Optional[str],
    *,
    file_name: str,
    raw: bytes,
    source_kind: Optional[str] = None,
    source_uri: Optional[str] = None,
    source_ref: Optional[str] = None,
    change_reason: Optional[str] = None,
) -> RequirementDetailResponse:
    parsed = _parsed_document(file_name, raw)
    markdown = str(parsed.get("normalized_markdown") or "").strip()
    requirement = SddRequirement(
        workspace_id=workspace_id,
        created_by_id=actor_id,
        title=_direct_import_title(file_name, markdown),
        body=markdown,
        status=RequirementStatus.DRAFT,
        acceptance_criteria_json=_extract_acceptance_criteria(markdown.splitlines()),
        priority=None,
        source_kind=_clean_optional(source_kind, limit=80) or "document",
        source_uri=_clean_optional(source_uri, limit=1000),
        source_ref=_clean_optional(source_ref, limit=300),
        source_metadata_json=_document_metadata(parsed, extra={"created_from": "direct_import", "source_filename": file_name}),
    )
    db.add(requirement)
    db.flush()
    _add_requirement_audit(
        db,
        workspace_id=workspace_id,
        requirement_id=requirement.id,
        actor_id=actor_id,
        action=RequirementAuditAction.CREATED,
        after=_requirement_snapshot(requirement),
        reason=change_reason,
        source_metadata={"created_from": "direct_import", "source_filename": file_name},
    )
    db.commit()
    result = get_requirement_detail(db, workspace_id, requirement.id)
    if not result:
        raise WorkspaceAssetWriteError("Imported Requirement could not be loaded.", status_code=500)
    return result


def create_requirement_import_preview_job(
    db: Session,
    workspace_id: str,
    actor_id: str,
    *,
    file_name: str,
    raw: bytes,
    source_kind: Optional[str] = None,
    source_uri: Optional[str] = None,
    source_ref: Optional[str] = None,
) -> RequirementPreviewJobResponse:
    project_path = _workspace_project_path_or_error(db, workspace_id)
    job = SddAiJob(
        workspace_id=workspace_id,
        task_id=None,
        asset_id=None,
        thread_id=None,
        channel=AiJobChannel.ASSET_THREAD,
        queue_key=f"REQUIREMENT_PREVIEW:{workspace_id}",
        status=AiJobStatus.PENDING,
        progress=0,
        message="Requirement AI preview queued",
        context_json={
            "job_kind": "REQUIREMENT_IMPORT_PREVIEW",
            "project_path": project_path,
            "source_kind": source_kind or "document",
            "source_filename": file_name,
            "source_uri": source_uri,
            "source_ref": source_ref,
        },
        creator_id=actor_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return _preview_job_response(db, job)


def create_requirement_split_preview_job(
    db: Session,
    workspace_id: str,
    requirement_id: str,
    actor_id: str,
    change_reason: Optional[str] = None,
) -> Optional[RequirementPreviewJobResponse]:
    requirement = _get_requirement(db, workspace_id, requirement_id)
    if not requirement:
        return None
    project_path = _workspace_project_path_or_error(db, workspace_id)
    job = SddAiJob(
        workspace_id=workspace_id,
        task_id=None,
        asset_id=None,
        thread_id=None,
        channel=AiJobChannel.ASSET_THREAD,
        queue_key=f"REQUIREMENT_PREVIEW:{workspace_id}",
        status=AiJobStatus.PENDING,
        progress=0,
        message="Requirement split preview queued",
        context_json={
            "job_kind": "REQUIREMENT_SPLIT_PREVIEW",
            "project_path": project_path,
            "requirement_id": requirement.id,
            "source_kind": "split",
            "source_uri": requirement.source_uri,
            "source_ref": requirement.id,
            "change_reason": change_reason,
        },
        creator_id=actor_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return _preview_job_response(db, job)


def _update_preview_job_state(
    db: Session,
    job: SddAiJob,
    *,
    status: Optional[AiJobStatus] = None,
    progress: Optional[int] = None,
    message: Optional[str] = None,
    error: Optional[str] = None,
    context_patch: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
) -> None:
    if status is not None:
        job.status = status
        if status == AiJobStatus.RUNNING and job.started_at is None:
            job.started_at = datetime.utcnow()
        if status in {AiJobStatus.SUCCESS, AiJobStatus.FAILED, AiJobStatus.CANCELLED}:
            job.finished_at = datetime.utcnow()
    if progress is not None:
        job.progress = max(0, min(100, int(progress)))
    if message is not None:
        job.message = message
    if error is not None:
        job.error_message = error
    if context_patch:
        context = job.context_json if isinstance(job.context_json, dict) else {}
        job.context_json = {**context, **context_patch}
    if result is not None:
        job.result_json = result
    db.commit()
    db.refresh(job)


async def run_requirement_import_preview_job(
    job_id: str,
    *,
    file_name: str,
    raw: bytes,
    source_kind: Optional[str],
    source_uri: Optional[str],
    source_ref: Optional[str],
) -> None:
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job:
            return
        try:
            _update_preview_job_state(db, job, status=AiJobStatus.RUNNING, progress=8, message="Parsing requirement document")
            parsed = _parsed_document(file_name, raw)
            markdown = str(parsed.get("normalized_markdown") or "").strip()
            project_path = _workspace_project_path_or_error(db, job.workspace_id)
            prompt = _build_requirement_preview_prompt(
                mode="import",
                markdown=markdown,
                source_kind=source_kind,
                source_ref=source_ref,
                source_uri=source_uri,
                file_name=file_name,
            )
            job.prompt_text = prompt
            _update_preview_job_state(db, job, progress=28, message="Running Claude Code CLI requirement preview")
            ai_result = await run_cli_single_turn(prompt, project_path, max_attempts=1)
            parsed_json = _extract_json_object(str(ai_result.get("text") or ""))
            items = _normalize_ai_preview_items(parsed_json)
            items = _coalesce_simple_import_preview_items(
                markdown=markdown,
                file_name=file_name,
                items=items,
            )
            metadata = _document_metadata(
                parsed,
                extra={
                    "ai_preview": True,
                    "ai_job_id": job.id,
                    "splitter": "claude-code-cli",
                    "session_id": ai_result.get("session_id"),
                },
            )
            batch = _create_requirement_preview_batch(
                db,
                workspace_id=job.workspace_id,
                actor_id=job.creator_id,
                file_name=file_name,
                markdown=markdown,
                source_kind=source_kind,
                source_uri=source_uri,
                source_ref=source_ref,
                source_metadata=metadata,
                items=items,
                audit_action=RequirementAuditAction.IMPORT_PREVIEW_CREATED,
            )
            _update_preview_job_state(
                db,
                job,
                status=AiJobStatus.SUCCESS,
                progress=100,
                message="Requirement AI preview created",
                context_patch={"preview_batch_id": batch.id},
                result={"item_count": len(items), "batch_id": batch.id},
            )
        except Exception as exc:
            db.rollback()
            _update_preview_job_state(
                db,
                job,
                status=AiJobStatus.FAILED,
                progress=100,
                message="Requirement AI preview failed",
                error=str(exc),
            )
    finally:
        db.close()


async def run_requirement_split_preview_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job:
            return
        context = job.context_json if isinstance(job.context_json, dict) else {}
        requirement_id = str(context.get("requirement_id") or "").strip()
        try:
            requirement = _get_requirement(db, job.workspace_id, requirement_id)
            if not requirement:
                raise WorkspaceAssetWriteError("Requirement not found", status_code=404)
            content = (requirement.body or requirement.title or "").strip()
            if not content:
                raise WorkspaceAssetWriteError("Requirement content is required for AI split preview.", status_code=422)
            project_path = _workspace_project_path_or_error(db, job.workspace_id)
            _update_preview_job_state(db, job, status=AiJobStatus.RUNNING, progress=16, message="Running Claude Code CLI split preview")
            prompt = _build_requirement_preview_prompt(
                mode="split",
                markdown=content,
                source_kind="split",
                source_ref=requirement.id,
                source_uri=requirement.source_uri,
                file_name=None,
            )
            job.prompt_text = prompt
            ai_result = await run_cli_single_turn(prompt, project_path, max_attempts=1)
            parsed_json = _extract_json_object(str(ai_result.get("text") or ""))
            items = _normalize_ai_preview_items(parsed_json)
            if len(items) <= 1:
                raise WorkspaceAssetWriteError("AI split preview must produce at least two Requirement preview items.", status_code=422)
            metadata = {
                **(requirement.source_metadata_json or {}),
                "parent_requirement_id": requirement.id,
                "ai_preview": True,
                "ai_job_id": job.id,
                "splitter": "claude-code-cli",
                "session_id": ai_result.get("session_id"),
            }
            for item in items:
                item["source_metadata"] = {
                    **(item.get("source_metadata") or {}),
                    "parent_requirement_id": requirement.id,
                }
            batch = _create_requirement_preview_batch(
                db,
                workspace_id=job.workspace_id,
                actor_id=job.creator_id,
                file_name=None,
                markdown=content,
                source_kind="split",
                source_uri=requirement.source_uri,
                source_ref=requirement.id,
                source_metadata=metadata,
                items=items,
                audit_action=RequirementAuditAction.SPLIT_PREVIEW_CREATED,
                requirement_id=requirement.id,
                reason=context.get("change_reason"),
            )
            _update_preview_job_state(
                db,
                job,
                status=AiJobStatus.SUCCESS,
                progress=100,
                message="Requirement split preview created",
                context_patch={"preview_batch_id": batch.id},
                result={"item_count": len(items), "batch_id": batch.id},
            )
        except Exception as exc:
            db.rollback()
            _update_preview_job_state(
                db,
                job,
                status=AiJobStatus.FAILED,
                progress=100,
                message="Requirement split preview failed",
                error=str(exc),
            )
    finally:
        db.close()


def create_requirement_import_preview(
    db: Session,
    workspace_id: str,
    actor_id: Optional[str],
    *,
    file_name: str,
    raw: bytes,
    source_kind: Optional[str] = None,
    source_uri: Optional[str] = None,
    source_ref: Optional[str] = None,
) -> RequirementImportBatchResponse:
    raise WorkspaceAssetWriteError(
        "Requirement preview must use the asynchronous AI preview job.",
        status_code=410,
    )


def _get_import_batch(db: Session, workspace_id: str, batch_id: str) -> Optional[SddRequirementImportBatch]:
    return (
        db.query(SddRequirementImportBatch)
        .options(selectinload(SddRequirementImportBatch.items))
        .filter(SddRequirementImportBatch.workspace_id == workspace_id, SddRequirementImportBatch.id == batch_id)
        .first()
    )


def confirm_requirement_import(
    db: Session,
    workspace_id: str,
    batch_id: str,
    actor_id: Optional[str],
    payload: RequirementImportConfirmRequest,
) -> Optional[RequirementImportBatchResponse]:
    batch = _get_import_batch(db, workspace_id, batch_id)
    if not batch:
        return None
    if _enum_value(batch.status) != RequirementImportBatchStatus.PREVIEW.value:
        raise WorkspaceAssetWriteError("Import batch has already been confirmed or closed.", status_code=409)

    provided = {item.item_id: item for item in payload.items}
    selected_items = []
    for item in sorted(batch.items or [], key=lambda current: current.order_index):
        override = provided.get(item.id)
        include = (override is not None and bool(override.include)) if payload.items else True
        if include:
            selected_items.append((item, override))
        else:
            item.status = RequirementImportItemStatus.SKIPPED

    def _import_item_values(
        item: SddRequirementImportItem,
        override: Optional[Any],
    ) -> Optional[Dict[str, Any]]:
        title = _clean_optional((override.title if override and override.title is not None else item.title), limit=300)
        if not title:
            item.status = RequirementImportItemStatus.SKIPPED
            return None
        body = override.body if override and override.body is not None else item.body
        criteria = override.acceptance_criteria if override and override.acceptance_criteria is not None else item.acceptance_criteria_json
        priority = override.priority if override and override.priority is not None else item.priority
        status_value = override.status if override else "DRAFT"
        item_metadata = item.source_metadata_json if isinstance(item.source_metadata_json, dict) else {}
        if override and override.task_prompt is not None:
            item_metadata = {**item_metadata, "task_prompt": _clean_optional(override.task_prompt)}
            item.source_metadata_json = item_metadata
        return {
            "title": title,
            "body": body,
            "criteria": criteria,
            "priority": priority,
            "status": status_value,
            "source_ref": item.source_ref,
            "metadata": item_metadata,
        }

    created_count = 0
    selected_values = [
        (item, values)
        for item, override in selected_items
        if (values := _import_item_values(item, override)) is not None
    ]

    if len(selected_values) > 1:
        parent_title = _direct_import_title(batch.source_filename or "Imported Requirement", batch.normalized_markdown or "")
        parent = SddRequirement(
            workspace_id=workspace_id,
            created_by_id=actor_id,
            title=parent_title,
            body=_clean_optional(batch.normalized_markdown),
            status=RequirementStatus.DRAFT,
            acceptance_criteria_json=_extract_acceptance_criteria(str(batch.normalized_markdown or "").splitlines()),
            priority=None,
            import_batch_id=batch.id,
            source_kind=batch.source_kind,
            source_uri=batch.source_uri,
            source_ref=batch.source_ref,
            source_metadata_json={
                **(batch.source_metadata_json or {}),
                "source_filename": batch.source_filename,
                "created_from": "import_confirm_parent",
                "preview_item_count": len(selected_values),
            },
        )
        db.add(parent)
        db.flush()
        _add_requirement_audit(
            db,
            workspace_id=workspace_id,
            requirement_id=parent.id,
            import_batch_id=batch.id,
            actor_id=actor_id,
            action=RequirementAuditAction.CREATED,
            after=_requirement_snapshot(parent),
            reason=payload.change_reason,
            source_metadata={"created_from": "import_confirm_parent"},
        )

        for item, values in selected_values:
            child = SddRequirement(
                workspace_id=workspace_id,
                created_by_id=actor_id,
                title=values["title"],
                body=_clean_optional(values["body"]),
                status=_normalize_status(values["status"]),
                acceptance_criteria_json=_normalize_list(values["criteria"]),
                priority=_clean_optional(values["priority"], limit=40),
                parent_requirement_id=parent.id,
                import_batch_id=batch.id,
                source_kind=batch.source_kind,
                source_uri=batch.source_uri,
                source_ref=values["source_ref"] or batch.source_ref,
                source_metadata_json={
                    **(batch.source_metadata_json or {}),
                    **values["metadata"],
                    "source_filename": batch.source_filename,
                    "parent_requirement_id": parent.id,
                    "created_from": "import_confirm_child",
                },
            )
            db.add(child)
            db.flush()
            item.requirement_id = child.id
            item.status = RequirementImportItemStatus.CONFIRMED
            created_count += 1
            _add_requirement_audit(
                db,
                workspace_id=workspace_id,
                requirement_id=child.id,
                import_batch_id=batch.id,
                actor_id=actor_id,
                action=RequirementAuditAction.CREATED,
                after=_requirement_snapshot(child),
                reason=payload.change_reason,
                source_metadata={"created_from": "import_confirm_child", "parent_requirement_id": parent.id},
            )
    else:
        for item, values in selected_values:
            requirement = SddRequirement(
                workspace_id=workspace_id,
                created_by_id=actor_id,
                title=values["title"],
                body=_clean_optional(values["body"]),
                status=_normalize_status(values["status"]),
                acceptance_criteria_json=_normalize_list(values["criteria"]),
                priority=_clean_optional(values["priority"], limit=40),
                import_batch_id=batch.id,
                source_kind=batch.source_kind,
                source_uri=batch.source_uri,
                source_ref=values["source_ref"] or batch.source_ref,
                source_metadata_json={
                    **(batch.source_metadata_json or {}),
                    **values["metadata"],
                    "source_filename": batch.source_filename,
                    "created_from": "import_confirm_single",
                },
            )
            db.add(requirement)
            db.flush()
            item.requirement_id = requirement.id
            item.status = RequirementImportItemStatus.CONFIRMED
            created_count += 1
            _add_requirement_audit(
                db,
                workspace_id=workspace_id,
                requirement_id=requirement.id,
                import_batch_id=batch.id,
                actor_id=actor_id,
                action=RequirementAuditAction.CREATED,
                after=_requirement_snapshot(requirement),
                reason=payload.change_reason,
                source_metadata={"created_from": "import_confirm_single"},
            )

    batch.status = RequirementImportBatchStatus.CONFIRMED
    batch.confirmed_count = created_count
    _add_requirement_audit(
        db,
        workspace_id=workspace_id,
        import_batch_id=batch.id,
        actor_id=actor_id,
        action=RequirementAuditAction.IMPORT_CONFIRMED,
        after={"confirmed_count": created_count},
        reason=payload.change_reason,
    )
    db.commit()
    refreshed = _get_import_batch(db, workspace_id, batch_id)
    return _import_batch_response(refreshed) if refreshed else None


def create_requirement_split_preview(
    db: Session,
    workspace_id: str,
    requirement_id: str,
    actor_id: Optional[str],
    change_reason: Optional[str] = None,
) -> Optional[RequirementImportBatchResponse]:
    raise WorkspaceAssetWriteError(
        "Requirement split preview must use the asynchronous AI preview job.",
        status_code=410,
    )


def confirm_requirement_split(
    db: Session,
    workspace_id: str,
    requirement_id: str,
    actor_id: Optional[str],
    payload: RequirementSplitRequest,
) -> Optional[RequirementImportBatchResponse]:
    parent = _get_requirement(db, workspace_id, requirement_id)
    if not parent:
        return None
    batch = _get_import_batch(db, workspace_id, payload.batch_id)
    if not batch:
        raise WorkspaceAssetWriteError("Split preview batch not found.", status_code=404)
    if batch.source_ref != requirement_id or batch.source_kind != "split":
        raise WorkspaceAssetWriteError("Split preview batch does not belong to this Requirement.", status_code=409)
    if _enum_value(batch.status) != RequirementImportBatchStatus.PREVIEW.value:
        raise WorkspaceAssetWriteError("Split batch has already been confirmed or closed.", status_code=409)

    provided = {item.item_id: item for item in payload.items}
    created_count = 0
    for item in sorted(batch.items or [], key=lambda current: current.order_index):
        override = provided.get(item.id)
        if override is not None and not override.include:
            item.status = RequirementImportItemStatus.SKIPPED
            continue
        title = _clean_optional((override.title if override and override.title is not None else item.title), limit=300)
        if not title:
            item.status = RequirementImportItemStatus.SKIPPED
            continue
        body = override.body if override and override.body is not None else item.body
        criteria = override.acceptance_criteria if override and override.acceptance_criteria is not None else item.acceptance_criteria_json
        priority = override.priority if override and override.priority is not None else item.priority
        item_metadata = item.source_metadata_json if isinstance(item.source_metadata_json, dict) else {}
        if override and override.task_prompt is not None:
            item_metadata = {**item_metadata, "task_prompt": _clean_optional(override.task_prompt)}
            item.source_metadata_json = item_metadata
        child = SddRequirement(
            workspace_id=workspace_id,
            created_by_id=actor_id,
            title=title,
            body=_clean_optional(body),
            status=RequirementStatus.DRAFT,
            acceptance_criteria_json=_normalize_list(criteria),
            priority=_clean_optional(priority, limit=40),
            parent_requirement_id=parent.id,
            import_batch_id=batch.id,
            source_kind=parent.source_kind or "split",
            source_uri=parent.source_uri,
            source_ref=item.source_ref or parent.source_ref,
            source_metadata_json={
                **(parent.source_metadata_json or {}),
                **item_metadata,
                "parent_requirement_id": parent.id,
            },
        )
        db.add(child)
        db.flush()
        item.requirement_id = child.id
        item.status = RequirementImportItemStatus.CONFIRMED
        created_count += 1
        _add_requirement_audit(
            db,
            workspace_id=workspace_id,
            requirement_id=child.id,
            import_batch_id=batch.id,
            actor_id=actor_id,
            action=RequirementAuditAction.CREATED,
            after=_requirement_snapshot(child),
            reason=payload.change_reason,
            source_metadata={"created_from": "split_confirm", "parent_requirement_id": parent.id},
        )
    batch.status = RequirementImportBatchStatus.CONFIRMED
    batch.confirmed_count = created_count
    _add_requirement_audit(
        db,
        workspace_id=workspace_id,
        requirement_id=parent.id,
        import_batch_id=batch.id,
        actor_id=actor_id,
        action=RequirementAuditAction.SPLIT_CONFIRMED,
        after={"confirmed_count": created_count},
        reason=payload.change_reason,
    )
    db.commit()
    refreshed = _get_import_batch(db, workspace_id, batch.id)
    return _import_batch_response(refreshed) if refreshed else None


def get_task_detail(db: Session, workspace_id: str, task_id: str) -> Optional[TaskDetailResponse]:
    task = (
        db.query(SddTask)
        .options(
            selectinload(SddTask.requirement_links).selectinload(SddTaskRequirement.requirement),
            selectinload(SddTask.ai_jobs).selectinload(SddAiJob.outputs),
            selectinload(SddTask.ai_outputs),
            selectinload(SddTask.human_reviews).selectinload(SddHumanReview.comments),
            selectinload(SddTask.human_deltas).selectinload(SddHumanDelta.decisions),
            selectinload(SddTask.evidence_items),
            selectinload(SddTask.decisions),
            selectinload(SddTask.clarifications),
            selectinload(SddTask.final_summary),
            selectinload(SddTask.process_audit_logs),
            selectinload(SddTask.change_proposals).selectinload(SddTaskChangeProposal.files),
            selectinload(SddTask.verification_runs),
            selectinload(SddTask.conflict_reports),
        )
        .filter(SddTask.workspace_id == workspace_id, SddTask.id == task_id)
        .first()
    )
    if not task:
        return None

    specs = (
        db.query(SddAsset)
        .filter(SddAsset.workspace_id == workspace_id, SddAsset.task_id == task_id, SddAsset.asset_type == AssetType.SPEC)
        .order_by(SddAsset.created_at.desc())
        .all()
    )
    plans = (
        db.query(SddAsset)
        .filter(SddAsset.workspace_id == workspace_id, SddAsset.task_id == task_id, SddAsset.asset_type == AssetType.PLAN)
        .order_by(SddAsset.created_at.desc())
        .all()
    )
    plan_nodes = (
        db.query(SddPlanNode)
        .filter(SddPlanNode.workspace_id == workspace_id, SddPlanNode.task_id == task_id)
        .order_by(SddPlanNode.order_index.asc(), SddPlanNode.created_at.asc())
        .all()
    )

    ai_runs = sorted(task.ai_jobs or [], key=lambda item: item.created_at, reverse=True)
    ai_outputs = sorted(task.ai_outputs or [], key=lambda item: item.created_at, reverse=True)
    reviews = sorted(task.human_reviews or [], key=lambda item: item.created_at, reverse=True)
    deltas = sorted(task.human_deltas or [], key=lambda item: item.created_at, reverse=True)
    evidence = sorted(task.evidence_items or [], key=lambda item: item.created_at, reverse=True)
    decisions = sorted(task.decisions or [], key=lambda item: item.created_at, reverse=True)
    clarifications = sorted(task.clarifications or [], key=lambda item: item.created_at, reverse=True)
    requirement_links = sorted(task.requirement_links or [], key=lambda item: item.created_at, reverse=True)
    change_proposals = sorted(task.change_proposals or [], key=lambda item: item.created_at, reverse=True)
    verification_runs = sorted(task.verification_runs or [], key=lambda item: item.created_at, reverse=True)
    conflict_reports = sorted(task.conflict_reports or [], key=lambda item: item.created_at, reverse=True)

    task_summary = _task_summary(db, task)
    process_summary = TaskProcessSummary(
        spec_status="available" if specs else "empty",
        plan_status="available" if plans or plan_nodes else "empty",
        ai_run_status="available" if ai_runs else "empty",
        human_review_status="available" if reviews else "empty",
        human_delta_status="available" if deltas else "empty",
        evidence_status="available" if evidence else "empty",
        coverage_status=task_summary.coverage_status,
        risk_status="not_available",
    )

    return TaskDetailResponse(
        task=task_summary,
        requirement_links=[_task_requirement_link(item) for item in requirement_links],
        task_files=workspace_task_detail_service.task_file_items(
            specs=specs,
            plans=plans,
            ai_outputs=ai_outputs,
            change_proposals=change_proposals,
            verification_runs=verification_runs,
            conflict_reports=conflict_reports,
        ),
        specs=[_asset_summary(item) for item in specs],
        plans=[_asset_summary(item) for item in plans],
        plan_nodes=[_plan_node_summary(item) for item in plan_nodes],
        ai_runs=[_ai_run_summary(item) for item in ai_runs],
        ai_outputs=[_ai_output_response(item) for item in ai_outputs],
        human_reviews=[_human_review_response(item) for item in reviews],
        human_deltas=[_human_delta_response(item) for item in deltas],
        evidence=[_evidence_response(item) for item in evidence],
        decisions=[_decision_response(item) for item in decisions],
        clarifications=[_clarification_response(item) for item in clarifications],
        final_summary=_final_summary_response(task.final_summary) if task.final_summary else None,
        process_audit_logs=[_process_audit_response(item) for item in (task.process_audit_logs or [])],
        process_summary=process_summary,
        connection_status=[
            _connection(
                "task_process_assets",
                "Task process assets",
                "AVAILABLE" if any([specs, plans, plan_nodes, ai_runs, reviews, deltas, evidence]) else "EMPTY",
                "Real process records are available."
                if any([specs, plans, plan_nodes, ai_runs, reviews, deltas, evidence])
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
        ],
    )


def _evidence_registry_items(evidence_items: List[SddEvidence]) -> List[Dict[str, Any]]:
    return [
        {
            "id": item.id,
            "requirement_id": item.requirement_id,
            "task_id": item.task_id,
            "ai_job_id": item.ai_job_id,
            "status": _enum_value(item.status),
            "source": _external_evidence_ref(item).model_dump(),
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
            "status": _enum_value(item.status),
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
    return [item for item in (task.assets or []) if _enum_value(item.asset_type) == asset_type.value]


def _dedupe_by_id(items: Iterable[Any]) -> List[Any]:
    seen = set()
    result = []
    for item in items:
        item_id = getattr(item, "id", None)
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        result.append(item)
    return result


def _has_rejected_review(task: Optional[SddTask]) -> bool:
    if not task:
        return False
    rejected_values = {"reject", "rejected", "request_changes", "changes_requested"}
    for review in task.human_reviews or []:
        if _enum_value(review.outcome) == HumanReviewOutcome.REJECT.value:
            return True
        if (review.review_type or "").strip().lower() in rejected_values:
            return True
        source_ref = review.source_ref_json if isinstance(review.source_ref_json, dict) else {}
        for key in ("status", "decision", "result", "outcome"):
            if str(source_ref.get(key, "")).strip().lower() in rejected_values:
                return True
    return False


def _matrix_coverage_status(
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
    has_rejection = any(_enum_value(item.status) == DecisionStatus.REJECTED.value for item in decisions)
    if has_rejection or _has_rejected_review(task):
        return "rejected", "Rejected status is traceable to a real Human Review or Decision."
    if any(_enum_value(item.status) == ClarificationStatus.OPEN.value for item in clarifications):
        return "need_clarification", "Open Clarification exists for this Requirement and Task path."
    if any(_is_human_confirmation(item) for item in evidence_items):
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
    evidence_items = _dedupe_by_id([
        *(requirement.evidence_items or []),
        *((task.evidence_items or []) if task else []),
    ])
    decisions = list(task.decisions or []) if task else []
    clarifications = list(task.clarifications or []) if task else []
    coverage_status, coverage_reason = _matrix_coverage_status(
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
        relation_type=_enum_value(link.relation_type) if link else None,
        spec_status="available" if specs else "empty",
        plan_status="available" if plan_assets or plan_nodes else "empty",
        ai_run_status="available" if ai_runs else "empty",
        human_review_status="available" if reviews else "empty",
        human_delta_status="available" if deltas else "empty",
        evidence_status="available" if evidence_items else "empty",
        coverage_status=coverage_status,
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
                state=_collection_state(len(coverage_items), "Waiting for Requirement and Task links."),
            ),
            TraceabilityViewResponse(
                key="evidence_registry",
                title="Evidence Registry",
                view_type="derived_registry",
                items=evidence_registry_items,
                total=len(evidence_registry_items),
                state=_collection_state(len(evidence_registry_items), "Waiting for real Evidence references."),
            ),
            TraceabilityViewResponse(
                key="human_delta_dashboard",
                title="Human Delta Dashboard",
                view_type="derived_dashboard",
                items=delta_items,
                total=len(delta_items),
                state=_collection_state(len(delta_items), "Waiting for Human Delta records."),
            ),
            TraceabilityViewResponse(
                key="risk_board",
                title="Risk Board",
                view_type="derived_board",
                items=[],
                total=0,
                state=_collection_state(0, "Risk Board requires real task, evidence and review signals."),
            ),
        ],
        connection_status=[
            _connection(
                "traceable_assets",
                "Traceable assets",
                "AVAILABLE" if any([requirements, links, evidence_items, deltas]) else "EMPTY",
                "Traceability is derived from real asset records."
                if any([requirements, links, evidence_items, deltas])
                else "Waiting for real Requirement, Task, Evidence and Review records.",
            )
        ],
    )


def list_knowledge_assets(db: Session, workspace_id: str) -> WorkspaceAssetsKnowledgeResponse:
    assets = (
        db.query(SddKnowledgeAsset)
        .filter(SddKnowledgeAsset.workspace_id == workspace_id)
        .order_by(SddKnowledgeAsset.created_at.desc())
        .all()
    )
    total = len(assets)
    return WorkspaceAssetsKnowledgeResponse(
        workspace_id=workspace_id,
        items=[_knowledge_asset_response(item) for item in assets],
        total=total,
        state=_collection_state(total, "No promoted Knowledge Asset records are available yet."),
        connection_status=[
            _connection(
                "knowledge_assets",
                "Knowledge assets",
                "AVAILABLE" if total else "EMPTY",
                "Promoted Knowledge Asset records are available."
                if total
                else "Waiting for promotion from real task process records.",
            )
        ],
    )
