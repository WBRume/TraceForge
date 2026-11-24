import type { ChatMessageFields } from '@/composables/chat/shared/messageIdentity'

export interface SessionPreview {
  messages: ChatMessageFields[]
  scrollTop: number
}

export interface TaskFloatSession {
  workspaceName: string
  taskName: string
  tone: string
  preview?: SessionPreview
}

export type TaskFloatMessage =
  | { type: 'ready' }
  | { type: 'prepared' }
  | { type: 'session'; session: TaskFloatSession; output: string }
  | { type: 'output'; text: string }
  | { type: 'refresh' }

export function taskFloatChannel(id: string): BroadcastChannel {
  return new BroadcastChannel(`traceforge:task-float:${id}`)
}
