export type ConnectionState = 'NOT_CONNECTED' | 'EMPTY' | 'AVAILABLE' | 'ERROR'
export type CoverageStatus = 'not_available' | 'waiting_evidence' | 'waiting_human_confirmation' | 'verified'
export type RequirementEditableStatus =
  | 'DRAFT'
  | 'READY'
  | 'IN_PROGRESS'
  | 'VERIFIED'
  | 'REJECTED'
  | 'ARCHIVED'
  | 'ACTIVE'
  | 'WAITING_SOURCE'
export type SpecCoverageMatrixCoverageStatus =
  | 'missing'
  | 'spec_covered'
  | 'in_progress'
  | 'human_modified'
  | 'evidence_missing'
  | 'need_clarification'
  | 'rejected'
  | 'verified'
export type DecisionSourceType =
  | 'CHAT_MESSAGE'
  | 'SPEC_PLAN_CHANGE'
  | 'TASK_CLOSEOUT'
  | 'TASK_DETAIL_BACKFILL'

export type WorkspaceAssetConnectionStatus = {
  key: string
  label: string
  state: ConnectionState
  detail?: string | null
}

export type WorkspaceAssetListState = {
  empty: boolean
  message?: string | null
}

export type ExternalEvidenceRef = {
  source_type: string
  source_uri?: string | null
  source_label?: string | null
  source_ref?: string | null
  source_path?: string | null
  source_metadata?: Record<string, unknown> | null
}

export type RequirementLinkedTask = {
  link_id: string
  task_id: string
  task_name: string
  task_status: string
  current_phase?: string | null
  relation_type: string
  coverage_status: CoverageStatus
  created_at?: string | null
}

export type RequirementCoverageSummary = {
  coverage_status: string
  coverage_reason: string
  related_task_count: number
  evidence_count: number
  human_review_count: number
  human_delta_count: number
}

export type RequirementSummary = {
  id: string
  workspace_id: string
  title: string
  body?: string | null
  status: string
  acceptance_criteria: readonly string[]
  priority?: string | null
  parent_requirement_id?: string | null
  parent_title?: string | null
  child_count: number
  children?: readonly RequirementSummary[]
  can_link_task: boolean
  import_batch_id?: string | null
  source_kind?: string | null
  source_uri?: string | null
  source_ref?: string | null
  source_metadata?: Record<string, unknown> | null
  coverage_summary: RequirementCoverageSummary
  change_history_count: number
  related_task_count: number
  linked_tasks?: readonly RequirementLinkedTask[]
  created_at?: string | null
  updated_at?: string | null
}

export type RequirementAuditLog = {
  id: string
  workspace_id: string
  requirement_id?: string | null
  import_batch_id?: string | null
  task_id?: string | null
  actor_id?: string | null
  action: string
  before?: Record<string, unknown> | null
  after?: Record<string, unknown> | null
  reason?: string | null
  source_metadata?: Record<string, unknown> | null
  created_at?: string | null
}

export type RequirementDetail = {
  requirement: RequirementSummary
  linked_tasks: readonly RequirementLinkedTask[]
  children: readonly RequirementSummary[]
  audit_logs: readonly RequirementAuditLog[]
}

export type RequirementMutationPayload = {
  title?: string
  body?: string | null
  acceptance_criteria?: string[]
  priority?: string | null
  parent_requirement_id?: string | null
  status?: RequirementEditableStatus
  source_kind?: string | null
  source_uri?: string | null
  source_ref?: string | null
  source_metadata?: Record<string, unknown> | null
  change_reason?: string | null
}

export type RequirementListQuery = {
  q?: string | null
  status?: string | null
  priority?: string | null
  source_kind?: string | null
  parent_id?: string | null
  scope?: 'tree' | 'flat' | 'children'
  sort_by?: 'created_at' | 'updated_at' | 'title' | 'status' | 'priority' | 'child_count' | 'related_task_count'
  sort_order?: 'asc' | 'desc'
  page?: number
  page_size?: number
}

export type TaskListQuery = {
  q?: string | null
  requirement_q?: string | null
  status?: string | null
  current_phase?: string | null
  sort_by?: 'created_at' | 'updated_at' | 'name' | 'status' | 'current_phase' | 'requirement_count' | 'evidence_count'
  sort_order?: 'asc' | 'desc'
  page?: number
  page_size?: number
}

