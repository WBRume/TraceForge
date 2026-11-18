"""Cross-workspace workload for the members of one workspace."""

from collections import Counter
from datetime import datetime

from sqlalchemy.orm import Session

from app.domains.auth.models.user import Workspace, WorkspaceMember, WorkspacePermission
from app.domains.workspace.services.workspace_service import user_has_permission
from app.domains.workspace_asset.schemas.workload import (
    MemberWorkloadOverview,
    Slot,
    WorkKind,
    WorkloadCounts,
    WorkloadDetails,
    WorkloadSource,
    WorkspaceMemberWorkload,
)
from app.domains.workspace_asset.services.workload import get_workload


def _sum_counts(sources: list[WorkloadSource]) -> WorkloadCounts:
    slots: Counter[Slot] = Counter()
    items: Counter[WorkKind] = Counter()
    for source in sources:
        slots.update(source.counts.slots)
        items.update(source.counts.items)
    return WorkloadCounts(slots=slots, items=items, overdue=sum(source.counts.overdue for source in sources))


def get_workspace_member_workload(
    db: Session,
    workspace_id: str,
    viewer_id: str,
    *,
    can_edit_limits: bool,
    as_of: datetime,
) -> WorkspaceMemberWorkload:
    anchor = get_workload(db, workspace_id, as_of=as_of, can_edit_limits=can_edit_limits)
    sources_by_member: dict[str, list[WorkloadSource]] = {member.user_id: [] for member in anchor.members}
    # Use the roster's memberships to select sources. Check the viewer's
    # permissions separately when including task and requirement records.
    workspaces = (
        db.query(Workspace.id, Workspace.name)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .filter(WorkspaceMember.user_id.in_(sources_by_member))
        .distinct()
        .order_by(Workspace.name, Workspace.id)
        .all()
    )
    workspaces.sort(key=lambda workspace: workspace.id != workspace_id)
    next_evaluate_at = anchor.next_evaluate_at
    observation_gaps = 0
    for source_id, source_name in workspaces:
        snapshot = (
            anchor
            if source_id == workspace_id
            else get_workload(db, source_id, as_of=as_of, can_edit_limits=False, member_ids=sources_by_member.keys())
        )
        observation_gaps += snapshot.observation_gaps
        if snapshot.next_evaluate_at is not None:
            next_evaluate_at = min(next_evaluate_at or snapshot.next_evaluate_at, snapshot.next_evaluate_at)
        can_view_details = source_id == workspace_id or user_has_permission(
            db, source_id, viewer_id, WorkspacePermission.VIEW_ASSETS
        )
        for member in snapshot.members:
            sources_by_member[member.user_id].append(
                WorkloadSource(
                    workspace_id=source_id,
                    workspace_name=source_name,
                    counts=WorkloadCounts(
                        slots=Counter(run.slot for run in member.executions),
                        items=Counter(item.kind for item in member.items),
                        overdue=sum(item.overdue for item in member.items),
                    ),
                    details=(
                        WorkloadDetails(executions=member.executions, items=member.items) if can_view_details else None
                    ),
                )
            )

    return WorkspaceMemberWorkload(
        graph_version=anchor.graph_version,
        as_of=anchor.as_of,
        next_evaluate_at=next_evaluate_at,
        can_edit_limits=anchor.can_edit_limits,
        unassigned=anchor.unassigned,
        observation_gaps=observation_gaps,
        members=[
            MemberWorkloadOverview(
                user_id=member.user_id,
                display_name=member.display_name,
                role=member.role,
                avatar_url=member.avatar_url,
                limits=member.limits,
                counts=_sum_counts(sources_by_member[member.user_id]),
                sources=sources_by_member[member.user_id],
            )
            for member in anchor.members
        ],
    )
