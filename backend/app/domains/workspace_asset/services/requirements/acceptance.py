"""Requirement acceptance transitions and their audited review scope."""

import hashlib
import json

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.domains.task.models.task import SddTask
from app.domains.workspace_asset.models.workspace_asset import (
    RequirementAuditAction,
    RequirementStatus,
    SddRequirement,
    TaskRequirementRelationType,
)
from app.domains.workspace_asset.schemas.workspace_asset import RequirementAcceptanceRequest, RequirementDetailResponse
from app.domains.workspace_asset.services.common.errors import WorkspaceAssetError
from app.domains.workspace_asset.services.requirements.presenters import (
    add_requirement_audit,
    implementation_tasks,
    requirement_acceptance_blocker,
    requirement_family,
    requirement_snapshot,
    requirement_task_progress,
)
from app.domains.workspace_asset.services.requirements.queries import get_requirement, get_requirement_detail


def acceptance_scope(requirement: SddRequirement) -> str:
    scope = [
        {
            "id": member.id,
            "title": member.title,
            "body": member.body,
            "criteria": member.acceptance_criteria_json,
            "tasks": sorted(
                link.task_id for link in member.task_links if link.relation_type == TaskRequirementRelationType.COVERS
            ),
        }
        for member in sorted(requirement_family(requirement), key=lambda member: member.id)
    ]
    return hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()


def apply_acceptance(
    db: Session, workspace_id: str, requirement_id: str, actor_id: str, payload: RequirementAcceptanceRequest
) -> RequirementDetailResponse | None:
    requirement = get_requirement(db, workspace_id, requirement_id, for_update=True)
    if requirement is None:
        return None

    action = payload.action
    status = requirement.status
    reason = (payload.reason or "").strip()
    allowed = {
        "submit": {
            RequirementStatus.DRAFT,
            RequirementStatus.ACTIVE,
            RequirementStatus.READY,
            RequirementStatus.IN_PROGRESS,
            RequirementStatus.REJECTED,
        },
        "approve": {RequirementStatus.PENDING_ACCEPTANCE},
        "reject": {RequirementStatus.PENDING_ACCEPTANCE},
        "reopen": {RequirementStatus.VERIFIED},
    }
    if status not in allowed[action]:
        raise WorkspaceAssetError("This acceptance action is unavailable in the current status.", status_code=409)
    if action in {"reject", "reopen"} and not reason:
        raise WorkspaceAssetError("An acceptance reason is required.", status_code=422)

    meta = {"acceptance_action": action}
    if action in {"submit", "approve"}:
        # Keep the review scope stable while validating. Child edits lock the
        # child row, and task state transitions lock the affected task row.
        child_ids = [child.id for child in requirement.child_requirements]
        if child_ids:
            db.query(SddRequirement.id).filter(SddRequirement.id.in_(child_ids)).order_by(
                SddRequirement.id
            ).with_for_update().all()
            requirement = get_requirement(db, workspace_id, requirement_id, for_update=True)
        tasks = implementation_tasks(requirement)
        if tasks:
            try:
                db.query(SddTask).filter(SddTask.id.in_(tasks)).order_by(
                    SddTask.id
                ).populate_existing().with_for_update(nowait=True).all()
            except OperationalError as exc:
                if getattr(exc.orig, "sqlstate", None) != "55P03":
                    raise
                raise WorkspaceAssetError(
                    "A linked task is being updated. Retry the acceptance action.", status_code=409
                ) from exc
        blocker = requirement_acceptance_blocker(requirement, requirement_task_progress(requirement))
        if blocker:
            raise WorkspaceAssetError(
                {
                    "no_tasks": "Link at least one implementation task before submitting acceptance.",
                    "tasks_pending": "Complete all implementation tasks before accepting the requirement.",
                    "children_pending": "Accept all child requirements first.",
                }[blocker],
                status_code=409,
            )
        scope = acceptance_scope(requirement)
        meta["acceptance_scope"] = scope
        if action == "approve":
            submission = next(
                (
                    log
                    for log in requirement.audit_logs
                    if isinstance(log.source_metadata_json, dict)
                    and log.source_metadata_json.get("acceptance_action") == "submit"
                ),
                None,
            )
            if not submission or submission.source_metadata_json.get("acceptance_scope") != scope:
                raise WorkspaceAssetError(
                    "The acceptance scope has changed. Return the requirement and submit it again.", status_code=409
                )

    before = requirement_snapshot(requirement)
    requirement.status = {
        "submit": RequirementStatus.PENDING_ACCEPTANCE,
        "approve": RequirementStatus.VERIFIED,
        "reject": RequirementStatus.REJECTED,
        "reopen": RequirementStatus.IN_PROGRESS,
    }[action]
    add_requirement_audit(
        db,
        workspace_id=workspace_id,
        requirement_id=requirement_id,
        actor_id=actor_id,
        action=RequirementAuditAction.STATUS_CHANGED,
        before=before,
        after=requirement_snapshot(requirement),
        reason=reason,
        source_metadata=meta,
    )
    db.commit()
    return get_requirement_detail(db, workspace_id, requirement_id)