export type RequirementTaskLinkPayload = {
  task_id: string
  relation_type?: 'RELATES_TO' | 'COVERS'
  change_reason?: string | null
}

export type RequirementImportPreviewItem = {
  id: string
  title: string
  body?: string | null
  acceptance_criteria: string[]
  priority?: string | null
  task_prompt?: string | null
  source_ref?: string | null
  source_metadata?: Record<string, unknown> | null
  order_index: number
  status: string
  requirement_id?: string | null
}

export type RequirementImportBatch = {
  id: string
  workspace_id: string
  source_kind?: string | null
  source_filename?: string | null
  source_uri?: string | null
  source_ref?: string | null
  source_metadata?: Record<string, unknown> | null
  status: string
  item_count: number
  confirmed_count: number
  normalized_markdown?: string | null
  items: RequirementImportPreviewItem[]
  created_at?: string | null
  updated_at?: string | null
}

export type RequirementPreviewJob = {
  job_id: string
  workspace_id: string
  status: string
  progress: number
  message?: string | null
  error?: string | null
  batch?: RequirementImportBatch | null
  created_at?: string | null
  updated_at?: string | null
}

export type RequirementImportConfirmItem = {
  item_id: string
  include: boolean
  title?: string | null
  body?: string | null
  acceptance_criteria?: string[]
  priority?: string | null
  task_prompt?: string | null
  status?: RequirementEditableStatus
}

export type RequirementImportConfirmPayload = {
  items: RequirementImportConfirmItem[]
  change_reason?: string | null
}

export type RequirementSplitPayload = {
  batch_id: string
  items: RequirementImportConfirmItem[]
  change_reason?: string | null
}

export type TaskRequirementLink = {
  id: string
  requirement_id: string
  task_id: string
  relation_type: string
  requirement?: RequirementSummary | null
  created_at?: string | null
}

export type TaskAssetSummary = {
  id: string
  asset_type: string
  title: string
  status: string
  content_text?: string | null
  content_json?: Record<string, unknown> | null
  created_at?: string | null
  updated_at?: string | null
}

export type PlanNodeAssetSummary = {
  id: string
  title: string
  description?: string | null
  status: string
  order_index: number
  created_at?: string | null
  updated_at?: string | null
}

export type AiRunSummary = {
  id: string
  task_id?: string | null
  channel: string
  status: string
  progress: number
  message?: string | null
  input_summary?: string | null
  output_summary?: string | null
  adoption_status: string
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
}

export type AiOutput = {
  id: string
  workspace_id: string
  task_id?: string | null
  ai_job_id: string
  output_type: string
  title?: string | null
  content_text?: string | null
  content_json?: Record<string, unknown> | null
  created_at?: string | null
}

export type HumanReview = {
  id: string
  workspace_id: string
  task_id: string
  reviewer_id?: string | null
  status: string
  outcome?: string | null
  review_type?: string | null
  review_scope?: string | null
  priority?: string | null
  title?: string | null
  body?: string | null
  source_ref?: Record<string, unknown> | null
  target_ref?: Record<string, unknown> | null
  target_refs?: ReviewTargetRef[]
  derived_status?: ReviewDerivedStatus | null
  due_date?: string | null
  resolved_at?: string | null
  linked_clarification_ids?: string[]
  comments: HumanReviewComment[]
  created_at?: string | null
  updated_at?: string | null
}

export type HumanReviewComment = {
  id: string
  workspace_id: string
  task_id: string
  review_id: string
  author_id?: string | null
  comment_type?: string | null
  body: string
  required_change?: Record<string, unknown> | null
  created_at?: string | null
}

export type ChangeProposalSummary = {
  id: string
  proposal_no: number
  patch_set_no: number
  base_branch: string
  changed_files_count: number
  insertions: number
  deletions: number
}

export type EvidenceSummary = {
  id: string
  source_type: string
  source_ref?: string | null
  source_uri?: string | null
  title?: string | null
}

export type HumanDeltaSuggestion = {
  proposal: ChangeProposalSummary
  evidence: EvidenceSummary
}

