import { describe, expect, it } from 'vitest'
import { useTerminalLogs } from '../message/useTerminalLogs'

describe('useTerminalLogs', () => {
  it('restores typed tool events and explicit runtime logs while discarding obsolete tool records', () => {
    const store = useTerminalLogs()
    store.restoreFromHistory([
      { id: 'l1', type: 'STDOUT', content: JSON.stringify({ contract_version: 2, event_type: 'tool_use', event_id: 'e1', payload: { task_id: 'task', tool_name: 'bash', tool_input: { cmd: 'ls' }, tool_use_id: 'tu1' } }), created_at: '2026-01-01T00:00:00Z' },
      { id: 'l2', type: 'STDOUT', content: JSON.stringify({ contract_version: 2, event_type: 'tool_result', event_id: 'e2', payload: { task_id: 'task', tool_use_id: 'tu1', output: 'ok', is_error: false } }), created_at: '2026-01-01T00:00:01Z' },
      { id: 'l3', type: 'STDERR', content: 'plain runtime line', created_at: '2026-01-01T00:00:02Z' },
      { id: 'legacy', type: 'STDOUT', content: '{"tool_use_id":"tu0","output":"legacy"}', created_at: '2026-01-01T00:00:03Z' },
    ])

    expect(store.logs.value.map(row => row.type)).toEqual(['tool_use', 'tool_result', 'log'])
    expect(store.logs.value[0]).toMatchObject({ tool_name: 'bash', tool_use_id: 'tu1' })
    expect(store.logs.value[1]).toMatchObject({ tool_use_id: 'tu1', output: 'ok', is_error: false })
    expect(store.logs.value[2]?.content).toBe('plain runtime line')
    expect(store.logs.value.every(row => row.timestamp.length > 0)).toBe(true)
  })

  it('appends WS increments with the same shapes', () => {
    const store = useTerminalLogs()
    store.appendToolUse({ tool_name: 'read', tool_input: {}, tool_use_id: 'tu9' })
    store.appendToolResult({ tool_use_id: 'tu9', output: 'done', is_error: true })
    store.appendLog({ content: 'hello' })

    expect(store.logs.value.map(row => row.type)).toEqual(['tool_use', 'tool_result', 'log'])
    expect(store.logs.value[1]?.is_error).toBe(true)

    store.clear()
    expect(store.logs.value).toHaveLength(0)
  })

  it('uses the same agent event time and correlation in live and restored tools', () => {
    const store = useTerminalLogs()
    const activity = {
      event_id: 'event-1', agent: 'opencode', kind: 'mcp', tool_name: 'read_item',
      mcp_server: 'example', ai_job_id: 'job-1', session_turn_id: 'turn-1', attempt: 1,
      occurred_at: '2026-05-01T03:00:00.321Z', received_at: '2026-05-01T03:00:01Z',
      time_source: 'agent_event', truncated: false,
    }
    const payload = { task_id: 'task', tool_use_id: 'call-1', output: 'result', is_error: false, activity }
    store.appendToolResult(payload)
    const live = store.logs.value[0]
    store.restoreFromHistory([{
      id: activity.event_id, type: 'STDOUT', created_at: '2026-05-01T03:00:02Z',
      content: JSON.stringify({ contract_version: 2, event_type: 'tool_result', event_id: activity.event_id, payload }),
    }])
    expect(store.logs.value[0]).toEqual(live)
    expect(store.logs.value[0]?.created_at).toBe(activity.occurred_at)
    expect(store.logs.value[0]?.activity?.session_turn_id).toBe('turn-1')
  })
})
