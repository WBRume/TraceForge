export type TerminalLocalEchoKind = 'command' | 'info' | 'success' | 'warning' | 'error'
export type TerminalCommandTone = 'query' | 'operate' | 'state' | 'danger' | 'local'

export interface TerminalLocalEcho {
  id: string
  kind: TerminalLocalEchoKind
  content: string
  createdAt: string
  tone?: TerminalCommandTone
}

type TerminalTimelineKind =
  | 'message'
  | 'tool_use'
  | 'tool_result'
  | 'log'
  | 'status'
  | 'hitl'
  | 'result'
  | TerminalLocalEchoKind

interface TerminalTimelineBase {
  id: string
  kind: TerminalTimelineKind
  createdAt: string
  createdMs: number
  sourceLogId?: string | null
}

export interface TerminalMessageEntry extends TerminalTimelineBase {
  kind: 'message'
  role: string
  content: string
  messageType: string
}

export interface TerminalToolUseEntry extends TerminalTimelineBase {
  kind: 'tool_use'
  toolName: string
  toolInput: unknown
  toolUseId: string
}

export interface TerminalToolResultEntry extends TerminalTimelineBase {
  kind: 'tool_result'
  toolUseId: string
  output: string
  isError: boolean
}

export interface TerminalLogEntry extends TerminalTimelineBase {
  kind: 'log'
  content: string
}

export interface TerminalStatusEntry extends TerminalTimelineBase {
  kind: 'status'
  status: string
  message: string
  model: string
}

export interface TerminalHitlEntry extends TerminalTimelineBase {
  kind: 'hitl'
  cardId: string
  jobId: string
  hitlType: string
  prompt: string
  options: string[]
  context: string
  answered: boolean
}

export interface TerminalResultEntry extends TerminalTimelineBase {
  kind: 'result'
  success: boolean
  durationMs: number
  costUsd: number
  result: string
}

export interface TerminalLocalEchoEntry extends TerminalTimelineBase {
  kind: TerminalLocalEchoKind
  content: string
  tone?: TerminalCommandTone
}

export type TerminalTimelineEntry =
  | TerminalMessageEntry
  | TerminalToolUseEntry
  | TerminalToolResultEntry
  | TerminalLogEntry
  | TerminalStatusEntry
  | TerminalHitlEntry
  | TerminalResultEntry
  | TerminalLocalEchoEntry
