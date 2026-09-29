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
    })
    expect(controls.interruptingTask.value).toBe(false)
  })

  it('resumes an interrupted task through the resume endpoint', async () => {
    const { useTaskSessionControls } = await import('@/composables/useTaskSessionControls')
    apiMock.post.mockResolvedValueOnce({ data: { status: 'CODING' } })

    const controls = useTaskSessionControls({ getWorkspaceId: () => 'ws-1' })
    await expect(
      controls.resumeInterruptedTask('task-1', {
        prompt: ' continue here ',
        confirmContinue: false,
        clientMessageId: 'client-1',
      }),
    ).resolves.toMatchObject({ status: 'CODING' })

    expect(apiMock.post).toHaveBeenCalledWith('/workspaces/ws-1/tasks/task-1/resume-interrupted', {
      prompt: 'continue here',
      confirm_continue: false,
      client_message_id: 'client-1',
    })
    expect(controls.resumingInterruptedTask.value).toBe(false)
  })
})
