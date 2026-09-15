import { describe, expect, it } from 'vitest'
import { useTaskRuntimePanels } from '@/composables/useTaskRuntimePanels'

describe('useTaskRuntimePanels', () => {
  it('restores runtime panels independently for each task', () => {
    const panels = useTaskRuntimePanels()
    panels.save('task-1', {
      statusCards: [{
        id: 'status-1',
        type: 'status',
        status: 'INIT',
        message: 'Agent 会话已启动 (model: test-model)',
        model: 'test-model',
      }],
      thinkingContent: 'Inspecting the repository',
      showThinking: true,
      thinkingExpanded: true,
    })

    expect(panels.restore('task-2')).toBeNull()
    expect(panels.restore('task-1')).toMatchObject({
      thinkingContent: 'Inspecting the repository',
      showThinking: true,
      thinkingExpanded: true,
      statusCards: [{ message: 'Agent 会话已启动 (model: test-model)' }],
    })
  })

  it('returns copies and clears stale snapshots', () => {
    const panels = useTaskRuntimePanels()
    panels.save('task-1', {
      statusCards: [{ id: 'status-1', type: 'status', status: 'RUNNING' }],
      thinkingContent: 'Thinking',
      showThinking: true,
      thinkingExpanded: false,
    })

    const restored = panels.restore('task-1')
    restored!.statusCards[0].status = 'FAILED'

    expect(panels.restore('task-1')?.statusCards[0].status).toBe('RUNNING')
    panels.clear('task-1')
    expect(panels.restore('task-1')).toBeNull()
  })
})
