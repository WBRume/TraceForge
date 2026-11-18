from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

Quota = Annotated[int, Field(strict=True, ge=0, le=999)] | None
Slot = Literal["background", "interactive", "incomplete", "uncertain"]
WorkKind = Literal["reply", "check", "acceptance", "failure", "expected_check", "paused_check", "ongoing", "planned"]


class WorkloadLimits(BaseModel):
    background: Quota = None
    interactive: Quota = None
    ongoing: Quota = None


class WorkloadItem(BaseModel):
    id: str
    kind: WorkKind
    title: str
    task_id: str | None = None
    requirement_id: str | None = None
    since: datetime | None = None
    overdue: bool = False


class WorkloadExecution(BaseModel):
    id: str
    task_id: str
    title: str
    slot: Slot
    reason: Literal["running", "started", "reply", "recent_activity", "incomplete", "uncertain"]
    since: datetime | None = None


class MemberWorkload(BaseModel):
    user_id: str
    display_name: str
    role: str
    avatar_url: str | None = None
    limits: WorkloadLimits
    executions: list[WorkloadExecution] = Field(default_factory=list)
    items: list[WorkloadItem] = Field(default_factory=list)


class WorkspaceWorkload(BaseModel):
    graph_version: int
    as_of: datetime
    next_evaluate_at: datetime | None = None
    can_edit_limits: bool
    members: list[MemberWorkload]
    unassigned: list[WorkloadItem]
    observation_gaps: int = 0
