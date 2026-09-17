"""Requirement 族响应构建器与审计写入。

覆盖 Requirement 摘要/详情、关联任务、coverage 摘要、审计日志以及导入
批次/条目的响应映射；读侧与写侧共用，展示逻辑不落在查询或写入函数里。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.domains.workspace_asset.models.workspace_asset import (
    SddRequirement,
    SddRequirementAuditLog,
    SddRequirementImportBatch,
    SddRequirementImportItem,
    SddTaskRequirement,
    RequirementAuditAction,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    RequirementAuditLogResponse,
    RequirementCoverageSummary,
    RequirementImportBatchResponse,
    RequirementImportPreviewItem,
    RequirementLinkedTaskResponse,
    RequirementSummary,
    TaskRequirementLinkResponse,
)
from app.domains.workspace_asset.services.common.primitives import (
    clean_optional,
    coverage_status,
    dedupe_by_id,
    enum_value,
    json_dict,
    normalize_list,
)


def requirement_snapshot(requirement: SddRequirement) -> Dict[str, Any]:
    return {
        "id": requirement.id,
        "title": requirement.title,
        "body": requirement.body,
        "status": enum_value(requirement.status),
        "acceptance_criteria": list(requirement.acceptance_criteria_json or []),
        "priority": requirement.priority,
        "parent_requirement_id": requirement.parent_requirement_id,
        "import_batch_id": requirement.import_batch_id,
        "source_kind": requirement.source_kind,
        "source_uri": requirement.source_uri,
        "source_ref": requirement.source_ref,
        "source_metadata": requirement.source_metadata_json,
    }


def add_requirement_audit(
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
        reason=clean_optional(reason),
        source_metadata_json=json_dict(source_metadata),
    )
    db.add(log)
    return log


def requirement_audit_response(log: SddRequirementAuditLog) -> RequirementAuditLogResponse:
    return RequirementAuditLogResponse(
        id=log.id,
        workspace_id=log.workspace_id,
        requirement_id=log.requirement_id,
        import_batch_id=log.import_batch_id,
        task_id=log.task_id,
        actor_id=log.actor_id,
        action=enum_value(log.action),
        before=log.before_json if isinstance(log.before_json, dict) else None,
        after=log.after_json if isinstance(log.after_json, dict) else None,
        reason=log.reason,
        source_metadata=log.source_metadata_json if isinstance(log.source_metadata_json, dict) else None,
        created_at=log.created_at,
    )


# ---------------------------------------------------------------------------
# Requirement ↔ Task 关联与 coverage
# ---------------------------------------------------------------------------


def requirement_family(requirement: SddRequirement) -> List[SddRequirement]:
    members = [requirement]
    if not requirement.parent_requirement_id:
        members.extend(list(requirement.child_requirements or []))
    return members


def requirement_task_links(requirement: SddRequirement) -> List[SddTaskRequirement]:
    return [link for member in requirement_family(requirement) for link in (member.task_links or [])]


def requirement_coverage_summary(requirement: SddRequirement) -> RequirementCoverageSummary:
    task_links = requirement_task_links(requirement)
    tasks = [link.task for link in task_links if link.task]
    evidence_items = dedupe_by_id([
        *[evidence for member in requirement_family(requirement) for evidence in (member.evidence_items or [])],
        *[evidence for task in tasks for evidence in (task.evidence_items or [])],
    ])
    human_review_count = sum(len(task.human_reviews or []) for task in tasks)
    human_delta_count = sum(len(task.human_deltas or []) for task in tasks)
    status = coverage_status(len(task_links), evidence_items)
    if status == "verified":
        reason = "Coverage Verified is derived from confirmed Evidence and human confirmation."
    elif status == "waiting_human_confirmation":
        reason = "Evidence exists, but human confirmation is still required before Coverage can be Verified."
    elif status == "waiting_evidence":
        reason = "Requirement has related Task records, but no confirmed Evidence is attached."
    else:
        reason = "Coverage is unavailable until the Requirement is linked to a real Task."
    return RequirementCoverageSummary(
        coverage_status=status,
        coverage_reason=reason,
        related_task_count=len(task_links),
        evidence_count=len(evidence_items),
        human_review_count=human_review_count,
        human_delta_count=human_delta_count,
    )


def requirement_linked_task(link: SddTaskRequirement) -> RequirementLinkedTaskResponse:
    task = link.task
    requirement_count = len(task.requirement_links or []) if task else 0
    evidence_items = list(task.evidence_items or []) if task else []
    return RequirementLinkedTaskResponse(
        link_id=link.id,
        task_id=link.task_id,
        task_name=task.name if task else "",
        task_status=enum_value(task.status) if task else "unknown",
        current_phase=task.current_phase if task else None,
        relation_type=enum_value(link.relation_type),
        coverage_status=coverage_status(requirement_count, evidence_items),
        created_at=link.created_at,
    )


def task_requirement_link(link: SddTaskRequirement) -> TaskRequirementLinkResponse:
    return TaskRequirementLinkResponse(
        id=link.id,
        requirement_id=link.requirement_id,
        task_id=link.task_id,
        relation_type=enum_value(link.relation_type),
        requirement=requirement_summary(link.requirement) if link.requirement else None,
        created_at=link.created_at,
    )


def requirement_summary(
    requirement: SddRequirement,
    *,
    include_linked_tasks: bool = False,
    include_children: bool = False,
) -> RequirementSummary:
    task_links = requirement_task_links(requirement)
    children = sorted(list(requirement.child_requirements or []), key=lambda item: item.created_at or datetime.min, reverse=True)
    child_count = len(children)
    return RequirementSummary(
        id=requirement.id,
        workspace_id=requirement.workspace_id,
        title=requirement.title,
        body=requirement.body,
        status=enum_value(requirement.status),
        acceptance_criteria=normalize_list(requirement.acceptance_criteria_json),
        priority=requirement.priority,
        parent_requirement_id=requirement.parent_requirement_id,
        parent_title=requirement.parent_requirement.title if requirement.parent_requirement else None,
        child_count=child_count,
        children=[
            requirement_summary(child, include_linked_tasks=True, include_children=False)
            for child in children
        ] if include_children else [],
        can_link_task=bool(requirement.parent_requirement_id or child_count == 0),
        import_batch_id=requirement.import_batch_id,
        source_kind=requirement.source_kind,
        source_uri=requirement.source_uri,
        source_ref=requirement.source_ref,
        source_metadata=requirement.source_metadata_json if isinstance(requirement.source_metadata_json, dict) else None,
        coverage_summary=requirement_coverage_summary(requirement),
        change_history_count=len(requirement.audit_logs or []),
        related_task_count=len(task_links),
        linked_tasks=[requirement_linked_task(link) for link in task_links] if include_linked_tasks else [],
        created_at=requirement.created_at,
        updated_at=requirement.updated_at,
    )


# ---------------------------------------------------------------------------
# 导入批次 / 预览条目
# ---------------------------------------------------------------------------


def import_item_response(item: SddRequirementImportItem) -> RequirementImportPreviewItem:
    metadata = item.source_metadata_json if isinstance(item.source_metadata_json, dict) else None
    return RequirementImportPreviewItem(
        id=item.id,
        title=item.title,
        body=item.body,
        acceptance_criteria=normalize_list(item.acceptance_criteria_json),
        priority=item.priority,
        task_prompt=clean_optional((metadata or {}).get("task_prompt")),
        source_ref=item.source_ref,
        source_metadata=metadata,
        order_index=item.order_index,
        status=enum_value(item.status),
        requirement_id=item.requirement_id,
    )


def import_batch_response(batch: SddRequirementImportBatch) -> RequirementImportBatchResponse:
    items = sorted(batch.items or [], key=lambda item: item.order_index)
    return RequirementImportBatchResponse(
        id=batch.id,
        workspace_id=batch.workspace_id,
        source_kind=batch.source_kind,
        source_filename=batch.source_filename,
        source_uri=batch.source_uri,
        source_ref=batch.source_ref,
        source_metadata=batch.source_metadata_json if isinstance(batch.source_metadata_json, dict) else None,
        status=enum_value(batch.status),
        item_count=batch.item_count,
        confirmed_count=batch.confirmed_count,
        normalized_markdown=batch.normalized_markdown,
        items=[import_item_response(item) for item in items],
        created_at=batch.created_at,
        updated_at=batch.updated_at,
    )
