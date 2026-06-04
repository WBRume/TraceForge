import type {
  TerminalLocalEcho,
  TerminalTimelineEntry,
} from './timeline-types'

interface MergeTerminalTimelineInput {
  messages: any[]
  terminalLogs: any[]
  localEchoes: TerminalLocalEcho[]
  statusCards: any[]
  hitlCards: any[]
  resultHistory: any[]
}

const isToolEchoLog = (content: string): boolean => {
  const normalized = content.trim().toLowerCase()
  return normalized.startsWith('[tool]') || normalized.startsWith('[tool result]') || normalized.startsWith('[tool_result]')
}

const coerceTime = (value: unknown, fallbackMs: number): { createdAt: string; createdMs: number } => {
  const raw = String(value || '').trim()
  const parsed = raw ? Date.parse(raw) : Number.NaN
  const createdMs = Number.isFinite(parsed) ? parsed : fallbackMs
  return {
    createdAt: new Date(createdMs).toISOString(),
    createdMs,
  }
}

export const mergeTerminalTimeline = (input: MergeTerminalTimelineInput): TerminalTimelineEntry[] => {
  const entries: Array<TerminalTimelineEntry & { seq: number }> = []
  let seq = 0
  const hasStructuredToolEntries = input.terminalLogs.some((item) => item?.type === 'tool_use' || item?.type === 'tool_result')

  for (const [index, message] of input.messages.entries()) {
    const time = coerceTime(message?.created_at, Date.now() + index)
    entries.push({
      id: `msg-${message?.id || index}`,
      kind: 'message',
      role: String(message?.role || 'system'),
      content: String(message?.content || ''),
      messageType: String(message?.message_type || 'text'),
      createdAt: time.createdAt,
      createdMs: time.createdMs,
      seq: seq++,
    })
  }

  for (const [index, log] of input.terminalLogs.entries()) {
    const time = coerceTime(log?.created_at, Date.now() + 1000 + index)
    if (log?.type === 'tool_use') {
      entries.push({
        id: `tool-use-${log?.id || log?.tool_use_id || index}`,
        kind: 'tool_use',
        toolName: String(log?.tool_name || 'unknown'),
        toolInput: log?.tool_input,
        toolUseId: String(log?.tool_use_id || ''),
        sourceLogId: log?.id ? String(log.id) : null,
        createdAt: time.createdAt,
        createdMs: time.createdMs,
        seq: seq++,
      })
      continue
    }
    if (log?.type === 'tool_result') {
      entries.push({
        id: `tool-result-${log?.id || log?.tool_use_id || index}`,
        kind: 'tool_result',
        toolUseId: String(log?.tool_use_id || ''),
        output: String(log?.output || ''),
        isError: Boolean(log?.is_error),
        sourceLogId: log?.id ? String(log.id) : null,
        createdAt: time.createdAt,
        createdMs: time.createdMs,
        seq: seq++,
      })
      continue
    }
    const rawContent = String(log?.content || '')
    if (hasStructuredToolEntries && isToolEchoLog(rawContent)) {
      // Structured tool_use/tool_result cards already present.
      // Hide duplicated textual echo logs to keep timeline readable.
      continue
    }
    entries.push({
      id: `log-${log?.id || index}`,
      kind: 'log',
      content: rawContent,
      sourceLogId: log?.id ? String(log.id) : null,
      createdAt: time.createdAt,
      createdMs: time.createdMs,
      seq: seq++,
    })
  }

  for (const [index, card] of input.statusCards.entries()) {
    const time = coerceTime(card?.created_at, Date.now() + 2000 + index)
    entries.push({
      id: `status-${card?.id || index}`,
      kind: 'status',
      status: String(card?.status || ''),
      message: String(card?.message || ''),
      model: String(card?.model || ''),
      createdAt: time.createdAt,
      createdMs: time.createdMs,
      seq: seq++,
    })
  }

  for (const [index, card] of input.hitlCards.entries()) {
    const time = coerceTime(card?.created_at, Date.now() + 3000 + index)
    entries.push({
      id: `hitl-${card?.id || index}`,
      kind: 'hitl',
      cardId: String(card?.id || ''),
      jobId: String(card?.job_id || ''),
      hitlType: String(card?.hitl_type || 'text'),
      prompt: String(card?.prompt || ''),
      options: Array.isArray(card?.options) ? card.options.map((item: unknown) => String(item || '')) : [],
      context: String(card?.context || ''),
      answered: Boolean(card?.answered),
      createdAt: time.createdAt,
      createdMs: time.createdMs,
      seq: seq++,
    })
  }

  for (const [index, row] of input.resultHistory.entries()) {
    const time = coerceTime(row?.created_at, Date.now() + 4000 + index)
    entries.push({
      id: `result-${row?.id || index}`,
      kind: 'result',
      success: Boolean(row?.success),
      durationMs: Number(row?.duration_ms || 0),
      costUsd: Number(row?.cost_usd || 0),
      result: String(row?.result || ''),
      createdAt: time.createdAt,
      createdMs: time.createdMs,
      seq: seq++,
    })
  }

  for (const [index, echo] of input.localEchoes.entries()) {
    const time = coerceTime(echo?.createdAt, Date.now() + 5000 + index)
    entries.push({
      id: `local-${echo.id}`,
      kind: echo.kind,
      content: String(echo.content || ''),
      tone: echo.tone,
      createdAt: time.createdAt,
      createdMs: time.createdMs,
      seq: seq++,
    })
  }

  return entries
    .sort((a, b) => {
      if (a.createdMs !== b.createdMs) return a.createdMs - b.createdMs
      return a.seq - b.seq
    })
    .map(({ seq: _, ...rest }) => rest)
}