export type DeltaLineRef = {
  file_path: string
  line_start: number
  line_end: number
  selected_text?: string
}

export type DiffLineItem = {
  type: 'add' | 'del' | 'context'
  content: string
  old_line_no?: number | null
  new_line_no?: number | null
  source?: 'ai' | 'human' | 'both' | 'context' | null
}

export type DiffHunk = {
  old_start: number
  old_count: number
  new_start: number
  new_count: number
  lines: DiffLineItem[]
}

export type HumanDeltaFileDiff = {
  file_path: string
  old_path?: string | null
  new_path?: string | null
  change_type: 'added' | 'deleted' | 'modified' | 'renamed'
  insertions: number
  deletions: number
  hunks: DiffHunk[]
  comparison_type?: 'ai_only' | 'human_only' | 'common' | null
  ai_change_type?: string | null
  human_change_type?: string | null
  ai_insertions?: number
  ai_deletions?: number
  human_insertions?: number
  human_deletions?: number
  ai_hunks?: DiffHunk[] | null
  human_hunks?: DiffHunk[] | null
}

export type HumanDelta = {
  id: string
  workspace_id: string
  task_id: string
  title?: string | null
  proposal_id?: string | null
  final_evidence_id?: string | null
  status: string
  diff_asset_id?: string | null
  changed_files_count?: number | null
  insertions?: number | null
  deletions?: number | null
  comparison_summary?: string | null
  change_category?: string | null
  change_reason?: string | null
  promote_candidate: boolean
  proposal_summary?: ChangeProposalSummary | null
  final_evidence_summary?: EvidenceSummary | null
  diff_text?: string | null
  file_diffs?: HumanDeltaFileDiff[]
  decision_count: number
  created_at?: string | null
  updated_at?: string | null
}

export type DeltaRegionType = 'FILE_ADDED' | 'FILE_DELETED' | 'FILE_RENAMED' | 'FILE_REWRITTEN' | 'HUNK_MODIFIED' | 'LINE_DIVERGED'
export type DeltaRegionSource = 'AI_ONLY' | 'HUMAN_ONLY' | 'BOTH_SAME' | 'DIVERGED'

export type DeltaRegion = {
  id: string
  delta_id: string
  file_path: string
  old_file_path?: string | null
  region_type: DeltaRegionType
  region_source: DeltaRegionSource
  ai_line_start?: number | null
  ai_line_end?: number | null
  human_line_start?: number | null
  human_line_end?: number | null
  ai_insertions: number
  ai_deletions: number
  human_insertions: number
  human_deletions: number
  summary?: string | null
  decisions: DecisionLight[]
  created_at?: string | null
}

export type PatchSnapshot = {
  source_type: string
  source_id: string
  source_label: string
  base_commit_sha?: string | null
  head_commit_sha?: string | null
  changed_files_count: number
  insertions: number
  deletions: number
}

export type WorkbenchDelta = {
  id: string
  workspace_id: string
  task_id: string
  status: string
  change_category?: string | null
  change_reason?: string | null
  promote_candidate: boolean
  ai_patch?: PatchSnapshot | null
  human_patch?: PatchSnapshot | null
  file_diffs: HumanDeltaFileDiff[]
  delta_regions: DeltaRegion[]
  changed_files_count?: number | null
  insertions?: number | null
  deletions?: number | null
  comparison_summary?: string | null
  decision_count: number
  decisions: DecisionLight[]
  created_at?: string | null
  updated_at?: string | null
}

