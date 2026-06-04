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
      }),
    ).resolves.toMatchObject({ status: 'CODING' })

    expect(apiMock.post).toHaveBeenCalledWith('/workspaces/ws-1/tasks/task-1/resume-interrupted', {
      prompt: 'continue here',
      confirm_continue: false,
    })
    expect(controls.resumingInterruptedTask.value).toBe(false)
  })
})
