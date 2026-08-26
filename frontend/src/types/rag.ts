export type RagQueueStatus = 'RUNNING' | 'CONSUMED'

export type RagCaseStatus = 'QUEUED' | 'EXPORTED'

export type RagSyncQueueItem = {
  id: string
  name: string
  workspace_id?: string | null
  status: string
  case_count: number
  exported_count: number
  created_at?: string | null
  consumed_at?: string | null
  updated_at?: string | null
}

export type RagQueuePageResponse = {
  items: RagSyncQueueItem[]
  total: number
  page: number
  page_size: number
}

export type RagQueueCaseItem = {
  id: string
  doc_key: string
  case_id?: string | null
  workspace_id?: string | null
  title?: string | null
  version?: number | null
  status: string
  exported_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export type RagQueueCasePageResponse = {
  items: RagQueueCaseItem[]
  total: number
  page: number
  page_size: number
}