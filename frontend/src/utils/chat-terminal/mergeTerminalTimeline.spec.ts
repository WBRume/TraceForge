import { describe, expect, it } from 'vitest'
import { mergeTerminalTimeline } from './mergeTerminalTimeline'

describe('mergeTerminalTimeline', () => {
  it('keeps both rounds and their tool events visible with one divider per turn', () => {
    const time = (seconds: number) => new Date(Date.UTC(2026, 0, 1, 0, 0, seconds)).toISOString()
    const entries = mergeTerminalTimeline({
      messages: [
        { id: 'second', role: 'user', session_turn_id: 'turn-2', metadata: { session_turn_index: 2 }, created_at: time(4) },
        { id: 'first', role: 'user', session_turn_id: 'turn-1', metadata: { session_turn_index: 1 }, created_at: time(0) },
        { id: 'reply', role: 'assistant', session_turn_id: 'turn-1', created_at: time(3) },
      ],
      terminalLogs: [
        { id: 'call', type: 'tool_use', created_at: time(1) },
        { id: 'result', type: 'tool_result', created_at: time(2) },
      ],
      localEchoes: [], statusCards: [], hitlCards: [], resultHistory: [],
    })

    expect(entries.map(entry => entry.kind)).toEqual([
      'turn_separator', 'message', 'tool_use', 'tool_result', 'message', 'turn_separator', 'message',
    ])
    expect(entries.filter(entry => entry.kind === 'turn_separator').map(entry => entry.turnIndex)).toEqual([1, 2])
  })
})
