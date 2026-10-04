"""
Read-only schemas for Workspace Assets.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

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
    detail: str | None = None


class WorkspaceAssetListState(BaseModel):
    empty: bool = True
    message: str | None = None


class ExternalEvidenceRef(BaseModel):
    source_type: str
    source_uri: str | None = None
    source_label: str | None = None
    source_ref: str | None = None
    source_path: str | None = None
    source_metadata: dict[str, Any] | None = None


class RequirementOptionResponse(BaseModel):
    id: str
    title: str
    status: str
    source_ref: str | None = None
    parent_requirement_id: str | None = None
    parent_title: str | None = None
    child_count: int = 0
    can_link_task: bool = True


class RequirementOptionsResponse(BaseModel):
    items: list[RequirementOptionResponse]
    total: int
    page: int
    page_size: int


class RequirementLinkedTaskResponse(BaseModel):
    link_id: str
    task_id: str
    task_name: str
    task_status: str
    current_phase: str | None = None
    creator_name: str | None = None
    total_duration_ms: int = 0
    relation_type: str
    coverage_status: CoverageStatus = "not_available"
    created_at: datetime | None = None


class RequirementCoverageSummary(BaseModel):
    coverage_status: str = "not_available"
    coverage_reason: str = "Coverage is derived from Task process assets, Evidence, and human confirmation."
    related_task_count: int = 0
    evidence_count: int = 0
    human_review_count: int = 0
    human_delta_count: int = 0


class RequirementSummary(BaseModel):
    task_prompt: str | None = None
    id: str
    workspace_id: str
    title: str
    body: str | None = None
    status: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    priority: str | None = None
    parent_requirement_id: str | None = None
    parent_title: str | None = None
    child_count: int = 0
    children: list[RequirementSummary] = Field(default_factory=list)
    can_link_task: bool = True
    import_batch_id: str | None = None
    source_kind: str | None = None
    source_uri: str | None = None
    source_ref: str | None = None
    source_metadata: dict[str, Any] | None = None
    coverage_summary: RequirementCoverageSummary = Field(default_factory=RequirementCoverageSummary)
    change_history_count: int = 0
    related_task_count: int = 0
    linked_tasks: list[RequirementLinkedTaskResponse] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RequirementAuditLogResponse(BaseModel):
    id: str
    workspace_id: str
    requirement_id: str | None = None
    import_batch_id: str | None = None
    task_id: str | None = None
    actor_id: str | None = None
    action: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    reason: str | None = None
    source_metadata: dict[str, Any] | None = None
    created_at: datetime | None = None


class RequirementDetailResponse(BaseModel):
    requirement: RequirementSummary
    linked_tasks: list[RequirementLinkedTaskResponse] = Field(default_factory=list)
    children: list[RequirementSummary] = Field(default_factory=list)
    audit_logs: list[RequirementAuditLogResponse] = Field(default_factory=list)


class RequirementCreateRequest(BaseModel):
    task_prompt: str | None = None
    title: str
    body: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    priority: str | None = None
    parent_requirement_id: str | None = None
    status: RequirementEditableStatus = "DRAFT"
    source_kind: str | None = None
    source_uri: str | None = None
    source_ref: str | None = None
    source_metadata: dict[str, Any] | None = None
    change_reason: str | None = None


class RequirementUpdateRequest(BaseModel):
    task_prompt: str | None = None
    title: str | None = None
    body: str | None = None
    acceptance_criteria: list[str] | None = None
    priority: str | None = None
    status: RequirementEditableStatus | None = None
    source_kind: str | None = None
    source_uri: str | None = None
    source_ref: str | None = None
    source_metadata: dict[str, Any] | None = None
    change_reason: str | None = None


class RequirementTaskLinkRequest(BaseModel):
    task_id: str
    relation_type: str = "RELATES_TO"
    change_reason: str | None = None


class RequirementImportPreviewItem(BaseModel):
    id: str
    title: str
    body: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    priority: str | None = None
    task_prompt: str | None = None
    source_ref: str | None = None
    source_metadata: dict[str, Any] | None = None
    order_index: int = 0
    status: str
    requirement_id: str | None = None


class RequirementSplitDraftItem(BaseModel):
    item_id: str
    include: bool = True
    title: str | None = None
    body: str | None = None
    acceptance_criteria: list[str] | None = None
    priority: str | None = None
    task_prompt: str | None = None


class RequirementSplitDraftPayload(BaseModel):
    """拆分评审页未提交编辑的草稿结构：覆盖在批次原始 AI 预览之上的编辑态。"""

    change_reason: str | None = None
    items: list[RequirementSplitDraftItem] = Field(default_factory=list)


class RequirementImportBatchResponse(BaseModel):
    id: str
    workspace_id: str
    source_kind: str | None = None
    source_filename: str | None = None
    source_uri: str | None = None
    source_ref: str | None = None
    source_metadata: dict[str, Any] | None = None
    status: str
    item_count: int = 0
    confirmed_count: int = 0
    normalized_markdown: str | None = None
    items: list[RequirementImportPreviewItem] = Field(default_factory=list)
    draft: RequirementSplitDraftPayload | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RequirementPreviewJobResponse(BaseModel):
    job_id: str
    workspace_id: str
    status: str
    progress: int = 0
    message: str | None = None
    error: str | None = None
    batch: RequirementImportBatchResponse | None = None
    # 作业种类与关联对象（来自 context_json）：供前端浮窗区分拆分/导入并回跳
    job_kind: str | None = None
    requirement_id: str | None = None
    requirement_title: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RequirementImportConfirmItem(BaseModel):
    item_id: str
    include: bool = True
    title: str | None = None
    body: str | None = None
    acceptance_criteria: list[str] | None = None
    priority: str | None = None
    task_prompt: str | None = None
    status: RequirementEditableStatus = "DRAFT"


class RequirementImportConfirmRequest(BaseModel):
    items: list[RequirementImportConfirmItem] = Field(default_factory=list)
    change_reason: str | None = None


class RequirementSplitPreviewRequest(BaseModel):
    change_reason: str | None = None


class RequirementSplitItemRequest(BaseModel):
    item_id: str
    include: bool = True
    title: str | None = None
    body: str | None = None
    acceptance_criteria: list[str] | None = None
    priority: str | None = None
    task_prompt: str | None = None


class RequirementSplitRequest(BaseModel):
    batch_id: str
    items: list[RequirementSplitItemRequest] = Field(default_factory=list)
    change_reason: str | None = None


class TaskRequirementLinkResponse(BaseModel):
    id: str
    requirement_id: str
    task_id: str
    relation_type: str
    requirement: RequirementSummary | None = None
    created_at: datetime | None = None


class TaskAssetSummary(BaseModel):
    id: str
    asset_type: str
    title: str
    status: str
    content_text: str | None = None
    content_json: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PlanNodeAssetSummary(BaseModel):
    id: str
    title: str
    description: str | None = None
    status: str
    order_index: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AiRunSummary(BaseModel):
    id: str
    task_id: str | None = None
    channel: str
    status: str
    progress: int = 0
    message: str | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    adoption_status: str = "not_available"
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AiOutputResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str | None = None
    ai_job_id: str
    output_type: str
    title: str | None = None
    content_text: str | None = None
    content_json: dict[str, Any] | None = None
    created_at: datetime | None = None


class HumanReviewCommentResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    review_id: str
    author_id: str | None = None
    comment_type: str | None = None
    body: str
    required_change: dict[str, Any] | None = None
    created_at: datetime | None = None


class HumanReviewResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    reviewer_id: str | None = None
    status: str
    outcome: str | None = None
    review_type: str | None = None
    review_scope: str | None = None
    priority: str | None = None
    title: str | None = None
    body: str | None = None
    source_ref: dict[str, Any] | None = None
    target_ref: dict[str, Any] | None = None
    target_refs: list[dict[str, Any]] = Field(default_factory=list)
    derived_status: str | None = None
    due_date: datetime | None = None
    resolved_at: datetime | None = None
    linked_clarification_ids: list[str] = Field(default_factory=list)
    comments: list[HumanReviewCommentResponse] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


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
    source_ref: str | None = None
    source_uri: str | None = None
    title: str | None = None


class DiffLineItem(BaseModel):
    type: Literal["add", "del", "context"]
    content: str
    old_line_no: int | None = None
    new_line_no: int | None = None
    source: Literal["ai", "human", "both", "context"] | None = None


class DiffHunk(BaseModel):
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[DiffLineItem] = []


class HumanDeltaFileDiff(BaseModel):
    file_path: str
    old_path: str | None = None
    new_path: str | None = None
    change_type: str = "modified"
    insertions: int = 0
    deletions: int = 0
    hunks: list[DiffHunk] = []
    comparison_type: Literal["ai_only", "human_only", "common"] | None = None
    ai_change_type: str | None = None
    human_change_type: str | None = None
    ai_insertions: int = 0
    ai_deletions: int = 0
    human_insertions: int = 0
    human_deletions: int = 0
    ai_hunks: list[DiffHunk] | None = None
    human_hunks: list[DiffHunk] | None = None


class HumanDeltaResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    proposal_id: str | None = None
    final_evidence_id: str | None = None
    status: str
    diff_asset_id: str | None = None
    changed_files_count: int | None = None
    insertions: int | None = None
    deletions: int | None = None
    comparison_summary: str | None = None
    change_category: str | None = None
    change_reason: str | None = None
    promote_candidate: bool = False
    proposal_summary: ChangeProposalSummary | None = None
    final_evidence_summary: EvidenceSummary | None = None
    diff_text: str | None = None
    file_diffs: list[HumanDeltaFileDiff] = []
    decision_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DeltaRegionResponse(BaseModel):
    id: str
    delta_id: str
    file_path: str
    old_file_path: str | None = None
    region_type: str
    region_source: str
    ai_line_start: int | None = None
    ai_line_end: int | None = None
    human_line_start: int | None = None
    human_line_end: int | None = None
    ai_insertions: int = 0
    ai_deletions: int = 0
    human_insertions: int = 0
    human_deletions: int = 0
    summary: str | None = None
    decisions: list[DecisionLightResponse] = Field(default_factory=list)
    created_at: datetime | None = None


class PatchSnapshot(BaseModel):
    source_type: str
    source_id: str
    source_label: str
    base_commit_sha: str | None = None
    head_commit_sha: str | None = None
    changed_files_count: int = 0
    insertions: int = 0
    deletions: int = 0


class WorkbenchDeltaResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    status: str
    change_category: str | None = None
    change_reason: str | None = None
    promote_candidate: bool = False
    ai_patch: PatchSnapshot | None = None
    human_patch: PatchSnapshot | None = None
    file_diffs: list[HumanDeltaFileDiff] = Field(default_factory=list)
    delta_regions: list[DeltaRegionResponse] = Field(default_factory=list)
    changed_files_count: int | None = None
    insertions: int | None = None
    deletions: int | None = None
    comparison_summary: str | None = None
    decision_count: int = 0
    decisions: list[DecisionLightResponse] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class EvidenceResponse(BaseModel):
    id: str
    workspace_id: str
    requirement_id: str | None = None
    task_id: str | None = None
    ai_job_id: str | None = None
    human_review_id: str | None = None
    status: str
    evidence_type: str = "CODE"
    source: ExternalEvidenceRef
    title: str | None = None
    summary: str | None = None
    confirmed_by_id: str | None = None
    confirmed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DecisionSourceResponse(BaseModel):
    source_type: DecisionSourceTypeValue
    label: str
    chat_message_id: str | None = None
    asset_id: str | None = None
    asset_version_id: str | None = None
    asset_thread_id: str | None = None
    resolution_proposal_id: str | None = None
    final_summary_id: str | None = None
    metadata: dict[str, Any] | None = None


class DecisionResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    requirement_id: str | None = None
    human_delta_id: str | None = None
    delta_region_id: str | None = None
    status: str
    title: str
    body: str | None = None
    rationale: str | None = None
    impact_scope: str | None = None
    source_evidence_id: str | None = None
    source_type: DecisionSourceTypeValue = "TASK_DETAIL_BACKFILL"
    source_chat_message_id: str | None = None
    source_asset_id: str | None = None
    source_asset_version_id: str | None = None
    source_asset_thread_id: str | None = None
    source_resolution_proposal_id: str | None = None
    source_final_summary_id: str | None = None
    source_metadata: dict[str, Any] | None = None
    delta_line_refs: list[dict[str, Any]] | None = None
    source: DecisionSourceResponse | None = None
    decided_by_id: str | None = None
    promote_candidate: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ClarificationResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    requirement_id: str | None = None
    status: str
    blocking_level: str = "NON_BLOCKING"
    question: str
    answer: str | None = None
    requester_id: str | None = None
    responder_id: str | None = None
    source_evidence_id: str | None = None
    source_review_id: str | None = None
    clarification_type: str | None = None
    target_ref: dict[str, Any] | None = None
    urgency: str | None = None
    answered_at: datetime | None = None
    accepted_at: datetime | None = None
    promote_candidate: bool = False
    converted_requirement_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TaskFinalSummaryResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    author_id: str | None = None
    final_status: str
    summary: str | None = None
    remaining_risk: str | None = None
    next_steps: str | None = None
    final_evidence_ids: list[str] = Field(default_factory=list)
    review_checklist: dict[str, Any] | None = None
    clarification_summary: dict[str, Any] | None = None
    delta_summary: dict[str, Any] | None = None
    decision_summary: dict[str, Any] | None = None
    human_confirmation_review_id: str | None = None
    verified_at: datetime | None = None
    verified_by_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TaskProcessAuditLogResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    actor_id: str | None = None
    record_type: str
    record_id: str
    action: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    reason: str | None = None
    created_at: datetime | None = None


class TaskFileItemResponse(BaseModel):
    id: str
    file_type: str
    title: str
    status: str
    source_kind: str
    source_id: str | None = None
    source_version_id: str | None = None
    source_path: str | None = None
    summary: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class KnowledgeAssetResponse(BaseModel):
    id: str
    workspace_id: str
    asset_type: str
    status: str
    title: str
    body: str | None = None
    source_task_id: str | None = None
    source_decision_id: str | None = None
    source_human_delta_id: str | None = None
    source_clarification_id: str | None = None
    source_review_id: str | None = None
    source_evidence_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TaskSummary(BaseModel):
    id: str
    execution_location: str = "SERVER"
    workspace_id: str
    creator_id: str | None = None
    creator_display_name: str | None = None
    name: str
    description: str | None = None
    status: str
    current_phase: str | None = None
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
    baselined_at: datetime | None = None
    baselined_by_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
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
    requirement_links: list[TaskRequirementLinkResponse] = Field(default_factory=list)
    task_files: list[TaskFileItemResponse] = Field(default_factory=list)
    specs: list[TaskAssetSummary] = Field(default_factory=list)
    plans: list[TaskAssetSummary] = Field(default_factory=list)
    plan_nodes: list[PlanNodeAssetSummary] = Field(default_factory=list)
    ai_runs: list[AiRunSummary] = Field(default_factory=list)
    ai_outputs: list[AiOutputResponse] = Field(default_factory=list)
    human_reviews: list[HumanReviewResponse] = Field(default_factory=list)
    human_deltas: list[HumanDeltaResponse] = Field(default_factory=list)
    evidence: list[EvidenceResponse] = Field(default_factory=list)
    decisions: list[DecisionResponse] = Field(default_factory=list)
    clarifications: list[ClarificationResponse] = Field(default_factory=list)
    final_summary: TaskFinalSummaryResponse | None = None
    process_audit_logs: list[TaskProcessAuditLogResponse] = Field(default_factory=list)
    process_summary: TaskProcessSummary = Field(default_factory=TaskProcessSummary)
    connection_status: list[WorkspaceAssetConnectionStatus] = Field(default_factory=list)


class HumanReviewCreateRequest(BaseModel):
    outcome: HumanReviewOutcomeValue
    status: HumanReviewStatusValue = "OPEN"
    review_type: str | None = None
    review_scope: str | None = None
    priority: str | None = None
    title: str | None = None
    body: str | None = None
    source_ref: dict[str, Any] | None = None
    target_ref: dict[str, Any] | None = None
    target_refs: list[dict[str, Any]] = Field(default_factory=list)
    due_date: datetime | None = None
    change_reason: str | None = None


class HumanReviewUpdateRequest(BaseModel):
    outcome: HumanReviewOutcomeValue | None = None
    status: HumanReviewStatusValue | None = None
    review_type: str | None = None
    review_scope: str | None = None
    priority: str | None = None
    title: str | None = None
    body: str | None = None
    source_ref: dict[str, Any] | None = None
    target_ref: dict[str, Any] | None = None
    target_refs: list[dict[str, Any]] | None = None
    due_date: datetime | None = None
    change_reason: str | None = None


class HumanReviewCommentCreateRequest(BaseModel):
    comment_type: str | None = None
    body: str
    required_change: dict[str, Any] | None = None
    change_reason: str | None = None


class HumanDeltaCreateRequest(BaseModel):
    proposal_id: str | None = None
    final_evidence_id: str | None = None
    change_category: str | None = None
    change_reason: str | None = None
    promote_candidate: bool = False
    audit_reason: str | None = None


class HumanDeltaUpdateRequest(BaseModel):
    change_category: str | None = None
    change_reason: str | None = None
    promote_candidate: bool | None = None
    audit_reason: str | None = None


class EvidenceCreateRequest(BaseModel):
    requirement_id: str | None = None
    ai_job_id: str | None = None
    human_review_id: str | None = None
    status: EvidenceStatusValue = "UNCONFIRMED"
    evidence_type: EvidenceTypeValue = "CODE"
    source_type: EvidenceSourceTypeValue
    source_uri: str | None = None
    source_label: str | None = None
    source_ref: str | None = None
    source_path: str | None = None
    source_metadata: dict[str, Any] | None = None
    title: str | None = None
    summary: str | None = None
    confirmed: bool = False
    change_reason: str | None = None


class EvidenceUpdateRequest(BaseModel):
    requirement_id: str | None = None
    ai_job_id: str | None = None
    human_review_id: str | None = None
    status: EvidenceStatusValue | None = None
    evidence_type: EvidenceTypeValue | None = None
    source_type: EvidenceSourceTypeValue | None = None
    source_uri: str | None = None
    source_label: str | None = None
    source_ref: str | None = None
    source_path: str | None = None
    source_metadata: dict[str, Any] | None = None
    title: str | None = None
    summary: str | None = None
    confirmed: bool | None = None
    change_reason: str | None = None


class DecisionCreateRequest(BaseModel):
    requirement_id: str | None = None
    human_delta_id: str | None = None
    delta_region_id: str | None = None
    status: DecisionStatusValue = "PROPOSED"
    title: str
    body: str | None = None
    rationale: str | None = None
    impact_scope: str | None = None
    source_evidence_id: str | None = None
    source_type: DecisionSourceTypeValue = "TASK_DETAIL_BACKFILL"
    source_chat_message_id: str | None = None
    source_asset_id: str | None = None
    source_asset_version_id: str | None = None
    source_asset_thread_id: str | None = None
    source_resolution_proposal_id: str | None = None
    source_final_summary_id: str | None = None
    source_metadata: dict[str, Any] | None = None
    delta_line_refs: list[dict[str, Any]] | None = None
    promote_candidate: bool = False
    change_reason: str | None = None


class DecisionUpdateRequest(BaseModel):
    requirement_id: str | None = None
    human_delta_id: str | None = None
    delta_region_id: str | None = None
    status: DecisionStatusValue | None = None
    title: str | None = None
    body: str | None = None
    rationale: str | None = None
    impact_scope: str | None = None
    source_evidence_id: str | None = None
    source_type: DecisionSourceTypeValue | None = None
    source_chat_message_id: str | None = None
    source_asset_id: str | None = None
    source_asset_version_id: str | None = None
    source_asset_thread_id: str | None = None
    source_resolution_proposal_id: str | None = None
    source_final_summary_id: str | None = None
    source_metadata: dict[str, Any] | None = None
    delta_line_refs: list[dict[str, Any]] | None = None
    promote_candidate: bool | None = None
    change_reason: str | None = None


class ChatMessageDecisionCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    body: str | None = None
    impact_scope: str | None = Field(default=None, max_length=300)
    requirement_id: str | None = None
    promote_candidate: bool = False
    change_reason: str | None = None


class ClarificationCreateRequest(BaseModel):
    requirement_id: str | None = None
    status: ClarificationStatusValue = "OPEN"
    blocking_level: ClarificationBlockingLevelValue = "NON_BLOCKING"
    question: str
    answer: str | None = None
    source_evidence_id: str | None = None
    source_review_id: str | None = None
    clarification_type: str | None = None
    target_ref: dict[str, Any] | None = None
    urgency: str | None = None
    promote_candidate: bool = False
    converted_requirement_id: str | None = None
    change_reason: str | None = None


class ClarificationUpdateRequest(BaseModel):
    requirement_id: str | None = None
    status: ClarificationStatusValue | None = None
    blocking_level: ClarificationBlockingLevelValue | None = None
    question: str | None = None
    answer: str | None = None
    source_evidence_id: str | None = None
    source_review_id: str | None = None
    clarification_type: str | None = None
    target_ref: dict[str, Any] | None = None
    urgency: str | None = None
    promote_candidate: bool | None = None
    converted_requirement_id: str | None = None
    change_reason: str | None = None


class TaskFinalSummaryUpsertRequest(BaseModel):
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


class WorkspaceAssetsOverviewResponse(BaseModel):
    workspace_id: str
    requirement_count: int = 0
    task_count: int = 0
    ai_run_count: int = 0
    evidence_count: int = 0
    knowledge_asset_count: int = 0
    coverage_status: CoverageStatus = "not_available"
    connection_status: list[WorkspaceAssetConnectionStatus] = Field(default_factory=list)


class WorkspaceAssetsRequirementsResponse(BaseModel):
    workspace_id: str
    items: list[RequirementSummary] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    scope: str = "tree"
    state: WorkspaceAssetListState = Field(default_factory=WorkspaceAssetListState)
    connection_status: list[WorkspaceAssetConnectionStatus] = Field(default_factory=list)


class TaskListSummaryStats(BaseModel):
    review_pending_count: int = 0
    evidence_missing_count: int = 0
    human_delta_count: int = 0
    clarification_pending_count: int = 0


class WorkspaceAssetsTasksResponse(BaseModel):
    workspace_id: str
    items: list[TaskSummary] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    stats: TaskListSummaryStats = Field(default_factory=TaskListSummaryStats)
    state: WorkspaceAssetListState = Field(default_factory=WorkspaceAssetListState)
    connection_status: list[WorkspaceAssetConnectionStatus] = Field(default_factory=list)


class SpecCoverageMatrixTraceRefs(BaseModel):
    spec_ids: list[str] = Field(default_factory=list)
    plan_ids: list[str] = Field(default_factory=list)
    ai_run_ids: list[str] = Field(default_factory=list)
    human_review_ids: list[str] = Field(default_factory=list)
    human_delta_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    decision_ids: list[str] = Field(default_factory=list)
    clarification_ids: list[str] = Field(default_factory=list)


class SpecCoverageMatrixItem(BaseModel):
    id: str
    requirement_id: str
    requirement_title: str
    task_id: str | None = None
    task_name: str | None = None
    relation_type: str | None = None
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
    items: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    state: WorkspaceAssetListState = Field(default_factory=WorkspaceAssetListState)


class WorkspaceAssetsTraceabilityResponse(BaseModel):
    workspace_id: str
    views: list[TraceabilityViewResponse] = Field(default_factory=list)
    connection_status: list[WorkspaceAssetConnectionStatus] = Field(default_factory=list)


class WorkspaceAssetsKnowledgeResponse(BaseModel):
    workspace_id: str
    items: list[KnowledgeAssetResponse] = Field(default_factory=list)
    total: int = 0
    state: WorkspaceAssetListState = Field(default_factory=WorkspaceAssetListState)
    connection_status: list[WorkspaceAssetConnectionStatus] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Task Detail lightweight / sectioned schemas
# ---------------------------------------------------------------------------


class TaskDetailSummaryResponse(BaseModel):
    """Lightweight task detail summary for initial page load. No sub-table entities."""

    task: TaskSummary
    requirement_links: list[TaskRequirementLinkResponse] = Field(default_factory=list)
    process_summary: TaskProcessSummary = Field(default_factory=TaskProcessSummary)
    connection_status: list[WorkspaceAssetConnectionStatus] = Field(default_factory=list)


class TaskFileItemLightResponse(BaseModel):
    """TaskFileItem without metadata -- for list views."""

    id: str
    file_type: str
    title: str
    status: str
    source_kind: str
    source_id: str | None = None
    source_version_id: str | None = None
    source_path: str | None = None
    summary: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TaskFilesSectionResponse(BaseModel):
    items: list[TaskFileItemLightResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class HumanReviewLightResponse(BaseModel):
    """HumanReviewResponse without body/source_ref/comments for list views."""

    id: str
    workspace_id: str
    task_id: str
    reviewer_id: str | None = None
    status: str
    outcome: str | None = None
    review_type: str | None = None
    review_scope: str | None = None
    priority: str | None = None
    title: str | None = None
    due_date: datetime | None = None
    resolved_at: datetime | None = None
    linked_clarification_ids: list[str] = Field(default_factory=list)
    comment_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TaskHumanReviewsSectionResponse(BaseModel):
    items: list[HumanReviewLightResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class HumanDeltaLightResponse(BaseModel):
    """HumanDeltaResponse without diff_text."""

    id: str
    workspace_id: str
    task_id: str
    proposal_id: str | None = None
    final_evidence_id: str | None = None
    status: str
    diff_asset_id: str | None = None
    changed_files_count: int | None = None
    insertions: int | None = None
    deletions: int | None = None
    comparison_summary: str | None = None
    change_category: str | None = None
    change_reason: str | None = None
    promote_candidate: bool = False
    proposal_summary: ChangeProposalSummary | None = None
    final_evidence_summary: EvidenceSummary | None = None
    decision_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TaskHumanDeltasSectionResponse(BaseModel):
    items: list[HumanDeltaLightResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class HumanDeltaSuggestionItem(BaseModel):
    proposal: ChangeProposalSummary
    evidence: EvidenceSummary


class HumanDeltaSuggestionsResponse(BaseModel):
    items: list[HumanDeltaSuggestionItem] = Field(default_factory=list)


class EvidenceLightResponse(BaseModel):
    """EvidenceResponse without source_metadata."""

    id: str
    workspace_id: str
    requirement_id: str | None = None
    task_id: str | None = None
    ai_job_id: str | None = None
    human_review_id: str | None = None
    status: str
    evidence_type: str = "CODE"
    source_type: str
    source_uri: str | None = None
    source_label: str | None = None
    source_ref: str | None = None
    source_path: str | None = None
    title: str | None = None
    summary: str | None = None
    confirmed_by_id: str | None = None
    confirmed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TaskEvidenceSectionResponse(BaseModel):
    items: list[EvidenceLightResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class DecisionLightResponse(BaseModel):
    """DecisionResponse without body/rationale/source_metadata."""

    id: str
    workspace_id: str
    task_id: str
    requirement_id: str | None = None
    human_delta_id: str | None = None
    delta_region_id: str | None = None
    status: str
    title: str
    impact_scope: str | None = None
    source_evidence_id: str | None = None
    source_type: DecisionSourceTypeValue = "TASK_DETAIL_BACKFILL"
    source: DecisionSourceResponse | None = None
    delta_line_refs: list[dict[str, Any]] | None = None
    decided_by_id: str | None = None
    promote_candidate: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TaskDecisionsSectionResponse(BaseModel):
    items: list[DecisionLightResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class ClarificationLightResponse(BaseModel):
    """ClarificationResponse without answer."""

    id: str
    workspace_id: str
    task_id: str
    requirement_id: str | None = None
    status: str
    blocking_level: str = "NON_BLOCKING"
    question: str
    requester_id: str | None = None
    responder_id: str | None = None
    source_evidence_id: str | None = None
    source_review_id: str | None = None
    clarification_type: str | None = None
    urgency: str | None = None
    answered_at: datetime | None = None
    accepted_at: datetime | None = None
    promote_candidate: bool = False
    converted_requirement_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TaskClarificationsSectionResponse(BaseModel):
    items: list[ClarificationLightResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class TaskProcessAuditLogLightResponse(BaseModel):
    """TaskProcessAuditLogResponse without before/after."""

    id: str
    workspace_id: str
    task_id: str
    actor_id: str | None = None
    record_type: str
    record_id: str
    action: str
    reason: str | None = None
    created_at: datetime | None = None


class TaskProcessAuditSectionResponse(BaseModel):
    items: list[TaskProcessAuditLogLightResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class TaskFileDiffResponse(BaseModel):
    """Full diff content for a task file, loaded on demand."""

    file_id: str
    diff_text: str
