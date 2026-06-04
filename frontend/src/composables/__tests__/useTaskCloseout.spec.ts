import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  post: vi.fn(),
}))

vi.mock('@/utils/api', () => ({
  default: apiMock,
}))

describe('useTaskCloseout', () => {
  beforeEach(() => {
    apiMock.post.mockReset()
  })

  it('uploads evidence files before completing a task through closeout API', async () => {
    const { useTaskCloseout } = await import('@/composables/useTaskCloseout')
    apiMock.post
      .mockResolvedValueOnce({ data: { filename: 'evidence.txt', path: 'uploads/evidence.txt', url: '/api/upload/files/evidence.txt' } })
      .mockResolvedValueOnce({ data: { task_id: 'task-1', workspace_id: 'ws-1', status: 'DONE', evidence_ids: ['evidence-1'] } })

    const closeout = useTaskCloseout()
    const file = new File(['ok'], 'evidence.txt', { type: 'text/plain' })
    const result = await closeout.completeTask(
      'ws-1',
      'task-1',
      {
        completion_summary: 'Implemented locally.',
        landing_method: 'HUMAN_ADJUSTED',
        commit_id: 'abc123',
      },
      [file],
    )

    expect(apiMock.post).toHaveBeenNthCalledWith(1, '/upload', expect.any(FormData))
    expect(apiMock.post).toHaveBeenNthCalledWith(
      2,
      '/workspaces/ws-1/tasks/task-1/closeout/complete',
      expect.objectContaining({
        completion_summary: 'Implemented locally.',
        landing_method: 'HUMAN_ADJUSTED',
        commit_id: 'abc123',
        evidence_attachments: [
          expect.objectContaining({
            filename: 'evidence.txt',
            source_uri: '/api/upload/files/evidence.txt',
          }),
        ],
      }),
    )
    expect(result?.status).toBe('DONE')
  })

  it('submits failure closeout without calling old cancel endpoint', async () => {
    const { useTaskCloseout } = await import('@/composables/useTaskCloseout')
    apiMock.post
      .mockResolvedValueOnce({ data: { filename: 'compile.log', path: 'uploads/compile.log', url: '/api/upload/files/compile.log' } })
      .mockResolvedValueOnce({ data: { task_id: 'task-1', workspace_id: 'ws-1', status: 'FAILED', evidence_ids: ['evidence-1'] } })

    const closeout = useTaskCloseout()
    await closeout.failTask(
      'ws-1',
      'task-1',
      {
        failure_stage: 'COMPILE',
        failure_reason: 'COMPILE_ERROR',
        failure_summary: 'Compile failed locally.',
      },
      [new File(['error'], 'compile.log', { type: 'text/plain' })],
    )

    expect(apiMock.post).toHaveBeenLastCalledWith(
      '/workspaces/ws-1/tasks/task-1/closeout/fail',
      expect.objectContaining({
        failure_stage: 'COMPILE',
        failure_reason: 'COMPILE_ERROR',
      }),
    )
    expect(apiMock.post.mock.calls.some((call) => String(call[0]).endsWith('/cancel'))).toBe(false)
  })
})
