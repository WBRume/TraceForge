"""Schemas for the Task final-state workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.domains.workspace_asset.schemas.workspace_asset import (
    ClarificationBlockingLevelValue,
    ClarificationResponse,
    DeltaRegionResponse,
    HumanReviewResponse,
    HumanDeltaFileDiff,
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
    disabled_reason: Optional[str] = None


class TaskFinalWorkflowStep(BaseModel):
    key: WorkflowStepKey
    title: str
    status: WorkflowStepStatus
    detail: Optional[str] = None
    blocking_count: int = 0


class BaselineCheckItem(BaseModel):
    key: str
    label: str
    status: ChecklistStatus
    detail: Optional[str] = None
    blocking: bool = False


class ClarificationThreadResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    clarification_id: str
    author_id: Optional[str] = None
    entry_type: str
    body: str
    is_answer: bool = False
    created_at: Optional[datetime] = None


class FinalWorkflowReviewTargetRef(BaseModel):
    target_type: ReviewTargetType
    target_id: str
    label: Optional[str] = None
    source_ref: Optional[Dict[str, Any]] = None


class FinalWorkflowReviewTarget(BaseModel):
    target_type: ReviewTargetType
    target_id: str
    label: str
    status: Optional[str] = None
    subtitle: Optional[str] = None
    source_ref: Optional[Dict[str, Any]] = None


class FinalWorkflowReviewTargetPreviewMetadata(BaseModel):
    key: str
    label: str
    value: Optional[str] = None


class FinalWorkflowReviewTargetPreviewBlock(BaseModel):
    key: str
    title: str
    kind: PreviewBlockKind
    content: Optional[str] = None
    items: List[Dict[str, Any]] = Field(default_factory=list)
    file_diffs: List[HumanDeltaFileDiff] = Field(default_factory=list)
    delta_regions: List[DeltaRegionResponse] = Field(default_factory=list)
    diff_text: Optional[str] = None


class FinalWorkflowReviewTargetPreviewResponse(BaseModel):
    target: FinalWorkflowReviewTarget
    title: str
    status: Optional[str] = None
    subtitle: Optional[str] = None
    source_ref: Optional[Dict[str, Any]] = None
    metadata: List[FinalWorkflowReviewTargetPreviewMetadata] = Field(default_factory=list)
    blocks: List[FinalWorkflowReviewTargetPreviewBlock] = Field(default_factory=list)


class TaskBaselineResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    summary_id: Optional[str] = None
    version: int
    snapshot: Optional[Dict[str, Any]] = None
    baselined_by_id: Optional[str] = None
    is_rollback: bool = False
    rollback_from_version: Optional[int] = None
    created_at: Optional[datetime] = None


class TaskFinalWorkflowResponse(BaseModel):
    task: TaskSummary
    steps: List[TaskFinalWorkflowStep] = Field(default_factory=list)
    reviews: List[HumanReviewResponse] = Field(default_factory=list)
    review_targets: Dict[str, List[FinalWorkflowReviewTarget]] = Field(default_factory=dict)
    clarifications: List[ClarificationResponse] = Field(default_factory=list)
    clarification_threads: Dict[str, List[ClarificationThreadResponse]] = Field(default_factory=dict)
    final_summary: Optional[TaskFinalSummaryResponse] = None
    baseline: Optional[TaskBaselineResponse] = None
    checklist: List[BaselineCheckItem] = Field(default_factory=list)
    available_actions: List[FinalWorkflowAction] = Field(default_factory=list)
    readonly: bool = False
    can_write_final_workflow: bool = False
    can_resolve_clarification: bool = False


class FinalWorkflowReviewUpsertRequest(BaseModel):
    title: str
    body: Optional[str] = None
    priority: Optional[str] = "NORMAL"
    target_refs: List[FinalWorkflowReviewTargetRef] = Field(default_factory=list)
    change_reason: Optional[str] = None


class WorkflowClarificationCreateRequest(BaseModel):
    requirement_id: Optional[str] = None
    source_review_id: Optional[str] = None
    source_evidence_id: Optional[str] = None
    blocking_level: ClarificationBlockingLevelValue = "BLOCKING"
    clarification_type: Optional[str] = None
    target_ref: Optional[Dict[str, Any]] = None
    urgency: Optional[str] = None
    question: str
    change_reason: Optional[str] = None


class ClarificationMessageCreateRequest(BaseModel):
    body: str
    entry_type: ClarificationMessageType
    change_reason: Optional[str] = None


class FinalSummaryDraftRequest(BaseModel):
    change_reason: Optional[str] = None


class WorkflowFinalSummaryUpsertRequest(BaseModel):
    final_status: TaskFinalStatusValue = "PENDING"
    summary: Optional[str] = None
    remaining_risk: Optional[str] = None
    next_steps: Optional[str] = None
    final_evidence_ids: List[str] = Field(default_factory=list)
    review_checklist: Optional[Dict[str, Any]] = None
    clarification_summary: Optional[Dict[str, Any]] = None
    delta_summary: Optional[Dict[str, Any]] = None
    decision_summary: Optional[Dict[str, Any]] = None
    human_confirmation_review_id: Optional[str] = None
    change_reason: Optional[str] = None
