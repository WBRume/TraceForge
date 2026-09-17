"""Clarification 的更新写操作（创建走 final workflow 的 clarification_service）。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.domains.workspace_asset.models.workspace_asset import (
    ClarificationBlockingLevel,
    ClarificationStatus,
    SddClarification,
    TaskProcessAuditAction,
    TaskProcessRecordType,
)
from app.domains.workspace_asset.schemas.workspace_asset import ClarificationUpdateRequest
from app.domains.workspace_asset.services.common.errors import WorkspaceAssetError
from app.domains.workspace_asset.services.common.primitives import (
    clean_optional,
    json_dict,
    normalize_enum,
    payload_has_field,
)
from app.domains.workspace_asset.services.common.process_presenters import clarification_response
from app.domains.workspace_asset.services.task_process.writes_support import (
    add_process_audit,
    ensure_evidence,
    ensure_human_review,
    ensure_requirement,
    ensure_task_not_baselined,
)


def update_clarification(
    db: Session,
    workspace_id: str,
    task_id: str,
    clarification_id: str,
    actor_id: Optional[str],
    payload: ClarificationUpdateRequest,
) -> None:
    clarification = (
        db.query(SddClarification)
        .filter(
            SddClarification.workspace_id == workspace_id,
            SddClarification.task_id == task_id,
            SddClarification.id == clarification_id,
        )
        .first()
    )
    if not clarification:
        raise WorkspaceAssetError("Clarification not found for this Task.", status_code=404)
    ensure_task_not_baselined(clarification.task)
    before = clarification_response(clarification).model_dump(mode="json")
    if payload_has_field(payload, "requirement_id"):
        ensure_requirement(db, workspace_id, payload.requirement_id)
        clarification.requirement_id = payload.requirement_id
    if payload_has_field(payload, "converted_requirement_id"):
        ensure_requirement(db, workspace_id, payload.converted_requirement_id)
        clarification.converted_requirement_id = payload.converted_requirement_id
    if payload_has_field(payload, "source_evidence_id"):
        ensure_evidence(db, workspace_id, task_id, payload.source_evidence_id)
        clarification.source_evidence_id = payload.source_evidence_id
    if payload_has_field(payload, "source_review_id"):
        ensure_human_review(db, workspace_id, task_id, payload.source_review_id)
        clarification.source_review_id = payload.source_review_id
    if payload_has_field(payload, "status") and payload.status is not None:
        clarification.status = normalize_enum(
            ClarificationStatus,
            payload.status,
            ClarificationStatus.OPEN,
            "Clarification status",
        )
    if payload_has_field(payload, "blocking_level") and payload.blocking_level is not None:
        clarification.blocking_level = normalize_enum(
            ClarificationBlockingLevel,
            payload.blocking_level,
            ClarificationBlockingLevel.NON_BLOCKING,
            "Clarification blocking level",
        )
    if payload_has_field(payload, "question"):
        clarification.question = clean_optional(payload.question) or clarification.question
    if payload_has_field(payload, "answer"):
        clarification.answer = clean_optional(payload.answer)
        clarification.responder_id = actor_id if clarification.answer else None
        clarification.answered_at = None
        if clarification.answer:
            clarification.answered_at = datetime.utcnow()
            if clarification.status == ClarificationStatus.OPEN:
                clarification.status = ClarificationStatus.ANSWERED
    if payload_has_field(payload, "clarification_type"):
        clarification.clarification_type = clean_optional(payload.clarification_type, limit=80)
    if payload_has_field(payload, "target_ref"):
        clarification.target_ref_json = json_dict(payload.target_ref)
    if payload_has_field(payload, "urgency"):
        clarification.urgency = clean_optional(payload.urgency, limit=40)
    if payload_has_field(payload, "promote_candidate") and payload.promote_candidate is not None:
        clarification.promote_candidate = bool(payload.promote_candidate)
    db.flush()
    add_process_audit(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        record_type=TaskProcessRecordType.CLARIFICATION,
        record_id=clarification.id,
        action=TaskProcessAuditAction.UPDATED,
        actor_id=actor_id,
        before=before,
        after=clarification_response(clarification).model_dump(mode="json"),
        reason=payload.change_reason,
    )
    db.commit()
