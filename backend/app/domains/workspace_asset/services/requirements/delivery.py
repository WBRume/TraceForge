"""Shared delivery rules for requirement lists, mutations and workload."""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domains.ai.models.ai_job import AiJobChannel, SddAiJob
from app.domains.task.models.task import TaskStatus
from app.domains.workspace_asset.models.workspace_asset import (
    RequirementStatus as Status,
)
from app.domains.workspace_asset.models.workspace_asset import (
    SddRequirement,
    TaskRequirementRelationType,
)

OPEN_STATUSES = {Status.DRAFT, Status.WAITING_SOURCE, Status.READY, Status.ACTIVE, Status.IN_PROGRESS, Status.REJECTED}
READY_STATUSES = {Status.READY, Status.ACTIVE}
OUTPUT_STATUSES = {TaskStatus.ROUND_COMPLETED, TaskStatus.COMPLETED}


def implementation_links(requirement: SddRequirement):
    return [
        link
        for link in requirement.task_links
        if link.relation_type == TaskRequirementRelationType.COVERS and link.task is not None
    ]


def activity_times(db: Session, workspace_id: str, task_ids: Iterable[str]) -> dict[str, datetime]:
    ids = set(task_ids)
    if not ids:
        return {}
    return dict(
        db.query(SddAiJob.task_id, func.max(SddAiJob.started_at))
        .filter(
            SddAiJob.workspace_id == workspace_id,
            SddAiJob.task_id.in_(ids),
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
            SddAiJob.started_at.isnot(None),
        )
        .group_by(SddAiJob.task_id)
        .all()
    )


def work_started(requirement: SddRequirement, starts: dict[str, datetime]) -> bool:
    return requirement.status in {
        Status.IN_PROGRESS,
        Status.REJECTED,
        Status.PENDING_ACCEPTANCE,
        Status.VERIFIED,
    } or any(
        link.task_id in starts or link.task.status in OUTPUT_STATUSES for link in implementation_links(requirement)
    )


def clarification_reason(requirement: SddRequirement) -> str | None:
    prerequisite = requirement.predecessor
    if prerequisite and prerequisite.status != Status.VERIFIED:
        return "predecessor"
    if (
        requirement.status not in READY_STATUSES
        or not (requirement.body or "").strip()
        or not any(str(item).strip() for item in (requirement.acceptance_criteria_json or []))
    ):
        return "scope"
    return None


def matches_work_scope(requirement: SddRequirement, starts: dict[str, datetime], scope: str, actor_id: str) -> bool:
    if requirement.child_requirements or requirement.status not in OPEN_STATUSES or work_started(requirement, starts):
        return False
    if scope == "mine":
        return requirement.owner_id == actor_id
    reason = clarification_reason(requirement)
    return reason is not None if scope == "clarify" else reason is None and not requirement.owner_id


def acceptance_event(requirement: SddRequirement, actions: set[str]):
    return max(
        (row for row in requirement.audit_logs if _event_metadata(row).get("acceptance_action") in actions),
        key=lambda row: (row.created_at, row.id),
        default=None,
    )


def _event_metadata(row) -> dict:
    return row.source_metadata_json if isinstance(row.source_metadata_json, dict) else {}


def _last_return(requirement: SddRequirement):
    return max(
        (
            row
            for row in requirement.audit_logs
            if _event_metadata(row).get("acceptance_action") in {"reject", "reopen"}
            or _event_metadata(row).get("result_check_action") == "return"
        ),
        key=lambda row: (row.created_at, row.id),
        default=None,
    )


def check_cycle(requirement: SddRequirement) -> tuple[str, datetime | None]:
    returned = _last_return(requirement)
    return (returned.id, returned.created_at) if returned else ("initial", None)


def check_receipt(requirement: SddRequirement, cycle: str):
    return max(
        (row for row in requirement.audit_logs if _event_metadata(row).get("checked_cycle") == cycle),
        key=lambda row: (row.created_at, row.id),
        default=None,
    )


def result_check_state(
    requirement: SddRequirement, starts: dict[str, datetime], active_tasks: set[str] | None = None
) -> str | None:
    """One result check per leaf and business cycle, irrespective of producer attempts."""
    if (
        not requirement.result_check_required
        or requirement.child_requirements
        or requirement.status not in OPEN_STATUSES
    ):
        return None
    cycle, returned_at = check_cycle(requirement)
    if check_receipt(requirement, cycle):
        return None
    links = implementation_links(requirement)
    if not any(
        (link.task_id in starts and (returned_at is None or starts[link.task_id] > returned_at))
        or (link.task.status in OUTPUT_STATUSES and (returned_at is None or link.task.created_at > returned_at))
        for link in links
    ):
        return None
    if all(link.task.status in OUTPUT_STATUSES for link in links):
        return "ready"
    if active_tasks is not None:
        return "producing" if any(link.task_id in active_tasks for link in links) else "paused"
    if all(link.task.status in OUTPUT_STATUSES | {TaskStatus.FAILED, TaskStatus.INTERRUPTED} for link in links):
        return "paused"
    return "producing"


def result_check_blocks_acceptance(requirement: SddRequirement, starts: dict[str, datetime]) -> bool:
    if not requirement.result_check_required or requirement.child_requirements:
        return False
    returned = _last_return(requirement)
    waiting_for_revision = (
        returned
        and _event_metadata(returned).get("result_check_action") == "return"
        and not check_receipt(requirement, returned.id)
    )
    return bool(waiting_for_revision) or result_check_state(requirement, starts) == "ready"
