import type { JobCompletion } from '../../shared/contracts/generated/jobCompletion'
import type { QueueJobActionResponse } from '../../shared/contracts/generated/queueJobActionResponse'
export type { QueueJobActionResponse }

export type QueueSource = 'provision' | 'api_mock' | 'bootstrap' | 'skill_analysis'
export type QueueStatus = 'PENDING' | 'RUNNING' | 'WAITING_HITL' | 'INTERRUPTED' | 'TERMINATING' | 'ORPHANED' | 'SUCCESS' | 'FAILED' | 'CANCELLED' | 'REVERTED'
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
  case_id?: string | null
  doc_key?: string | null
  version: number
  attempt_count?: number
  cancel_requested?: boolean
  result_available?: boolean
  completion?: JobCompletion | null
  retry_of_job_id?: string | null
  retry_count?: number | null
  actions: QueueJobActions
}

export type QueueJobListResponse = {
  items: QueueJobItem[]
  total: number
  page: number
  page_size: number
}
