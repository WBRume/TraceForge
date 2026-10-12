import { describe, expect, it } from 'vitest'
import { consumeCollaborationIntent, rememberCollaborationIntent } from '../localCollaborationIntent'
describe('task creation collaboration intent', () => {
  it('keeps review intent scoped to the created task and consumes it only once', () => {
    rememberCollaborationIntent('ws', 'task-a')
    expect(consumeCollaborationIntent('ws', 'task-b')).toBe(false)
    expect(consumeCollaborationIntent('other-workspace', 'task-a')).toBe(false)
    expect(consumeCollaborationIntent('ws', 'task-a')).toBe(true)
    expect(consumeCollaborationIntent('ws', 'task-a')).toBe(false)
  })
})
