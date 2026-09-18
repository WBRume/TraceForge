/**
 * Chat 领域跨模块共享类型。
 * 仅放被多个子域使用的类型；单一模块内部的类型留在各自模块中。
 */

export type ChatAiJobStatus = 'PENDING' | 'RUNNING' | 'WAITING_HITL' | 'INTERRUPTED' | 'SUCCESS' | 'FAILED' | 'CANCELLED' | 'REVERTED'

export type ChatAiJob = {
  id: string
  task_id?: string | null
  status: ChatAiJobStatus
  progress: number
  message?: string | null
  error_message?: string | null
  context_json?: Record<string, any> | null
  session_id?: string | null
  started_at?: string | null
  created_at?: string | null
}

export type SpecBootstrapStatus = 'PENDING' | 'RUNNING' | 'READY' | 'FAILED' | 'STALE'

export type TaskSpecBootstrap = {
  task_id: string
  workspace_id: string
  spec_asset_id?: string | null
  spec_version_id?: string | null
  status: SpecBootstrapStatus
  progress: number
  message?: string | null
  baseline_session_id?: string | null
  error_message?: string | null
  updated_at?: string | null
}

export type SpecDrawerLevel = 0 | 1 | 2 | 3
export type OpenSpecDrawerLevel = 1 | 2 | 3
export type SpecDrawerTab = 'spec_doc' | 'superpowers_docs' | 'diag_docs' | 'diag_code'

export type TaskSessionFilter = 'ALL' | 'DONE' | 'FAILED'
export type TaskRelationFilter = 'created_by_me' | 'mentioned_me' | 'messaged_by_me' | 'followed_by_me'
export type TaskTypeFilterValue = 'ALL' | 'DEVELOPMENT' | 'DIAGNOSIS'

export type RuntimeSkillUsage = {
  is_used: boolean
  used_count: number
  last_used_at?: string | null
  usage_scope_start_at?: string | null
}

export type RuntimeSkillItem = {
  skill_id: string
  name: string
  description?: string | null
  dimension: 'GLOBAL' | 'WORKSPACE' | string
  publish_state?: 'PUBLISHED' | 'DRAFT' | string
  has_pending_changes?: boolean
  changed_files_count?: number
  materialized_dir?: string | null
  is_materialized?: boolean
  config_deleted?: boolean
  usage?: RuntimeSkillUsage
}

export type RuntimeSkillFileNode = {
  path: string
  name: string
  node_type: 'file' | 'directory'
  size?: number | null
  children?: RuntimeSkillFileNode[]
}

/** 置顶卡片：HITL 交互卡与引擎状态卡。 */
export type HitlCard = {
  id: string
  type: 'hitl'
  interaction_id: string
  message_id: string
  hitl_type: string
  prompt: string
  options: any[]
  context: string
  job_id: string
  answered: boolean
  answer: string
  tempInput: string
  created_at: string
}

export type ChatStatusCard = {
  id: string
  type: 'status'
  status?: string | null
  message?: string | null
  model?: string | null
  created_at?: string | null
}

export type PinnedCard = HitlCard | ChatStatusCard

export type ResultSummaryStep = {
  id: string
  duration_ms: number
  cost_usd: number
  success: boolean
  result: any
  created_at: string
  timestamp: string
}

export type ResultsSummaryState = {
  visible: boolean
  totalDurationMs: number
  totalCostUsd: number
  history: ResultSummaryStep[]
  expanded: boolean
}

export type PreInputEditPermission = 'ALL' | 'MENTIONED' | 'EXPERTS' | 'NONE'

export type PreInputMember = {
  user_id: string
  display_name: string | null
  avatar_url: string | null
  avatar_svg: string | null
  is_expert: boolean
  done?: boolean
}

export type PreInputDocumentSegment = {
  text: string
  created_by: string
  created_by_name: string | null
  updated_by: string
  updated_by_name: string | null
  modified: boolean
}

export type ActivePreInput = {
  id: string
  task_id: string
  workspace_id: string
  creator: PreInputMember
  main_text: string
  document_segments: PreInputDocumentSegment[]
  edit_permission: PreInputEditPermission
  status: 'COLLECTING' | 'SUBMITTED' | 'CANCELLED'
  wait_seconds: number
  deadline_at: string | null
  created_at: string | null
  mentioned_user_ids: string[]
  mentionees: PreInputMember[]
  volunteers: PreInputMember[]
  participant_ids: string[]
  all_participated: boolean
}
