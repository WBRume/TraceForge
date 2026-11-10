export type AssetSummary = {
  id: string
  task_id: string
  workspace_id: string
  asset_type: string
  name: string
  source_ext?: string | null
  source_mime?: string | null
  created_at: string
}

export type AssetVersion = {
  id: string
  asset_id: string
  version_no: number
  base_version_id?: string | null
  original_ext?: string | null
  original_mime?: string | null
  normalized_markdown?: string | null
  blocks_json?: any
  render_json?: any
  change_note?: string | null
  created_by: string
  created_at: string
}

export type AssetThreadMarker = {
  thread_id: string
  block_id: string
  selected_text?: string | null
  char_start?: number | null
  char_end?: number | null
  status: 'open' | 'resolved' | 'closed'
  creator_id: string
  created_at: string
  message_count: number
}

export type AssetThreadMessage = {
  id: string
  thread_id: string
  role: 'user' | 'ai' | 'system'
  content: string
  creator_id?: string | null
  creator_display_name?: string | null
  creator_avatar_svg?: string | null
  metadata_json?: any
  created_at: string
}

export type AssetResolutionProposal = {
  id: string
  thread_id: string
  base_version_id: string
  proposed_patch_json?: any
  diff_text?: string | null
  status: 'draft' | 'applied' | 'discarded'
  creator_id: string
  created_at: string
  updated_at?: string | null
}

export type ResolutionApplyPayload = {
  finalBlockAst?: any
  finalBlocksAst?: any[]
}

export type ResolutionDecisionPayload = {
  title: string
  body?: string | null
  impact_scope?: string | null
  requirement_id?: string | null
  promote_candidate?: boolean
}

export type AssetThread = {
  id: string
  asset_id: string
  version_id: string
  task_id: string
  workspace_id: string
  block_id: string
  selected_text?: string | null
  char_start?: number | null
  char_end?: number | null
  status: 'open' | 'resolved' | 'closed'
  creator_id: string
  creator_display_name?: string | null
  creator_avatar_svg?: string | null
  resolved_by?: string | null
  resolved_at?: string | null
  resolved_version_id?: string | null
  close_hint_state?: 'none' | 'pending' | 'no_close_needed'
  close_hint_reason?: string | null
  close_hint_version_id?: string | null
  anchor_status?: 'valid' | 'missing'
  effective_anchor?: {
    block_id?: string
    selected_text?: string | null
    char_start?: number | null
    char_end?: number | null
    source?: string
    block_text?: string
  } | null
  created_at: string
  updated_at?: string | null
  messages: AssetThreadMessage[]
  proposals: AssetResolutionProposal[]
}

export type AssetDocumentCapabilities = {
  can_view: boolean
  can_comment: boolean
  can_ai_reply: boolean
  can_apply_resolution: boolean
  can_manual_edit: boolean
  inline_review_enabled: boolean
  ai_available: boolean
  ai_unavailable_reason?: string | null
}

export type AssetDocumentPayload = {
  asset: AssetSummary
  active_version?: AssetVersion | null
  blocks: any[]
  thread_markers: AssetThreadMarker[]
  capabilities: AssetDocumentCapabilities
}

export type AssetAiJob = {
  id: string
  workspace_id: string
  task_id?: string | null
  asset_id?: string | null
  thread_id?: string | null
  channel: 'ASSET_THREAD' | 'TASK_CHAT'
  queue_key: string
  status: 'PENDING' | 'RUNNING' | 'WAITING_HITL' | 'SUCCESS' | 'FAILED' | 'CANCELLED'
  progress: number
  message?: string | null
  prompt_text?: string | null
  context_json?: Record<string, any> | null
  result_json?: Record<string, any> | null
  error_message?: string | null
  session_id?: string | null
  creator_id: string
  started_at?: string | null
  finished_at?: string | null
  created_at: string
  updated_at?: string | null
}

export type ThreadJobKind = 'THREAD_AI_REPLY' | 'RESOLUTION_PROPOSAL' | 'RESOLUTION_REWRITE'

