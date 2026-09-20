export type Retrieval = 'hybrid' | 'lexical'
export interface SearchCapabilities {
  enabled: boolean
  ready: boolean
  hybrid_available: boolean
  hybrid_unavailable_reason?: string | null
}
export interface SearchItem {
  entity_key: string
  kind: 'task' | 'message'
  workspace_name: string
  task_name: string
  message_id?: string
  role?: string
  creator_id?: string | null
  creator_display_name?: string | null
  creator_avatar_url?: string | null
  creator_avatar_svg?: string | null
  created_at: string
  snippet_basis: 'keyword' | 'semantic' | 'plain'
  snippet: { text: string; match: boolean }[]
  target: { route_name: string; params: Record<string, string>; query: Record<string, string> }
}
export interface SearchResponse {
  items: SearchItem[]
  has_more: boolean
  next_cursor: string | null
  session_cursor: string
  executed_retrieval: Retrieval
  degraded_reason: string | null
  indexing_state: string
  semantic_indexing_state: string
  result_window_exhausted: boolean
}
export interface MessageContext {
  anchor_message_id: string | null
  messages: Record<string, any>[]
  before_cursor: string | null
  after_cursor: string | null
  has_before: boolean
  has_after: boolean
  at_latest: boolean
}
