"""
Evidence write operations.

Extracted from workspace_task_detail_service.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.domains.workspace_asset.models.workspace_asset import (
    EvidenceSourceType,
    EvidenceStatus,
    EvidenceType,
    SddEvidence,
    TaskProcessAuditAction,
    TaskProcessRecordType,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    EvidenceCreateRequest,
    EvidenceUpdateRequest,
)
from app.domains.workspace_asset.services.workspace_task_detail_shared import (
    TaskDetailWriteError,
    _ensure_task_not_baselined,
    clean_optional,
    evidence_response,
    json_dict,
    normalize_enum,
    payload_has_field,
    _add_process_audit,
    _ensure_ai_job,
    _ensure_evidence,
    _ensure_human_review,
    _ensure_requirement,
    _get_task_or_error,
    _validate_evidence_for_phase,
    _validate_evidence_source,
)


def create_evidence(
    db: Session,
    workspace_id: str,
    task_id: str,
    actor_id: Optional[str],
    payload: EvidenceCreateRequest,
    *,
    _skip_phase_check: bool = False,
) -> str:
    task = _get_task_or_error(db, workspace_id, task_id)
    _ensure_task_not_baselined(task)
    _ensure_requirement(db, workspace_id, payload.requirement_id)
    _ensure_ai_job(db, workspace_id, task_id, payload.ai_job_id)
    _ensure_human_review(db, workspace_id, task_id, payload.human_review_id)
    evidence_type = normalize_enum(EvidenceType, payload.evidence_type, EvidenceType.CODE, "Evidence type")
    if not _skip_phase_check:
        _validate_evidence_for_phase(task.status, evidence_type)
    source_type = normalize_enum(EvidenceSourceType, payload.source_type, None, "Evidence source type")
    _validate_evidence_source(
        source_type=source_type,
        source_uri=payload.source_uri,
        source_ref=payload.source_ref,
        source_path=payload.source_path,
        source_metadata=payload.source_metadata,
    )
    status = normalize_enum(EvidenceStatus, payload.status, EvidenceStatus.UNCONFIRMED, "Evidence status")
    confirmed_at = datetime.utcnow() if payload.confirmed or status == EvidenceStatus.CONFIRMED else None
    evidence = SddEvidence(
        workspace_id=workspace_id,
        task_id=task_id,
        requirement_id=payload.requirement_id,
        ai_job_id=payload.ai_job_id,
        human_review_id=payload.human_review_id,
        created_by_id=actor_id,
        confirmed_by_id=actor_id if confirmed_at else None,
        status=EvidenceStatus.CONFIRMED if payload.confirmed else status,
        evidence_type=evidence_type,
        source_type=source_type,
        source_uri=clean_optional(payload.source_uri, limit=1000),
        source_label=clean_optional(payload.source_label, limit=300),
        source_ref=clean_optional(payload.source_ref, limit=300),
        source_path=clean_optional(payload.source_path, limit=1000),
        source_metadata_json=json_dict(payload.source_metadata),
        title=clean_optional(payload.title, limit=300),
        summary=clean_optional(payload.summary),
        confirmed_at=confirmed_at,
    )
    db.add(evidence)
    db.flush()
    _add_process_audit(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        record_type=TaskProcessRecordType.EVIDENCE,
        record_id=evidence.id,
        action=TaskProcessAuditAction.CREATED,
        actor_id=actor_id,
        after=evidence_response(evidence).model_dump(mode="json"),
        reason=payload.change_reason,
    )
    if evidence.task:
        from app.domains.workspace_asset.services.task_final_workflow.review_service import ensure_expert_review_for_task

        ensure_expert_review_for_task(db, evidence.task, actor_id)
    created_id = evidence.id
    db.commit()
    return created_id


def update_evidence(
    db: Session,
    workspace_id: str,
    task_id: str,
    evidence_id: str,
    actor_id: Optional[str],
    payload: EvidenceUpdateRequest,
) -> None:
    evidence = _ensure_evidence(db, workspace_id, task_id, evidence_id)
    assert evidence is not None
    _ensure_task_not_baselined(evidence.task)
    before = evidence_response(evidence).model_dump(mode="json")
    if payload_has_field(payload, "requirement_id"):
        _ensure_requirement(db, workspace_id, payload.requirement_id)
        evidence.requirement_id = payload.requirement_id
    if payload_has_field(payload, "ai_job_id"):
        _ensure_ai_job(db, workspace_id, task_id, payload.ai_job_id)
        evidence.ai_job_id = payload.ai_job_id
    if payload_has_field(payload, "human_review_id"):
        _ensure_human_review(db, workspace_id, task_id, payload.human_review_id)
        evidence.human_review_id = payload.human_review_id
    source_type = evidence.source_type
    if payload_has_field(payload, "source_type") and payload.source_type is not None:
        source_type = normalize_enum(EvidenceSourceType, payload.source_type, None, "Evidence source type")
    source_uri = payload.source_uri if payload_has_field(payload, "source_uri") else evidence.source_uri
    source_ref = payload.source_ref if payload_has_field(payload, "source_ref") else evidence.source_ref
    source_path = payload.source_path if payload_has_field(payload, "source_path") else evidence.source_path
    source_metadata = payload.source_metadata if payload_has_field(payload, "source_metadata") else evidence.source_metadata_json
    _validate_evidence_source(
        source_type=source_type,
        source_uri=source_uri,
        source_ref=source_ref,
        source_path=source_path,
        source_metadata=source_metadata,
    )
    evidence.source_type = source_type
    if payload_has_field(payload, "status") and payload.status is not None:
        evidence.status = normalize_enum(EvidenceStatus, payload.status, EvidenceStatus.UNCONFIRMED, "Evidence status")
    if payload_has_field(payload, "evidence_type") and payload.evidence_type is not None:
        evidence.evidence_type = normalize_enum(EvidenceType, payload.evidence_type, EvidenceType.CODE, "Evidence type")
    for field_name, limit in (
        ("source_uri", 1000),
        ("source_label", 300),
        ("source_ref", 300),
        ("source_path", 1000),
        ("title", 300),
    ):
        if payload_has_field(payload, field_name):
            setattr(evidence, field_name, clean_optional(getattr(payload, field_name), limit=limit))
    if payload_has_field(payload, "source_metadata"):
        evidence.source_metadata_json = json_dict(payload.source_metadata)
    if payload_has_field(payload, "summary"):
        evidence.summary = clean_optional(payload.summary)
    if payload_has_field(payload, "confirmed") and payload.confirmed is not None:
        if payload.confirmed:
            evidence.status = EvidenceStatus.CONFIRMED
            evidence.confirmed_by_id = actor_id
            evidence.confirmed_at = datetime.utcnow()
        else:
            evidence.confirmed_by_id = None
            evidence.confirmed_at = None
    db.flush()
    _add_process_audit(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        record_type=TaskProcessRecordType.EVIDENCE,
        record_id=evidence.id,
        action=TaskProcessAuditAction.UPDATED,
        actor_id=actor_id,
        before=before,
        after=evidence_response(evidence).model_dump(mode="json"),
        reason=payload.change_reason,
    )
    if evidence.task:
        from app.domains.workspace_asset.services.task_final_workflow.review_service import ensure_expert_review_for_task

        ensure_expert_review_for_task(db, evidence.task, actor_id)
    db.commit()
