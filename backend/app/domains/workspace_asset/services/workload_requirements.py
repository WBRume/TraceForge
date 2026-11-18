"""Delivery responsibilities and result checks, independent of session attribution."""

from datetime import datetime

from sqlalchemy.orm import Session, selectinload

from app.domains.workspace_asset.models.workspace_asset import (
    RequirementStatus as Status,
)
from app.domains.workspace_asset.models.workspace_asset import (
    SddRequirement,
    SddTaskRequirement,
)
from app.domains.workspace_asset.schemas.workload import WorkloadItem
from app.domains.workspace_asset.services.requirements.delivery import (
    OPEN_STATUSES,
    acceptance_event,
    activity_times,
    check_cycle,
    implementation_links,
    result_check_state,
    work_started,
)
from app.domains.workspace_asset.services.workload_operators import register


@register("FollowupCheckProject")
def requirement_workload(db: Session, workspace_id: str, producing_tasks: set[str]):
    requirements = (
        db.query(SddRequirement)
        .filter_by(workspace_id=workspace_id)
        .options(
            selectinload(SddRequirement.child_requirements),
            selectinload(SddRequirement.task_links).selectinload(SddTaskRequirement.task),
            selectinload(SddRequirement.audit_logs),
        )
        .all()
    )
    starts = activity_times(
        db, workspace_id, (link.task_id for item in requirements for link in implementation_links(item))
    )
    items: list[tuple[str | None, WorkloadItem]] = []
    phase_ends: dict[str, datetime] = {}
    unspecified: set[str] = set()
    for requirement in requirements:
        for log in requirement.audit_logs:
            metadata = log.source_metadata_json
            if isinstance(metadata, dict) and metadata.get("checked_cycle"):
                for task_id in metadata.get("check_task_ids", []):
                    phase_ends[task_id] = max(phase_ends.get(task_id, log.created_at), log.created_at)
        common = {"title": requirement.title, "requirement_id": requirement.id}
        if requirement.status == Status.PENDING_ACCEPTANCE:
            submission = acceptance_event(requirement, {"submit"})
            items.append(
                (
                    requirement.acceptor_id,
                    WorkloadItem(
                        id=f"acceptance:{submission.id if submission else requirement.id}",
                        kind="acceptance",
                        since=submission.created_at if submission else requirement.updated_at,
                        **common,
                    ),
                )
            )
        if requirement.child_requirements:
            continue
        if requirement.owner_id and requirement.status in OPEN_STATUSES | {Status.PENDING_ACCEPTANCE}:
            kind = "ongoing" if work_started(requirement, starts) else "planned"
            items.append((requirement.owner_id, WorkloadItem(id=requirement.id, kind=kind, **common)))
        check = result_check_state(requirement, starts, producing_tasks)
        if check:
            cycle, _ = check_cycle(requirement)
            kind = {"ready": "check", "producing": "expected_check", "paused": "paused_check"}[check]
            since = max(
                (link.task.updated_at for link in implementation_links(requirement) if link.task.updated_at),
                default=None,
            )
            items.append(
                (
                    requirement.reviewer_id,
                    WorkloadItem(
                        id=f"check:{requirement.id}:{cycle}",
                        kind=kind,
                        since=since,
                        **common,
                    ),
                )
            )
        elif (
            requirement.status in OPEN_STATUSES
            and not requirement.result_check_required
            and work_started(requirement, starts)
        ):
            unspecified.update(link.task_id for link in implementation_links(requirement))
    return items, phase_ends, unspecified
