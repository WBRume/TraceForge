"""
Read-only schemas for Workspace Assets.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


ConnectionState = Literal["NOT_CONNECTED", "EMPTY", "AVAILABLE", "ERROR"]
CoverageStatus = Literal["not_available", "waiting_evidence", "waiting_human_confirmation", "verified"]
RequirementEditableStatus = Literal[
    "DRAFT",
    "READY",
    "IN_PROGRESS",
    "VERIFIED",
    "REJECTED",
    "ARCHIVED",
    "ACTIVE",
    "WAITING_SOURCE",
]
SpecCoverageMatrixCoverageStatus = Literal[
    "missing",
    "spec_covered",
    "in_progress",
    "human_modified",
    "evidence_missing",
    "need_clarification",
    "rejected",
    "verified",
]
HumanReviewOutcomeValue = Literal[
    "ACCEPT",
    "ACCEPT_WITH_MODIFICATION",
    "REJECT",
    "NEED_EVIDENCE",
    "NEED_CLARIFICATION",
]
HumanReviewStatusValue = Literal[
    "OPEN",
    "IN_REVIEW",
    "NEED_CLARIFICATION",
    "NEED_EVIDENCE",
    "REJECTED",
    "REOPENED",
    "RESOLVED",
    "CLOSED",
]
HumanDeltaStatusValue = Literal["PENDING", "COMPARING", "READY", "SUPERSEDED"]
EvidenceStatusValue = Literal["UNCONFIRMED", "CONFIRMED", "INVALID"]
EvidenceTypeValue = Literal["CODE", "TEST", "RUNTIME", "REVIEW", "DECISION", "AI", "BUSINESS", "FAILURE"]
EvidenceSourceTypeValue = Literal[
    "COMMIT",
    "MR",
    "DIFF",
    "FILE_PATH",
    "TEST_REPORT",
    "REVIEW_RECORD",
    "RUN_LOG",
    "HUMAN_CONFIRMATION",
    "OTHER",
]
DecisionStatusValue = Literal["PROPOSED", "ACCEPTED", "REJECTED", "SUPERSEDED"]
DecisionSourceTypeValue = Literal["CHAT_MESSAGE", "SPEC_PLAN_CHANGE", "TASK_CLOSEOUT", "TASK_DETAIL_BACKFILL"]
ClarificationStatusValue = Literal["OPEN", "ANSWERED", "ACCEPTED", "REJECTED", "CANCELLED", "CLOSED"]
ClarificationBlockingLevelValue = Literal["BLOCKING", "NON_BLOCKING"]
TaskFinalStatusValue = Literal["PENDING", "PARTIAL", "REJECTED", "VERIFIED"]


class WorkspaceAssetConnectionStatus(BaseModel):
    key: str
    label: str
    state: ConnectionState
    detail: Optional[str] = None


class WorkspaceAssetListState(BaseModel):
    empty: bool = True
    message: Optional[str] = None


class ExternalEvidenceRef(BaseModel):
    source_type: str
    source_uri: Optional[str] = None
    source_label: Optional[str] = None
    source_ref: Optional[str] = None
    source_path: Optional[str] = None
    source_metadata: Optional[Dict[str, Any]] = None


class RequirementLinkedTaskResponse(BaseModel):
    link_id: str
    task_id: str
    task_name: str
    task_status: str
    current_phase: Optional[str] = None
    relation_type: str
    coverage_status: CoverageStatus = "not_available"
    created_at: Optional[datetime] = None


class RequirementCoverageSummary(BaseModel):
    coverage_status: str = "not_available"
    coverage_reason: str = "Coverage is derived from Task process assets, Evidence, and human confirmation."
    related_task_count: int = 0
    evidence_count: int = 0
    human_review_count: int = 0
    human_delta_count: int = 0


class RequirementSummary(BaseModel):
    id: str
    workspace_id: str
    title: str
    body: Optional[str] = None
    status: str
    acceptance_criteria: List[str] = Field(default_factory=list)
    priority: Optional[str] = None
    parent_requirement_id: Optional[str] = None
    parent_title: Optional[str] = None
    child_count: int = 0
    children: List["RequirementSummary"] = Field(default_factory=list)
    can_link_task: bool = True
    import_batch_id: Optional[str] = None
    source_kind: Optional[str] = None
    source_uri: Optional[str] = None
    source_ref: Optional[str] = None
    source_metadata: Optional[Dict[str, Any]] = None
    coverage_summary: RequirementCoverageSummary = Field(default_factory=RequirementCoverageSummary)
    change_history_count: int = 0
    related_task_count: int = 0
    linked_tasks: List[RequirementLinkedTaskResponse] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RequirementAuditLogResponse(BaseModel):
    id: str
    workspace_id: str
    requirement_id: Optional[str] = None
    import_batch_id: Optional[str] = None
    task_id: Optional[str] = None
    actor_id: Optional[str] = None
    action: str
    before: Optional[Dict[str, Any]] = None
    after: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None
    source_metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None


class RequirementDetailResponse(BaseModel):
    requirement: RequirementSummary
    linked_tasks: List[RequirementLinkedTaskResponse] = Field(default_factory=list)
    children: List[RequirementSummary] = Field(default_factory=list)
    audit_logs: List[RequirementAuditLogResponse] = Field(default_factory=list)


class RequirementCreateRequest(BaseModel):
    title: str
    body: Optional[str] = None
    acceptance_criteria: List[str] = Field(default_factory=list)
    priority: Optional[str] = None
    parent_requirement_id: Optional[str] = None
    status: RequirementEditableStatus = "DRAFT"
    source_kind: Optional[str] = None
    source_uri: Optional[str] = None
    source_ref: Optional[str] = None
    source_metadata: Optional[Dict[str, Any]] = None
    change_reason: Optional[str] = None


class RequirementUpdateRequest(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    acceptance_criteria: Optional[List[str]] = None
    priority: Optional[str] = None
    status: Optional[RequirementEditableStatus] = None
    source_kind: Optional[str] = None
    source_uri: Optional[str] = None
    source_ref: Optional[str] = None
    source_metadata: Optional[Dict[str, Any]] = None
    change_reason: Optional[str] = None


class RequirementTaskLinkRequest(BaseModel):
    task_id: str
    relation_type: str = "RELATES_TO"
    change_reason: Optional[str] = None


class RequirementImportPreviewItem(BaseModel):
    id: str
    title: str
    body: Optional[str] = None
    acceptance_criteria: List[str] = Field(default_factory=list)
    priority: Optional[str] = None
    task_prompt: Optional[str] = None
    source_ref: Optional[str] = None
    source_metadata: Optional[Dict[str, Any]] = None
    order_index: int = 0
    status: str
    requirement_id: Optional[str] = None


class RequirementImportBatchResponse(BaseModel):
    id: str
    workspace_id: str
    source_kind: Optional[str] = None
    source_filename: Optional[str] = None
    source_uri: Optional[str] = None
    source_ref: Optional[str] = None
    source_metadata: Optional[Dict[str, Any]] = None
    status: str
    item_count: int = 0
    confirmed_count: int = 0
    normalized_markdown: Optional[str] = None
    items: List[RequirementImportPreviewItem] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RequirementPreviewJobResponse(BaseModel):
    job_id: str
    workspace_id: str
    status: str
    progress: int = 0
    message: Optional[str] = None
    error: Optional[str] = None
    batch: Optional[RequirementImportBatchResponse] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RequirementImportConfirmItem(BaseModel):
    item_id: str
    include: bool = True
    title: Optional[str] = None
    body: Optional[str] = None
    acceptance_criteria: Optional[List[str]] = None
    priority: Optional[str] = None
    task_prompt: Optional[str] = None
    status: RequirementEditableStatus = "DRAFT"


class RequirementImportConfirmRequest(BaseModel):
    items: List[RequirementImportConfirmItem] = Field(default_factory=list)
    change_reason: Optional[str] = None


class RequirementSplitPreviewRequest(BaseModel):
    change_reason: Optional[str] = None


class RequirementSplitItemRequest(BaseModel):
    item_id: str
    include: bool = True
    title: Optional[str] = None
    body: Optional[str] = None
    acceptance_criteria: Optional[List[str]] = None
    priority: Optional[str] = None
    task_prompt: Optional[str] = None


class RequirementSplitRequest(BaseModel):
    batch_id: str
    items: List[RequirementSplitItemRequest] = Field(default_factory=list)
    change_reason: Optional[str] = None


class TaskRequirementLinkResponse(BaseModel):
    id: str
    requirement_id: str
    task_id: str
    relation_type: str
    requirement: Optional[RequirementSummary] = None
    created_at: Optional[datetime] = None


class TaskAssetSummary(BaseModel):
    id: str
    asset_type: str
    title: str
    status: str
    content_text: Optional[str] = None
    content_json: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PlanNodeAssetSummary(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    status: str
    order_index: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AiRunSummary(BaseModel):
    id: str
    task_id: Optional[str] = None
    channel: str
    status: str
    progress: int = 0
    message: Optional[str] = None
    input_summary: Optional[str] = None
    output_summary: Optional[str] = None
    adoption_status: str = "not_available"
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class AiOutputResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: Optional[str] = None
    ai_job_id: str
    output_type: str
    title: Optional[str] = None
    content_text: Optional[str] = None
    content_json: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None


class HumanReviewCommentResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    review_id: str
    author_id: Optional[str] = None
    comment_type: Optional[str] = None
    body: str
    required_change: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None


class HumanReviewResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    reviewer_id: Optional[str] = None
    status: str
    outcome: Optional[str] = None
    review_type: Optional[str] = None
    review_scope: Optional[str] = None
    priority: Optional[str] = None
    title: Optional[str] = None
    body: Optional[str] = None
    source_ref: Optional[Dict[str, Any]] = None
    target_ref: Optional[Dict[str, Any]] = None
    target_refs: List[Dict[str, Any]] = Field(default_factory=list)
    derived_status: Optional[str] = None
    due_date: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    linked_clarification_ids: List[str] = Field(default_factory=list)
    comments: List[HumanReviewCommentResponse] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ChangeProposalSummary(BaseModel):
    id: str
    proposal_no: int
    patch_set_no: int
    base_branch: str
    changed_files_count: int = 0
    insertions: int = 0
    deletions: int = 0


class EvidenceSummary(BaseModel):
    id: str
    source_type: str
    source_ref: Optional[str] = None
    source_uri: Optional[str] = None
    title: Optional[str] = None


class DiffLineItem(BaseModel):
    type: Literal["add", "del", "context"]
    content: str
    old_line_no: Optional[int] = None
    new_line_no: Optional[int] = None
    source: Optional[Literal["ai", "human", "both", "context"]] = None


class DiffHunk(BaseModel):
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: List[DiffLineItem] = []


class HumanDeltaFileDiff(BaseModel):
    file_path: str
    old_path: Optional[str] = None
    new_path: Optional[str] = None
    change_type: str = "modified"
    insertions: int = 0
    deletions: int = 0
    hunks: List[DiffHunk] = []
    comparison_type: Optional[Literal["ai_only", "human_only", "common"]] = None
    ai_change_type: Optional[str] = None
    human_change_type: Optional[str] = None
    ai_insertions: int = 0
    ai_deletions: int = 0
    human_insertions: int = 0
    human_deletions: int = 0
    ai_hunks: Optional[List[DiffHunk]] = None
    human_hunks: Optional[List[DiffHunk]] = None


class HumanDeltaResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    proposal_id: Optional[str] = None
    final_evidence_id: Optional[str] = None
    status: str
    diff_asset_id: Optional[str] = None
    changed_files_count: Optional[int] = None
    insertions: Optional[int] = None
    deletions: Optional[int] = None
    comparison_summary: Optional[str] = None
    change_category: Optional[str] = None
    change_reason: Optional[str] = None
    promote_candidate: bool = False
    proposal_summary: Optional[ChangeProposalSummary] = None
    final_evidence_summary: Optional[EvidenceSummary] = None
    diff_text: Optional[str] = None
    file_diffs: List[HumanDeltaFileDiff] = []
    decision_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DeltaRegionResponse(BaseModel):
    id: str
    delta_id: str
    file_path: str
    old_file_path: Optional[str] = None
    region_type: str
    region_source: str
    ai_line_start: Optional[int] = None
    ai_line_end: Optional[int] = None
    human_line_start: Optional[int] = None
    human_line_end: Optional[int] = None
    ai_insertions: int = 0
    ai_deletions: int = 0
    human_insertions: int = 0
    human_deletions: int = 0
    summary: Optional[str] = None
    decisions: List[DecisionLightResponse] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class PatchSnapshot(BaseModel):
    source_type: str
    source_id: str
    source_label: str
    base_commit_sha: Optional[str] = None
    head_commit_sha: Optional[str] = None
    changed_files_count: int = 0
    insertions: int = 0
    deletions: int = 0


class WorkbenchDeltaResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    status: str
    change_category: Optional[str] = None
    change_reason: Optional[str] = None
    promote_candidate: bool = False
    ai_patch: Optional[PatchSnapshot] = None
    human_patch: Optional[PatchSnapshot] = None
    file_diffs: List[HumanDeltaFileDiff] = Field(default_factory=list)
    delta_regions: List[DeltaRegionResponse] = Field(default_factory=list)
    changed_files_count: Optional[int] = None
    insertions: Optional[int] = None
    deletions: Optional[int] = None
    comparison_summary: Optional[str] = None
    decision_count: int = 0
    decisions: List[DecisionLightResponse] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class EvidenceResponse(BaseModel):
    id: str
    workspace_id: str
    requirement_id: Optional[str] = None
    task_id: Optional[str] = None
    ai_job_id: Optional[str] = None
    human_review_id: Optional[str] = None
    status: str
    evidence_type: str = "CODE"
    source: ExternalEvidenceRef
    title: Optional[str] = None
    summary: Optional[str] = None
    confirmed_by_id: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DecisionSourceResponse(BaseModel):
    source_type: DecisionSourceTypeValue
    label: str
    chat_message_id: Optional[str] = None
    asset_id: Optional[str] = None
    asset_version_id: Optional[str] = None
    asset_thread_id: Optional[str] = None
    resolution_proposal_id: Optional[str] = None
    final_summary_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class DecisionResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    requirement_id: Optional[str] = None
    human_delta_id: Optional[str] = None
    delta_region_id: Optional[str] = None
    status: str
    title: str
    body: Optional[str] = None
    rationale: Optional[str] = None
    impact_scope: Optional[str] = None
    source_evidence_id: Optional[str] = None
    source_type: DecisionSourceTypeValue = "TASK_DETAIL_BACKFILL"
    source_chat_message_id: Optional[str] = None
    source_asset_id: Optional[str] = None
    source_asset_version_id: Optional[str] = None
    source_asset_thread_id: Optional[str] = None
    source_resolution_proposal_id: Optional[str] = None
    source_final_summary_id: Optional[str] = None
    source_metadata: Optional[Dict[str, Any]] = None
    delta_line_refs: Optional[List[Dict[str, Any]]] = None
    source: Optional[DecisionSourceResponse] = None
    decided_by_id: Optional[str] = None
    promote_candidate: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class ClarificationResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    requirement_id: Optional[str] = None
    status: str
    blocking_level: str = "NON_BLOCKING"
    question: str
    answer: Optional[str] = None
    requester_id: Optional[str] = None
    responder_id: Optional[str] = None
    source_evidence_id: Optional[str] = None
    source_review_id: Optional[str] = None
    clarification_type: Optional[str] = None
    target_ref: Optional[Dict[str, Any]] = None
    urgency: Optional[str] = None
    answered_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    promote_candidate: bool = False
    converted_requirement_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TaskFinalSummaryResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    author_id: Optional[str] = None
    final_status: str
    summary: Optional[str] = None
    remaining_risk: Optional[str] = None
    next_steps: Optional[str] = None
    final_evidence_ids: List[str] = Field(default_factory=list)
    review_checklist: Optional[Dict[str, Any]] = None
    clarification_summary: Optional[Dict[str, Any]] = None
    delta_summary: Optional[Dict[str, Any]] = None
    decision_summary: Optional[Dict[str, Any]] = None
    human_confirmation_review_id: Optional[str] = None
    verified_at: Optional[datetime] = None
    verified_by_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TaskProcessAuditLogResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    actor_id: Optional[str] = None
    record_type: str
    record_id: str
    action: str
    before: Optional[Dict[str, Any]] = None
    after: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None
    created_at: Optional[datetime] = None


class TaskFileItemResponse(BaseModel):
    id: str
    file_type: str
    title: str
    status: str
    source_kind: str
    source_id: Optional[str] = None
    source_version_id: Optional[str] = None
    source_path: Optional[str] = None
    summary: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class KnowledgeAssetResponse(BaseModel):
    id: str
    workspace_id: str
    asset_type: str
    status: str
    title: str
    body: Optional[str] = None
    source_task_id: Optional[str] = None
    source_decision_id: Optional[str] = None
    source_human_delta_id: Optional[str] = None
    source_clarification_id: Optional[str] = None
    source_review_id: Optional[str] = None
    source_evidence_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TaskSummary(BaseModel):
    id: str
    workspace_id: str
    creator_id: Optional[str] = None
    creator_display_name: Optional[str] = None
    name: str
    description: Optional[str] = None
    status: str
    current_phase: Optional[str] = None
    requirement_count: int = 0
    spec_count: int = 0
    plan_count: int = 0
    ai_run_count: int = 0
    human_review_count: int = 0
    human_delta_count: int = 0
    evidence_count: int = 0
    decision_count: int = 0
    clarification_count: int = 0
    coverage_status: CoverageStatus = "not_available"
    baseline_version: int = 0
    baselined_at: Optional[datetime] = None
    baselined_by_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_following: bool = False


class TaskProcessSummary(BaseModel):
    spec_status: str = "not_connected"
    plan_status: str = "not_connected"
    ai_run_status: str = "not_connected"
    human_review_status: str = "not_connected"
    human_delta_status: str = "not_connected"
    evidence_status: str = "not_connected"
    coverage_status: CoverageStatus = "not_available"
    risk_status: str = "not_available"


class TaskDetailResponse(BaseModel):
    task: TaskSummary
    requirement_links: List[TaskRequirementLinkResponse] = Field(default_factory=list)
    task_files: List[TaskFileItemResponse] = Field(default_factory=list)
    specs: List[TaskAssetSummary] = Field(default_factory=list)
    plans: List[TaskAssetSummary] = Field(default_factory=list)
    plan_nodes: List[PlanNodeAssetSummary] = Field(default_factory=list)
    ai_runs: List[AiRunSummary] = Field(default_factory=list)
    ai_outputs: List[AiOutputResponse] = Field(default_factory=list)
    human_reviews: List[HumanReviewResponse] = Field(default_factory=list)
    human_deltas: List[HumanDeltaResponse] = Field(default_factory=list)
    evidence: List[EvidenceResponse] = Field(default_factory=list)
    decisions: List[DecisionResponse] = Field(default_factory=list)
    clarifications: List[ClarificationResponse] = Field(default_factory=list)
    final_summary: Optional[TaskFinalSummaryResponse] = None
    process_audit_logs: List[TaskProcessAuditLogResponse] = Field(default_factory=list)
    process_summary: TaskProcessSummary = Field(default_factory=TaskProcessSummary)
    connection_status: List[WorkspaceAssetConnectionStatus] = Field(default_factory=list)


class HumanReviewCreateRequest(BaseModel):
    outcome: HumanReviewOutcomeValue
    status: HumanReviewStatusValue = "OPEN"
    review_type: Optional[str] = None
    review_scope: Optional[str] = None
    priority: Optional[str] = None
    title: Optional[str] = None
    body: Optional[str] = None
    source_ref: Optional[Dict[str, Any]] = None
    target_ref: Optional[Dict[str, Any]] = None
    target_refs: List[Dict[str, Any]] = Field(default_factory=list)
    due_date: Optional[datetime] = None
    change_reason: Optional[str] = None


class HumanReviewUpdateRequest(BaseModel):
    outcome: Optional[HumanReviewOutcomeValue] = None
    status: Optional[HumanReviewStatusValue] = None
    review_type: Optional[str] = None
    review_scope: Optional[str] = None
    priority: Optional[str] = None
    title: Optional[str] = None
    body: Optional[str] = None
    source_ref: Optional[Dict[str, Any]] = None
    target_ref: Optional[Dict[str, Any]] = None
    target_refs: Optional[List[Dict[str, Any]]] = None
    due_date: Optional[datetime] = None
    change_reason: Optional[str] = None


class HumanReviewCommentCreateRequest(BaseModel):
    comment_type: Optional[str] = None
    body: str
    required_change: Optional[Dict[str, Any]] = None
    change_reason: Optional[str] = None


class HumanDeltaCreateRequest(BaseModel):
    proposal_id: Optional[str] = None
    final_evidence_id: Optional[str] = None
    change_category: Optional[str] = None
    change_reason: Optional[str] = None
    promote_candidate: bool = False
    audit_reason: Optional[str] = None


class HumanDeltaUpdateRequest(BaseModel):
    change_category: Optional[str] = None
    change_reason: Optional[str] = None
    promote_candidate: Optional[bool] = None
    audit_reason: Optional[str] = None


class EvidenceCreateRequest(BaseModel):
    requirement_id: Optional[str] = None
    ai_job_id: Optional[str] = None
    human_review_id: Optional[str] = None
    status: EvidenceStatusValue = "UNCONFIRMED"
    evidence_type: EvidenceTypeValue = "CODE"
    source_type: EvidenceSourceTypeValue
    source_uri: Optional[str] = None
    source_label: Optional[str] = None
    source_ref: Optional[str] = None
    source_path: Optional[str] = None
    source_metadata: Optional[Dict[str, Any]] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    confirmed: bool = False
    change_reason: Optional[str] = None


class EvidenceUpdateRequest(BaseModel):
    requirement_id: Optional[str] = None
    ai_job_id: Optional[str] = None
    human_review_id: Optional[str] = None
    status: Optional[EvidenceStatusValue] = None
    evidence_type: Optional[EvidenceTypeValue] = None
    source_type: Optional[EvidenceSourceTypeValue] = None
    source_uri: Optional[str] = None
    source_label: Optional[str] = None
    source_ref: Optional[str] = None
    source_path: Optional[str] = None
    source_metadata: Optional[Dict[str, Any]] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    confirmed: Optional[bool] = None
    change_reason: Optional[str] = None


class DecisionCreateRequest(BaseModel):
    requirement_id: Optional[str] = None
    human_delta_id: Optional[str] = None
    delta_region_id: Optional[str] = None
    status: DecisionStatusValue = "PROPOSED"
    title: str
    body: Optional[str] = None
    rationale: Optional[str] = None
    impact_scope: Optional[str] = None
    source_evidence_id: Optional[str] = None
    source_type: DecisionSourceTypeValue = "TASK_DETAIL_BACKFILL"
    source_chat_message_id: Optional[str] = None
    source_asset_id: Optional[str] = None
    source_asset_version_id: Optional[str] = None
    source_asset_thread_id: Optional[str] = None
    source_resolution_proposal_id: Optional[str] = None
    source_final_summary_id: Optional[str] = None
    source_metadata: Optional[Dict[str, Any]] = None
    delta_line_refs: Optional[List[Dict[str, Any]]] = None
    promote_candidate: bool = False
    change_reason: Optional[str] = None


class DecisionUpdateRequest(BaseModel):
    requirement_id: Optional[str] = None
    human_delta_id: Optional[str] = None
    delta_region_id: Optional[str] = None
    status: Optional[DecisionStatusValue] = None
    title: Optional[str] = None
    body: Optional[str] = None
    rationale: Optional[str] = None
    impact_scope: Optional[str] = None
    source_evidence_id: Optional[str] = None
    source_type: Optional[DecisionSourceTypeValue] = None
    source_chat_message_id: Optional[str] = None
    source_asset_id: Optional[str] = None
    source_asset_version_id: Optional[str] = None
    source_asset_thread_id: Optional[str] = None
    source_resolution_proposal_id: Optional[str] = None
    source_final_summary_id: Optional[str] = None
    source_metadata: Optional[Dict[str, Any]] = None
    delta_line_refs: Optional[List[Dict[str, Any]]] = None
    promote_candidate: Optional[bool] = None
    change_reason: Optional[str] = None


class ChatMessageDecisionCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    body: Optional[str] = None
    impact_scope: Optional[str] = Field(default=None, max_length=300)
    requirement_id: Optional[str] = None
    promote_candidate: bool = False
    change_reason: Optional[str] = None


class ClarificationCreateRequest(BaseModel):
    requirement_id: Optional[str] = None
    status: ClarificationStatusValue = "OPEN"
    blocking_level: ClarificationBlockingLevelValue = "NON_BLOCKING"
    question: str
    answer: Optional[str] = None
    source_evidence_id: Optional[str] = None
    source_review_id: Optional[str] = None
    clarification_type: Optional[str] = None
    target_ref: Optional[Dict[str, Any]] = None
    urgency: Optional[str] = None
    promote_candidate: bool = False
    converted_requirement_id: Optional[str] = None
    change_reason: Optional[str] = None


class ClarificationUpdateRequest(BaseModel):
    requirement_id: Optional[str] = None
    status: Optional[ClarificationStatusValue] = None
    blocking_level: Optional[ClarificationBlockingLevelValue] = None
    question: Optional[str] = None
    answer: Optional[str] = None
    source_evidence_id: Optional[str] = None
    source_review_id: Optional[str] = None
    clarification_type: Optional[str] = None
    target_ref: Optional[Dict[str, Any]] = None
    urgency: Optional[str] = None
    promote_candidate: Optional[bool] = None
    converted_requirement_id: Optional[str] = None
    change_reason: Optional[str] = None


class TaskFinalSummaryUpsertRequest(BaseModel):
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


class WorkspaceAssetsOverviewResponse(BaseModel):
    workspace_id: str
    requirement_count: int = 0
    task_count: int = 0
    ai_run_count: int = 0
    evidence_count: int = 0
    knowledge_asset_count: int = 0
    coverage_status: CoverageStatus = "not_available"
    connection_status: List[WorkspaceAssetConnectionStatus] = Field(default_factory=list)


class WorkspaceAssetsRequirementsResponse(BaseModel):
    workspace_id: str
    items: List[RequirementSummary] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    scope: str = "tree"
    state: WorkspaceAssetListState = Field(default_factory=WorkspaceAssetListState)
    connection_status: List[WorkspaceAssetConnectionStatus] = Field(default_factory=list)


class TaskListSummaryStats(BaseModel):
    review_pending_count: int = 0
    evidence_missing_count: int = 0
    human_delta_count: int = 0
    clarification_pending_count: int = 0


class WorkspaceAssetsTasksResponse(BaseModel):
    workspace_id: str
    items: List[TaskSummary] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    stats: TaskListSummaryStats = Field(default_factory=TaskListSummaryStats)
    state: WorkspaceAssetListState = Field(default_factory=WorkspaceAssetListState)
    connection_status: List[WorkspaceAssetConnectionStatus] = Field(default_factory=list)


class SpecCoverageMatrixTraceRefs(BaseModel):
    spec_ids: List[str] = Field(default_factory=list)
    plan_ids: List[str] = Field(default_factory=list)
    ai_run_ids: List[str] = Field(default_factory=list)
    human_review_ids: List[str] = Field(default_factory=list)
    human_delta_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    decision_ids: List[str] = Field(default_factory=list)
    clarification_ids: List[str] = Field(default_factory=list)


class SpecCoverageMatrixItem(BaseModel):
    id: str
    requirement_id: str
    requirement_title: str
    task_id: Optional[str] = None
    task_name: Optional[str] = None
    relation_type: Optional[str] = None
    spec_status: str = "empty"
    plan_status: str = "empty"
    ai_run_status: str = "empty"
    human_review_status: str = "empty"
    human_delta_status: str = "empty"
    evidence_status: str = "empty"
    coverage_status: SpecCoverageMatrixCoverageStatus = "missing"
    coverage_reason: str
    trace_refs: SpecCoverageMatrixTraceRefs = Field(default_factory=SpecCoverageMatrixTraceRefs)


class TraceabilityViewResponse(BaseModel):
    key: Literal["spec_coverage_matrix", "evidence_registry", "human_delta_dashboard", "risk_board"]
    title: str
    view_type: str
    items: List[Dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    state: WorkspaceAssetListState = Field(default_factory=WorkspaceAssetListState)


class WorkspaceAssetsTraceabilityResponse(BaseModel):
    workspace_id: str
    views: List[TraceabilityViewResponse] = Field(default_factory=list)
    connection_status: List[WorkspaceAssetConnectionStatus] = Field(default_factory=list)


class WorkspaceAssetsKnowledgeResponse(BaseModel):
    workspace_id: str
    items: List[KnowledgeAssetResponse] = Field(default_factory=list)
    total: int = 0
    state: WorkspaceAssetListState = Field(default_factory=WorkspaceAssetListState)
    connection_status: List[WorkspaceAssetConnectionStatus] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Task Detail lightweight / sectioned schemas
# ---------------------------------------------------------------------------


class TaskDetailSummaryResponse(BaseModel):
    """Lightweight task detail summary for initial page load. No sub-table entities."""

    task: TaskSummary
    requirement_links: List[TaskRequirementLinkResponse] = Field(default_factory=list)
    process_summary: TaskProcessSummary = Field(default_factory=TaskProcessSummary)
    connection_status: List[WorkspaceAssetConnectionStatus] = Field(default_factory=list)


class TaskFileItemLightResponse(BaseModel):
    """TaskFileItem without metadata -- for list views."""

    id: str
    file_type: str
    title: str
    status: str
    source_kind: str
    source_id: Optional[str] = None
    source_version_id: Optional[str] = None
    source_path: Optional[str] = None
    summary: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TaskFilesSectionResponse(BaseModel):
    items: List[TaskFileItemLightResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class HumanReviewLightResponse(BaseModel):
    """HumanReviewResponse without body/source_ref/comments for list views."""

    id: str
    workspace_id: str
    task_id: str
    reviewer_id: Optional[str] = None
    status: str
    outcome: Optional[str] = None
    review_type: Optional[str] = None
    review_scope: Optional[str] = None
    priority: Optional[str] = None
    title: Optional[str] = None
    due_date: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    linked_clarification_ids: List[str] = Field(default_factory=list)
    comment_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TaskHumanReviewsSectionResponse(BaseModel):
    items: List[HumanReviewLightResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class HumanDeltaLightResponse(BaseModel):
    """HumanDeltaResponse without diff_text."""

    id: str
    workspace_id: str
    task_id: str
    proposal_id: Optional[str] = None
    final_evidence_id: Optional[str] = None
    status: str
    diff_asset_id: Optional[str] = None
    changed_files_count: Optional[int] = None
    insertions: Optional[int] = None
    deletions: Optional[int] = None
    comparison_summary: Optional[str] = None
    change_category: Optional[str] = None
    change_reason: Optional[str] = None
    promote_candidate: bool = False
    proposal_summary: Optional[ChangeProposalSummary] = None
    final_evidence_summary: Optional[EvidenceSummary] = None
    decision_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TaskHumanDeltasSectionResponse(BaseModel):
    items: List[HumanDeltaLightResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class HumanDeltaSuggestionItem(BaseModel):
    proposal: ChangeProposalSummary
    evidence: EvidenceSummary


class HumanDeltaSuggestionsResponse(BaseModel):
    items: List[HumanDeltaSuggestionItem] = Field(default_factory=list)


class EvidenceLightResponse(BaseModel):
    """EvidenceResponse without source_metadata."""

    id: str
    workspace_id: str
    requirement_id: Optional[str] = None
    task_id: Optional[str] = None
    ai_job_id: Optional[str] = None
    human_review_id: Optional[str] = None
    status: str
    evidence_type: str = "CODE"
    source_type: str
    source_uri: Optional[str] = None
    source_label: Optional[str] = None
    source_ref: Optional[str] = None
    source_path: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    confirmed_by_id: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TaskEvidenceSectionResponse(BaseModel):
    items: List[EvidenceLightResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class DecisionLightResponse(BaseModel):
    """DecisionResponse without body/rationale/source_metadata."""

    id: str
    workspace_id: str
    task_id: str
    requirement_id: Optional[str] = None
    human_delta_id: Optional[str] = None
    delta_region_id: Optional[str] = None
    status: str
    title: str
    impact_scope: Optional[str] = None
    source_evidence_id: Optional[str] = None
    source_type: DecisionSourceTypeValue = "TASK_DETAIL_BACKFILL"
    source: Optional[DecisionSourceResponse] = None
    delta_line_refs: Optional[List[Dict[str, Any]]] = None
    decided_by_id: Optional[str] = None
    promote_candidate: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TaskDecisionsSectionResponse(BaseModel):
    items: List[DecisionLightResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class ClarificationLightResponse(BaseModel):
    """ClarificationResponse without answer."""

    id: str
    workspace_id: str
    task_id: str
    requirement_id: Optional[str] = None
    status: str
    blocking_level: str = "NON_BLOCKING"
    question: str
    requester_id: Optional[str] = None
    responder_id: Optional[str] = None
    source_evidence_id: Optional[str] = None
    source_review_id: Optional[str] = None
    clarification_type: Optional[str] = None
    urgency: Optional[str] = None
    answered_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    promote_candidate: bool = False
    converted_requirement_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TaskClarificationsSectionResponse(BaseModel):
    items: List[ClarificationLightResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class TaskProcessAuditLogLightResponse(BaseModel):
    """TaskProcessAuditLogResponse without before/after."""

    id: str
    workspace_id: str
    task_id: str
    actor_id: Optional[str] = None
    record_type: str
    record_id: str
    action: str
    reason: Optional[str] = None
    created_at: Optional[datetime] = None


class TaskProcessAuditSectionResponse(BaseModel):
    items: List[TaskProcessAuditLogLightResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class TaskFileDiffResponse(BaseModel):
    """Full diff content for a task file, loaded on demand."""

    file_id: str
    diff_text: str
