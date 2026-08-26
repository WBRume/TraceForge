export type ContextTokenCategory =
  | 'TASK_PROMPT'
  | 'SPEC_DOCS'
  | 'RUNTIME_SKILLS'
  | 'SUPERPOWERS_RULES'
  | 'TOOL_INPUT'
  | 'TOOL_RESULT'
  | 'THINKING'
  | 'HISTORY'
  | 'HITL'

export type ContextTokenSnapshot = {
  id: string
  workspace_id: string
  task_id: string
  ai_job_id?: string | null
  session_id?: string | null
  model?: string | null
  agent_backend?: string | null
  status: string
  total_cost_usd?: number | null
  duration_ms?: number | null
  created_at?: string | null
  updated_at?: string | null
}

export type ContextProviderTokens = {
  available: boolean
  status: 'available' | 'unavailable' | string
  input_tokens?: number | null
  output_tokens?: number | null
  cache_read_tokens?: number | null
  cache_creation_tokens?: number | null
  thinking_tokens?: number | null
  tool_io_tokens?: number | null
  total_tokens?: number | null
}

export type ContextTokenCategorySummary = {
  category: ContextTokenCategory | string
  segment_count: number
  provider_tokens?: number | null
  attribution_units: number
  char_count: number
  byte_count: number
  percentage: number
}

export type ContextTokenSegment = {
  id: string
  snapshot_id: string
  category: ContextTokenCategory | string
  provider_tokens?: number | null
  attribution_units: number
  char_count: number
  byte_count: number
  source_kind: string
  source_ref_id?: string | null
  chat_message_id?: string | null
  asset_id?: string | null
  asset_version_id?: string | null
  skill_runtime_event_id?: string | null
  tool_use_id?: string | null
  content_hash?: string | null
  locator_json?: Record<string, unknown> | null
  title?: string | null
  preview?: string | null
  metadata_json?: Record<string, unknown> | null
  created_at?: string | null
}

export type ContextCompactionReference = {
  turn_index?: number | null
  ai_job_id?: string | null
  chat_message_id?: string | null
  log_id?: string | null
  label?: string | null
}

export type ContextCompactionRiskRef = {
  id: string
  category: string
  source_kind: string
  source_ref_id?: string | null
  chat_message_id?: string | null
  asset_id?: string | null
  skill_runtime_event_id?: string | null
  tool_use_id?: string | null
  title?: string | null
}

export type ContextCompactionRisk = {
  kind: string
  label: string
  level: 'low' | 'medium' | 'high' | 'unknown' | string
  reason?: string | null
  affected_segments: number
  sample_refs: ContextCompactionRiskRef[]
  estimated: boolean
}

export type ContextCompactionEvent = {
  id: string
  phase_before: number
  phase_after: number
  detected_at?: string | null
  source: string
  source_ref_id?: string | null
  source_label?: string | null
  event_type: string
  token_before_estimate?: number | null
  token_after_estimate?: number | null
  token_reduction_estimate?: number | null
  tokens_estimated: boolean
  preview?: string | null
  trigger?: ContextCompactionReference | null
  risks: ContextCompactionRisk[]
  locator: Record<string, unknown>
}

export type ContextCompactionPhase = {
  phase_index: number
  started_at?: string | null
  ended_at?: string | null
  token_before_estimate?: number | null
  token_after_estimate?: number | null
  phase_new_tokens_estimate?: number | null
  trigger?: ContextCompactionReference | null
  compaction_event_id?: string | null
  estimation_note?: string | null
}

export type ContextCompactionDataSource = {
  source: string
  status: string
  event_count: number
  note?: string | null
}

export type ContextCompactionResponse = {
  task_id: string
  workspace_id: string
  status: 'detected' | 'not_detected' | string
  has_detected_events: boolean
  empty_reason?: string | null
  events: ContextCompactionEvent[]
  phases: ContextCompactionPhase[]
  data_sources: ContextCompactionDataSource[]
  generated_at?: string | null
  parser_version: string
}

export type ContextCompactionLocatePayload = {
  source: string
  source_ref_id?: string | null
  ai_job_id?: string | null
  chat_message_id?: string | null
  log_id?: string | null
}

export type ContextWindowResponse = {
  task_id: string
  workspace_id: string
  snapshot?: ContextTokenSnapshot | null
  provider_tokens: ContextProviderTokens
  categories: ContextTokenCategorySummary[]
  segments: ContextTokenSegment[]
  segments_total: number
  segments_page: number
  segments_page_size: number
  selected_category?: string | null
  empty_reason?: string | null
  compaction?: ContextCompactionResponse | null
}
