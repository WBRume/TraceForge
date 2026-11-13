import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  post: vi.fn(),
}))

vi.mock('@/utils/api', () => ({
  default: apiMock,
}))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))

describe('useTaskCloseout', () => {
  beforeEach(() => {
    apiMock.post.mockReset()
  })

  it('uploads evidence files before completing a task through closeout API', async () => {
    const { useTaskCloseout } = await import('@/composables/useTaskCloseout')
    apiMock.post
      .mockResolvedValueOnce({ data: { id: 'attachment-1' } })
      .mockResolvedValueOnce({ data: { task_id: 'task-1', workspace_id: 'ws-1', status: 'COMPLETED', evidence_ids: ['evidence-1'] } })

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

    expect(apiMock.post).toHaveBeenNthCalledWith(1, '/workspaces/ws-1/tasks/task-1/closeout/attachments', expect.any(FormData))
    expect(apiMock.post).toHaveBeenNthCalledWith(
      2,
      '/workspaces/ws-1/tasks/task-1/closeout/complete',
      expect.objectContaining({
        completion_summary: 'Implemented locally.',
        landing_method: 'HUMAN_ADJUSTED',
        commit_id: 'abc123',
        evidence_attachments: [{ attachment_id: 'attachment-1' }],
      }),
    )
    expect(result?.status).toBe('COMPLETED')
  })

  it('submits failure closeout without calling old cancel endpoint', async () => {
    const { useTaskCloseout } = await import('@/composables/useTaskCloseout')
    apiMock.post
      .mockResolvedValueOnce({ data: { id: 'attachment-1' } })
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

  it.each([
    {
      method: 'completeTask', endpoint: 'complete', status: 'COMPLETED',
      fields: { completion_summary: 'Verified externally', landing_method: 'HUMAN_ADJUSTED' },
    },
    {
      method: 'failTask', endpoint: 'fail', status: 'FAILED',
      fields: { failure_summary: 'External build failed', failure_stage: 'COMPILE', failure_reason: 'COMPILE_ERROR' },
    },
  ] as const)('reuses uploaded references when retrying $endpoint after a lost response', async scenario => {
    const { useTaskCloseout } = await import('@/composables/useTaskCloseout')
    const closeout = useTaskCloseout()
    const file = new File(['log'], 'build.log')
    const receipt = { status: scenario.status, evidence_ids: ['evidence'], final_summary_id: 'summary' }
    apiMock.post
      .mockResolvedValueOnce({ data: { id: 'attachment-1' } })
      .mockRejectedValueOnce(new Error('Connection lost'))
      .mockResolvedValueOnce({ data: receipt })
    const submit = () => scenario.method === 'completeTask'
      ? closeout.completeTask('ws', 'task', scenario.fields, [file])
      : closeout.failTask('ws', 'task', scenario.fields, [file])

    expect(await submit()).toBeNull()
    expect(await submit()).toEqual(receipt)
    expect(apiMock.post.mock.calls.map(([path]) => path)).toEqual([
      '/workspaces/ws/tasks/task/closeout/attachments',
      `/workspaces/ws/tasks/task/closeout/${scenario.endpoint}`, `/workspaces/ws/tasks/task/closeout/${scenario.endpoint}`,
    ])
    expect(apiMock.post.mock.calls[2]).toEqual(apiMock.post.mock.calls[1])
  })
})
