import { ref } from 'vue'
import { parseContract } from '../../../../shared/contracts/validate'
import type { TerminalRecord } from '../../../../shared/contracts/generated/terminalRecord'
import type { ApplicationMessage } from '../../../../shared/contracts/generated/applicationMessage'

export type TerminalLogEntry = {
  id: string | null
  type: 'tool_use' | 'tool_result' | 'log'
  tool_name?: string
  tool_input?: unknown
  tool_use_id?: string
  output?: string
  is_error?: boolean
  structured_content?: unknown
  content_blocks?: unknown[]
  content?: string
  created_at: string
  timestamp: string
}

const toTimestamp = (createdAt: string) => new Date(createdAt).toLocaleTimeString()

/**
 * 终端日志面板存储：tool_use / tool_result / 原始 log 三类条目。
 * WS 增量与历史快照共用同一形状（历史条目 content 为 JSON 序列化的工具事件）。
 */
export function useTerminalLogs() {
  const logs = ref<TerminalLogEntry[]>([])

  const appendToolUse = (payload: any) => {
    const createdAt = new Date().toISOString()
    logs.value.push({
      id: payload.id || null,
      type: 'tool_use',
      tool_name: payload.tool_name,
      tool_input: payload.tool_input,
      tool_use_id: payload.tool_use_id,
      created_at: createdAt,
      timestamp: toTimestamp(createdAt),
    })
  }

  const appendToolResult = (payload: any) => {
    const createdAt = new Date().toISOString()
    logs.value.push({
      id: payload.id || null,
      type: 'tool_result',
      tool_use_id: payload.tool_use_id,
      output: payload.output,
      is_error: payload.is_error,
      structured_content: payload.structured_content,
      content_blocks: payload.content,
      created_at: createdAt,
      timestamp: toTimestamp(createdAt),
    })
  }

  const appendLog = (payload: any) => {
    const createdAt = new Date().toISOString()
    logs.value.push({
      id: payload.id || null,
      type: 'log',
      content: payload.content,
      created_at: createdAt,
      timestamp: toTimestamp(createdAt),
    })
  }

  const clear = () => {
    logs.value = []
  }

  const restoreFromHistory = (hLogs: { id: string; type: string; content: string; created_at: string }[]) => {
    logs.value = hLogs.flatMap<TerminalLogEntry>((row) => {
      const base = { id: row.id, created_at: row.created_at, timestamp: toTimestamp(row.created_at) }
      if (['STDERR', 'STATUS', 'HITL_REQUEST', 'HITL_RESPONSE', 'AGENT_STATE'].includes(row.type)) {
        return [{ ...base, type: 'log', content: row.content }]
      }
      if (row.type !== 'STDOUT') return []
      try {
        const record = parseContract<TerminalRecord>('terminalRecord', JSON.parse(row.content))
        const event = parseContract<ApplicationMessage>('applicationMessage', {
          contract_version: record.contract_version, event_type: record.event_type, payload: record.payload,
        })
        if (event.event_type === 'tool_use') {
          const parsed = event.payload
          return [{
            ...base,
            type: 'tool_use',
            tool_name: parsed.tool_name,
            tool_input: parsed.tool_input,
            tool_use_id: parsed.tool_use_id,
          }]
        }
        if (event.event_type === 'tool_result') {
          const parsed = event.payload
          return [{
            ...base,
            type: 'tool_result',
            tool_use_id: parsed.tool_use_id,
            output: parsed.output,
            is_error: parsed.is_error,
            structured_content: parsed.structured_content,
            content_blocks: parsed.content,
          }]
        }
      } catch {
        return []
      }
      return []
    })
  }

  return {
    logs,
    appendToolUse,
    appendToolResult,
    appendLog,
    clear,
    restoreFromHistory,
  }
}
