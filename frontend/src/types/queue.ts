export type QueueSource = 'provision' | 'api_mock' | 'bootstrap' | 'skill_analysis'
export type QueueStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED'
export type QueueView = 'mine' | 'workspace_all'

export type QueueJobActions = {
  can_stop: boolean
  can_retry: boolean
  can_open: boolean
}

export type QueueJobItem = {
  source: QueueSource
  job_id: string
  job_type: string
  status: QueueStatus
  progress: number
  stage?: string | null
  message?: string | null
  error_message?: string | null
  workspace_id?: string | null
  task_id?: string | null
  creator_id: string
  created_at: string
  updated_at?: string | null
  target_path?: string | null
  actions: QueueJobActions
}

export type QueueJobListResponse = {
  items: QueueJobItem[]
  total: number
  page: number
  page_size: number
}

export type QueueJobActionResponse = {
  ok: boolean
  action: 'stop' | 'retry'
  source: QueueSource
  job_id: string
  message?: string
  new_job_id?: string | null
}
