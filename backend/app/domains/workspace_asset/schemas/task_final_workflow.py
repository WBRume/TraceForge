"""Schemas for the Task final-state workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domains.workspace_asset.schemas.workspace_asset import (
    ClarificationBlockingLevelValue,
    ClarificationResponse,
    DeltaRegionResponse,
    HumanDeltaFileDiff,
    HumanReviewResponse,
    TaskFinalStatusValue,
    TaskFinalSummaryResponse,
    TaskSummary,
)

WorkflowStepKey = Literal["expert_review", "clarification", "final_summary", "baseline"]
WorkflowStepStatus = Literal["blocked", "ready", "active", "complete"]
ChecklistStatus = Literal["pass", "warning", "block"]
ReviewDerivedStatus = Literal["CLEAR", "WAITING_ANSWER", "ANSWERED_REVIEWING", "CLOSED"]
PreviewBlockKind = Literal["text", "markdown", "metadata", "list", "diff", "file_diffs", "json"]
ReviewTargetType = Literal[
    "SPEC",
    "PLAN",
    "AI_CHANGE",
    "HUMAN_DELTA",
    "EVIDENCE",
    "DECISION",
    "TASK_FILE",
]
ClarificationMessageType = Literal["QUESTION", "FOLLOW_UP", "ANSWER", "CONFIRM_RESOLUTION", "REOPEN", "SYSTEM"]


class FinalWorkflowAction(BaseModel):
    key: str
    label: str
    enabled: bool = True
    disabled_reason: str | None = None


class TaskFinalWorkflowStep(BaseModel):
    key: WorkflowStepKey
    title: str
    status: WorkflowStepStatus
    detail: str | None = None
    blocking_count: int = 0


class BaselineCheckItem(BaseModel):
    key: str
    label: str
    status: ChecklistStatus
    detail: str | None = None
    blocking: bool = False


class ClarificationThreadResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    clarification_id: str
    author_id: str | None = None
    entry_type: str
    body: str
    is_answer: bool = False
    created_at: datetime | None = None


class FinalWorkflowReviewTargetRef(BaseModel):
    target_type: ReviewTargetType
    target_id: str
    label: str | None = None
    source_ref: dict[str, Any] | None = None


class FinalWorkflowReviewTarget(BaseModel):
    target_type: ReviewTargetType
    target_id: str
    label: str
    status: str | None = None
    subtitle: str | None = None
    source_ref: dict[str, Any] | None = None


class FinalWorkflowReviewTargetPreviewMetadata(BaseModel):
    key: str
    label: str
    value: str | None = None


class FinalWorkflowReviewTargetPreviewBlock(BaseModel):
    key: str
    title: str
    kind: PreviewBlockKind
    content: str | None = None
    items: list[dict[str, Any]] = Field(default_factory=list)
    file_diffs: list[HumanDeltaFileDiff] = Field(default_factory=list)
    delta_regions: list[DeltaRegionResponse] = Field(default_factory=list)
    diff_text: str | None = None


class FinalWorkflowReviewTargetPreviewResponse(BaseModel):
    target: FinalWorkflowReviewTarget
    title: str
    status: str | None = None
    subtitle: str | None = None
    source_ref: dict[str, Any] | None = None
    metadata: list[FinalWorkflowReviewTargetPreviewMetadata] = Field(default_factory=list)
    blocks: list[FinalWorkflowReviewTargetPreviewBlock] = Field(default_factory=list)


class TaskBaselineResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    summary_id: str | None = None
    version: int
    snapshot: dict[str, Any] | None = None
    baselined_by_id: str | None = None
    is_rollback: bool = False
    rollback_from_version: int | None = None
    created_at: datetime | None = None


class TaskFinalWorkflowResponse(BaseModel):
    task: TaskSummary
    steps: list[TaskFinalWorkflowStep] = Field(default_factory=list)
    reviews: list[HumanReviewResponse] = Field(default_factory=list)
    review_targets: dict[str, list[FinalWorkflowReviewTarget]] = Field(default_factory=dict)
    clarifications: list[ClarificationResponse] = Field(default_factory=list)
    clarification_threads: dict[str, list[ClarificationThreadResponse]] = Field(default_factory=dict)
    final_summary: TaskFinalSummaryResponse | None = None
    baseline: TaskBaselineResponse | None = None
    checklist: list[BaselineCheckItem] = Field(default_factory=list)
    available_actions: list[FinalWorkflowAction] = Field(default_factory=list)
    readonly: bool = False
    can_write_final_workflow: bool = False
    can_resolve_clarification: bool = False


class FinalWorkflowReviewUpsertRequest(BaseModel):
    title: str
    body: str | None = None
    priority: str | None = "NORMAL"
    target_refs: list[FinalWorkflowReviewTargetRef] = Field(default_factory=list)
    change_reason: str | None = None


class WorkflowClarificationCreateRequest(BaseModel):
    requirement_id: str | None = None
    source_review_id: str | None = None
    source_evidence_id: str | None = None
    blocking_level: ClarificationBlockingLevelValue = "BLOCKING"
    clarification_type: str | None = None
    target_ref: dict[str, Any] | None = None
    urgency: str | None = None
    question: str
    change_reason: str | None = None


class ClarificationMessageCreateRequest(BaseModel):
    body: str
    entry_type: ClarificationMessageType
    change_reason: str | None = None


class FinalSummaryDraftRequest(BaseModel):
    change_reason: str | None = None


class WorkflowFinalSummaryUpsertRequest(BaseModel):
    final_status: TaskFinalStatusValue = "PENDING"
    summary: str | None = None
    remaining_risk: str | None = None
    next_steps: str | None = None
    final_evidence_ids: list[str] = Field(default_factory=list)
    review_checklist: dict[str, Any] | None = None
    clarification_summary: dict[str, Any] | None = None
    delta_summary: dict[str, Any] | None = None
    decision_summary: dict[str, Any] | None = None
    human_confirmation_review_id: str | None = None
    change_reason: str | None = None
