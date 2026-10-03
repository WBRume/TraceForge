export type RuntimeState = 'AI_RUNNING' | 'AI_HITL_SUSPENDED' | 'AI_RUN_FINISHED' | 'AI_RUN_ERROR' | 'AI_RUN_INTERRUPTED' | 'AI_RUN_STOPPED'

export interface TaskRuntimeEvent {
  event_id?: string
  event_type: RuntimeState
  occurred_at?: string
  workspace: { id: string; name: string }
  task: { id: string; title: string; url: string }
  initiator: { id: string; name: string }
  summary: string
  run: { id: string; version: number; started_at: string; finished_at?: string | null; client_message_id?: string | null; session_generation?: number }
}

export interface WebhookRequest {
  url: string
  body: Record<string, unknown>
  event_id: string
}