export type Evidence = {
  id: string
  workspace_id: string
  requirement_id?: string | null
  task_id?: string | null
  ai_job_id?: string | null
  human_review_id?: string | null
  status: string
  evidence_type: string
  source: ExternalEvidenceRef
  title?: string | null
  summary?: string | null
  confirmed_by_id?: string | null
  confirmed_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export type Decision = {
  id: string
  workspace_id: string
  task_id: string
  requirement_id?: string | null
  human_delta_id?: string | null
  delta_region_id?: string | null
  status: string
  title: string
  body?: string | null
  rationale?: string | null
  impact_scope?: string | null
  source_evidence_id?: string | null
  source_type: DecisionSourceType
  source_chat_message_id?: string | null
  source_asset_id?: string | null
  source_asset_version_id?: string | null
  source_asset_thread_id?: string | null
  source_resolution_proposal_id?: string | null
  source_final_summary_id?: string | null
  source_metadata?: Record<string, unknown> | null
  delta_line_refs?: DeltaLineRef[] | null
  source?: DecisionSource | null
  decided_by_id?: string | null
  promote_candidate: boolean
  created_at?: string | null
  updated_at?: string | null
}

export type DecisionSource = {
  source_type: DecisionSourceType
  label: string
  chat_message_id?: string | null
  asset_id?: string | null
  asset_version_id?: string | null
  asset_thread_id?: string | null
  resolution_proposal_id?: string | null
  final_summary_id?: string | null
  metadata?: Record<string, unknown> | null
}

export type Clarification = {
  id: string
  workspace_id: string
  task_id: string
  requirement_id?: string | null
  status: string
  blocking_level: string
  question: string
  answer?: string | null
  requester_id?: string | null
  responder_id?: string | null
  source_evidence_id?: string | null
  source_review_id?: string | null
  clarification_type?: string | null
  target_ref?: Record<string, unknown> | null
  urgency?: string | null
  answered_at?: string | null
  accepted_at?: string | null
  promote_candidate: boolean
  converted_requirement_id?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export type KnowledgeAsset = {
  id: string
  workspace_id: string
  asset_type: string
  status: string
  title: string
  body?: string | null
  source_task_id?: string | null
  source_decision_id?: string | null
  source_human_delta_id?: string | null
  source_clarification_id?: string | null
  source_review_id?: string | null
  source_evidence_id?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export type TaskSummary = {
  id: string
  workspace_id: string
  creator_id?: string | null
  creator_display_name?: string | null
  name: string
  description?: string | null
  status: string
  current_phase?: string | null
  requirement_count: number
  spec_count: number
  plan_count: number
  ai_run_count: number
  human_review_count: number
  human_delta_count: number
  evidence_count: number
  decision_count: number
  clarification_count: number
  coverage_status: CoverageStatus
  baseline_version?: number
  baselined_at?: string | null
  baselined_by_id?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export type TaskProcessSummary = {
  spec_status: string
  plan_status: string
  ai_run_status: string
  human_review_status: string
  human_delta_status: string
  evidence_status: string
  coverage_status: CoverageStatus
  risk_status: string
}

export type TaskFileItem = {
  id: string
  file_type: string
  title: string
  status: string
  source_kind: string
  source_id?: string | null
  source_version_id?: string | null
  source_path?: string | null
  summary?: string | null
  metadata?: Record<string, unknown> | null
  created_at?: string | null
  updated_at?: string | null
}

export type TaskFinalSummary = {
  id: string
  workspace_id: string
  task_id: string
  author_id?: string | null
  final_status: string
  summary?: string | null
  remaining_risk?: string | null
  next_steps?: string | null
  final_evidence_ids: string[]
  review_checklist?: Record<string, unknown> | null
  clarification_summary?: Record<string, unknown> | null
  delta_summary?: Record<string, unknown> | null
  decision_summary?: Record<string, unknown> | null
  human_confirmation_review_id?: string | null
  verified_at?: string | null
  verified_by_id?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export type TaskProcessAuditLog = {
  id: string
  workspace_id: string
  task_id: string
  actor_id?: string | null
  record_type: string
  record_id: string
  action: string
  before?: Record<string, unknown> | null
  after?: Record<string, unknown> | null
  reason?: string | null
  created_at?: string | null
}

export type TaskDetail = {
  task: TaskSummary
  requirement_links: TaskRequirementLink[]
  task_files: TaskFileItem[]
  specs: TaskAssetSummary[]
  plans: TaskAssetSummary[]
  plan_nodes: PlanNodeAssetSummary[]
  ai_runs: AiRunSummary[]
  ai_outputs: AiOutput[]
  human_reviews: HumanReview[]
  human_deltas: HumanDelta[]
  evidence: Evidence[]
  decisions: Decision[]
  clarifications: Clarification[]
  final_summary?: TaskFinalSummary | null
  process_audit_logs: TaskProcessAuditLog[]
  process_summary: TaskProcessSummary
  connection_status: WorkspaceAssetConnectionStatus[]
}

export type HumanReviewMutationPayload = {
  outcome?: string | null
  status?: string | null
  review_type?: string | null
  review_scope?: string | null
  priority?: string | null
  title?: string | null
  body?: string | null
  source_ref?: Record<string, unknown> | null
  target_ref?: Record<string, unknown> | null
  due_date?: string | null
  change_reason?: string | null
}

export type HumanReviewCommentPayload = {
  comment_type?: string | null
  body: string
  required_change?: Record<string, unknown> | null
  change_reason?: string | null
}

export type HumanDeltaMutationPayload = {
  proposal_id?: string | null
  final_evidence_id?: string | null
  change_category?: string | null
  change_reason?: string | null
  promote_candidate?: boolean
  audit_reason?: string | null
}

export type EvidenceMutationPayload = {
  requirement_id?: string | null
  ai_job_id?: string | null
  human_review_id?: string | null
  status?: string | null
  evidence_type?: string | null
  source_type?: string | null
  source_uri?: string | null
  source_label?: string | null
  source_ref?: string | null
  source_path?: string | null
  source_metadata?: Record<string, unknown> | null
  title?: string | null
  summary?: string | null
  confirmed?: boolean | null
  change_reason?: string | null
}

export type DecisionMutationPayload = {
  requirement_id?: string | null
  human_delta_id?: string | null
  status?: string | null
  title?: string | null
  body?: string | null
  rationale?: string | null
  impact_scope?: string | null
  source_evidence_id?: string | null
  source_type?: DecisionSourceType | null
  source_chat_message_id?: string | null
  source_asset_id?: string | null
  source_asset_version_id?: string | null
  source_asset_thread_id?: string | null
  source_resolution_proposal_id?: string | null
  source_final_summary_id?: string | null
  source_metadata?: Record<string, unknown> | null
  delta_line_refs?: DeltaLineRef[] | null
  promote_candidate?: boolean
  change_reason?: string | null
}

export type ClarificationMutationPayload = {
  requirement_id?: string | null
  status?: string | null
  blocking_level?: string | null
  question?: string | null
  answer?: string | null
  source_evidence_id?: string | null
  source_review_id?: string | null
  clarification_type?: string | null
  target_ref?: Record<string, unknown> | null
  urgency?: string | null
  promote_candidate?: boolean
  converted_requirement_id?: string | null
  change_reason?: string | null
}

export type TaskFinalSummaryPayload = {
  final_status?: string | null
  summary?: string | null
  remaining_risk?: string | null
  next_steps?: string | null
  final_evidence_ids?: string[]
  review_checklist?: Record<string, unknown> | null
  clarification_summary?: Record<string, unknown> | null
  delta_summary?: Record<string, unknown> | null
  decision_summary?: Record<string, unknown> | null
  human_confirmation_review_id?: string | null
  change_reason?: string | null
}

export type WorkspaceAssetsOverview = {
  workspace_id: string
  requirement_count: number
  task_count: number
  ai_run_count: number
  evidence_count: number
  knowledge_asset_count: number
  coverage_status: CoverageStatus
  connection_status: WorkspaceAssetConnectionStatus[]
}

export type WorkspaceAssetsRequirements = {
  workspace_id: string
  items: RequirementSummary[]
  total: number
  page: number
  page_size: number
  scope?: 'tree' | 'flat' | 'children'
  state: WorkspaceAssetListState
  connection_status: WorkspaceAssetConnectionStatus[]
}

export type TaskListSummaryStats = {
  review_pending_count: number
  evidence_missing_count: number
  human_delta_count: number
  clarification_pending_count: number
}

export type WorkspaceAssetsTasks = {
  workspace_id: string
  items: TaskSummary[]
  total: number
  page: number
  page_size: number
  stats: TaskListSummaryStats
  state: WorkspaceAssetListState
  connection_status: WorkspaceAssetConnectionStatus[]
}

export type TraceabilityViewKey =
  | 'spec_coverage_matrix'
  | 'evidence_registry'
  | 'human_delta_dashboard'
  | 'risk_board'

export type SpecCoverageMatrixTraceRefs = {
  spec_ids: string[]
  plan_ids: string[]
  ai_run_ids: string[]
  human_review_ids: string[]
  human_delta_ids: string[]
  evidence_ids: string[]
  decision_ids: string[]
  clarification_ids: string[]
}

export type SpecCoverageMatrixRow = {
  id: string
  requirement_id: string
  requirement_title: string
  task_id?: string | null
  task_name?: string | null
  relation_type?: string | null
  spec_status: string
  plan_status: string
  ai_run_status: string
  human_review_status: string
  human_delta_status: string
  evidence_status: string
  coverage_status: SpecCoverageMatrixCoverageStatus
  coverage_reason: string
  trace_refs: SpecCoverageMatrixTraceRefs
}

export type TraceabilityViewItem = SpecCoverageMatrixRow | Record<string, unknown>

export type TraceabilityView = {
  key: TraceabilityViewKey
  title: string
  view_type: string
  items: TraceabilityViewItem[]
  total: number
  state: WorkspaceAssetListState
}

export type WorkspaceAssetsTraceability = {
  workspace_id: string
  views: TraceabilityView[]
  connection_status: WorkspaceAssetConnectionStatus[]
}

export type WorkspaceAssetsKnowledge = {
  workspace_id: string
  items: KnowledgeAsset[]
  total: number
  state: WorkspaceAssetListState
  connection_status: WorkspaceAssetConnectionStatus[]
}

// ---------------------------------------------------------------------------
// Task Detail lightweight / sectioned types
// ---------------------------------------------------------------------------

export type TaskDetailSummaryResponse = {
  task: TaskSummary
  requirement_links: TaskRequirementLink[]
  process_summary: TaskProcessSummary
  connection_status: WorkspaceAssetConnectionStatus[]
  human_reviews?: HumanReview[]
  evidence?: Evidence[]
  final_summary?: TaskFinalSummary | null
}

export type TaskFileItemLight = Omit<TaskFileItem, 'metadata'>

export type TaskFilesSectionResponse = {
  items: TaskFileItemLight[]
  total: number
  page: number
  page_size: number
}

export type HumanReviewLight = Omit<HumanReview, 'source_ref' | 'comments'> & {
  comment_count: number
}

export type TaskHumanReviewsSectionResponse = {
  items: HumanReviewLight[]
  total: number
  page: number
  page_size: number
}

export type HumanDeltaLight = Omit<HumanDelta, 'diff_text' | 'file_diffs'>

export type TaskHumanDeltasSectionResponse = {
  items: HumanDeltaLight[]
  total: number
  page: number
  page_size: number
}

export type HumanDeltaSuggestionsResponse = {
  items: HumanDeltaSuggestion[]
}

export type EvidenceLight = Omit<Evidence, 'source'> & {
  source_type: string
  source_uri?: string | null
  source_label?: string | null
  source_ref?: string | null
  source_path?: string | null
}

export type TaskEvidenceSectionResponse = {
  items: EvidenceLight[]
  total: number
  page: number
  page_size: number
}

export type DecisionLight = Omit<Decision, 'body' | 'rationale' | 'source_metadata' | 'source_chat_message_id' | 'source_asset_id' | 'source_asset_version_id' | 'source_asset_thread_id' | 'source_resolution_proposal_id' | 'source_final_summary_id'>

export type TaskDecisionsSectionResponse = {
  items: DecisionLight[]
  total: number
  page: number
  page_size: number
}

export type ClarificationLight = Omit<Clarification, 'answer'>

export type TaskClarificationsSectionResponse = {
  items: ClarificationLight[]
  total: number
  page: number
  page_size: number
}

export type TaskProcessAuditLogLight = Omit<TaskProcessAuditLog, 'before' | 'after'>

export type TaskProcessAuditSectionResponse = {
  items: TaskProcessAuditLogLight[]
  total: number
  page: number
  page_size: number
}

export type TaskFileDiffResponse = {
  file_id: string
  diff_text: string
}

export type FinalWorkflowStepKey = 'expert_review' | 'clarification' | 'final_summary' | 'baseline'
export type FinalWorkflowStepStatus = 'blocked' | 'ready' | 'active' | 'complete'
export type BaselineCheckStatus = 'pass' | 'warning' | 'block'
export type ReviewDerivedStatus = 'CLEAR' | 'WAITING_ANSWER' | 'ANSWERED_REVIEWING' | 'CLOSED'
export type ReviewTargetType =
  | 'SPEC'
  | 'PLAN'
  | 'AI_CHANGE'
  | 'HUMAN_DELTA'
  | 'EVIDENCE'
  | 'DECISION'
  | 'TASK_FILE'
export type ClarificationMessageType =
  | 'QUESTION'
  | 'FOLLOW_UP'
  | 'ANSWER'
  | 'CONFIRM_RESOLUTION'
  | 'REOPEN'
  | 'SYSTEM'

export type FinalWorkflowAction = {
  key: string
  label: string
  enabled: boolean
  disabled_reason?: string | null
}

export type TaskFinalWorkflowStep = {
  key: FinalWorkflowStepKey
  title: string
  status: FinalWorkflowStepStatus
  detail?: string | null
  blocking_count: number
}

export type BaselineCheckItem = {
  key: string
  label: string
  status: BaselineCheckStatus
  detail?: string | null
  blocking: boolean
}

export type ClarificationThread = {
  id: string
  workspace_id: string
  task_id: string
  clarification_id: string
  author_id?: string | null
  entry_type: string
  body: string
  is_answer: boolean
  created_at?: string | null
}

export type ReviewTargetRef = {
  target_type: ReviewTargetType
  target_id: string
  label?: string | null
  source_ref?: Record<string, unknown> | null
}

export type ReviewTarget = ReviewTargetRef & {
  label: string
  status?: string | null
  subtitle?: string | null
}

export type ReviewTargetPreviewBlockKind =
  | 'text'
  | 'markdown'
  | 'metadata'
  | 'list'
  | 'diff'
  | 'file_diffs'
  | 'json'

export type ReviewTargetPreviewMetadata = {
  key: string
  label: string
  value?: string | null
}

export type ReviewTargetPreviewBlock = {
  key: string
  title: string
  kind: ReviewTargetPreviewBlockKind
  content?: string | null
  items: Array<Record<string, unknown>>
  file_diffs: HumanDeltaFileDiff[]
  delta_regions?: DeltaRegion[]
  diff_text?: string | null
}

export type ReviewTargetPreviewResponse = {
  target: ReviewTarget
  title: string
  status?: string | null
  subtitle?: string | null
  source_ref?: Record<string, unknown> | null
  metadata: ReviewTargetPreviewMetadata[]
  blocks: ReviewTargetPreviewBlock[]
}

export type TaskBaseline = {
  id: string
  workspace_id: string
  task_id: string
  summary_id?: string | null
  version: number
  snapshot?: Record<string, unknown> | null
  baselined_by_id?: string | null
  is_rollback: boolean
  rollback_from_version?: number | null
  created_at?: string | null
}

export type TaskFinalWorkflowResponse = {
  task: TaskSummary
  steps: TaskFinalWorkflowStep[]
  reviews: HumanReview[]
  review_targets: Record<ReviewTargetType, ReviewTarget[]>
  clarifications: Clarification[]
  clarification_threads: Record<string, ClarificationThread[]>
  final_summary?: TaskFinalSummary | null
  baseline?: TaskBaseline | null
  checklist: BaselineCheckItem[]
  available_actions: FinalWorkflowAction[]
  readonly: boolean
  can_write_final_workflow: boolean
  can_resolve_clarification: boolean
}

export type FinalWorkflowReviewPayload = {
  title: string
  body?: string | null
  priority?: string | null
  target_refs: ReviewTargetRef[]
  change_reason?: string | null
}

export type FinalWorkflowClarificationPayload = {
  requirement_id?: string | null
  source_review_id?: string | null
  source_evidence_id?: string | null
  blocking_level?: string
  clarification_type?: string | null
  target_ref?: Record<string, unknown> | null
  urgency?: string | null
  question: string
  change_reason?: string | null
}

export type ClarificationMessagePayload = {
  body: string
  entry_type: ClarificationMessageType
  change_reason?: string | null
}

export type TaskWorkbenchSectionKey =
  | 'taskFile'
  | 'finalWorkflow'
  | 'humanDelta'
  | 'evidence'
  | 'decisions'
  | 'processAudit'
