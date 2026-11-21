import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  post: vi.fn(),
}))

vi.mock('@/utils/api', () => ({
  default: apiMock,
}))

describe('useTaskSessionControls', () => {
  beforeEach(() => {
    apiMock.post.mockReset()
  })

  it('keeps undo pending beyond 15 seconds until the backend actually completes', async () => {
    vi.useFakeTimers()
    try {
      const { useTaskSessionControls } = await import('@/composables/useTaskSessionControls')
      apiMock.post.mockImplementationOnce((_url, _body, config) => new Promise((resolve, reject) => {
        const timeout = config?.timeout ?? 15000
        if (timeout) setTimeout(() => reject(new Error('client timeout')), timeout)
        setTimeout(() => resolve({ data: { operation_id: 'op-1', removed_message_ids: ['message-1'] } }), 20000)
      }))
      const controls = useTaskSessionControls({ getWorkspaceId: () => 'ws-1' })
      const pending = controls.undoTaskMessage('task-1', 'message-1', { operationId: 'op-1' })
      expect(controls.undoingTaskMessage.value).toBe(true)
      await vi.advanceTimersByTimeAsync(16000)
      expect(controls.undoingTaskMessage.value).toBe(true)
      await vi.advanceTimersByTimeAsync(4000)
      await expect(pending).resolves.toMatchObject({ operation_id: 'op-1' })
      expect(controls.undoingTaskMessage.value).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })

  it('reports an actual backend failure and releases the undo indicator', async () => {
    const { useTaskSessionControls } = await import('@/composables/useTaskSessionControls')
    const failure = new Error('restore verification failed')
    apiMock.post.mockRejectedValueOnce(failure)
    const controls = useTaskSessionControls({ getWorkspaceId: () => 'ws-1' })
    await expect(controls.undoTaskMessage('task-1', 'message-1', { operationId: 'op-1' })).rejects.toBe(failure)
    expect(controls.undoingTaskMessage.value).toBe(false)
  })

  it('interrupts a task through the temporary interrupt endpoint', async () => {
    const { useTaskSessionControls } = await import('@/composables/useTaskSessionControls')
    apiMock.post.mockResolvedValueOnce({ data: { status: 'INTERRUPTED' } })

    const controls = useTaskSessionControls({ getWorkspaceId: () => 'ws-1' })
    await expect(controls.interruptTask('task-1', ' pause ')).resolves.toMatchObject({
      status: 'INTERRUPTED',
    })

    expect(apiMock.post).toHaveBeenCalledWith('/workspaces/ws-1/tasks/task-1/interrupt', {
      reason: 'pause',
      command_id: expect.any(String),
    })
    expect(controls.interruptingTask.value).toBe(false)
  })

  it('fences the original interrupt across an uncertain response and replaces a definitively rejected command', async () => {
    const { useTaskSessionControls } = await import('@/composables/useTaskSessionControls')
    const controls = useTaskSessionControls({ getWorkspaceId: () => 'ws-1' })
    const lost = new Error('response lost')
    const stale = { response: { status: 409 } }
    apiMock.post.mockRejectedValueOnce(lost).mockRejectedValueOnce(stale).mockResolvedValueOnce({ data: {} })
    await expect(controls.interruptTask('t', 'pause', '9007199254740993')).rejects.toBe(lost)
    await expect(controls.interruptTask('t', 'translated pause reason', '9007199254740994')).rejects.toBe(stale)
    await controls.interruptTask('t', 'pause', '9007199254740994')
    const [first, retry, next] = apiMock.post.mock.calls.map(call => call[1])
    expect(first.expected_status_seq).toBe('9007199254740993')
    expect(retry).toEqual(first)
    expect(next.expected_status_seq).toBe('9007199254740994')
    expect(next.command_id).not.toBe(first.command_id)
  })

  it('keeps the first resume request pending while the server recovers the previous attempt', async () => {
    vi.useFakeTimers()
    try {
      const { useTaskSessionControls } = await import('@/composables/useTaskSessionControls')
      apiMock.post.mockImplementationOnce((_url, _body, config) => new Promise((resolve, reject) => {
        const timeout = config?.timeout ?? 15000
        if (timeout) setTimeout(() => reject(new Error('client timeout')), timeout)
        setTimeout(() => resolve({ data: { submission: { id: 'resume-1' } } }), 30000)
      }))
      const controls = useTaskSessionControls({ getWorkspaceId: () => 'ws-1' })
      const pending = controls.resumeInterruptedTask('task-1', {
        prompt: ' continue here ',
        confirmContinue: false,
        clientMessageId: 'client-1',
      })
      await vi.advanceTimersByTimeAsync(16000)
      expect(controls.resumingInterruptedTask.value).toBe(true)
      await vi.advanceTimersByTimeAsync(14000)
      await expect(pending).resolves.toMatchObject({ submission: { id: 'resume-1' } })
      expect(apiMock.post).toHaveBeenCalledTimes(1)
      expect(apiMock.post).toHaveBeenCalledWith('/workspaces/ws-1/tasks/task-1/resume-interrupted', {
        prompt: 'continue here',
        confirm_continue: false,
        client_message_id: 'client-1',
      }, { timeout: 0 })
      expect(controls.resumingInterruptedTask.value).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })
})
