import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Router } from 'vue-router'
import { openQueueJobTarget } from '@/composables/queue/queueJobOperations'
import type { QueueJobItem } from '@/types/queue'

const apiMock = vi.hoisted(() => ({ post: vi.fn() }))
vi.mock('@/utils/api', () => ({ default: apiMock }))

const item: QueueJobItem = {
  source: 'provision',
  job_id: 'job-1',
  job_type: 'CREATE_TASK',
  status: 'SUCCESS',
  progress: 100,
  creator_id: 'user-1',
  created_at: '2026-11-10T00:00:00Z',
  target_path: '/workspaces/workspace-1/chat/task-1',
  actions: { can_stop: false, can_retry: false, can_open: true },
}

describe('open queue result after a pending specification upload', () => {
  beforeEach(() => vi.clearAllMocks())

  it.each([true, false])('only navigates when the original context is still current: %s', async (stay) => {
    let finishUpload!: (value: unknown) => void
    apiMock.post.mockReturnValue(new Promise(resolve => { finishUpload = resolve }))
    const push = vi.fn().mockResolvedValue(undefined)
    let current = true
    const file = new File(['# Specification'], 'spec.md')
    const operation = openQueueJobTarget(item, {
      router: { push } as unknown as Router,
      provisioningStore: {
        consumePendingTaskSpec: () => ({ workspaceId: 'workspace-1', taskId: 'task-1', file }),
      },
      t: key => key,
      isCurrent: () => current,
    })

    expect(apiMock.post).toHaveBeenCalledOnce()
    expect(push).not.toHaveBeenCalled()
    current = stay
    finishUpload({ data: {} })
    await operation

    if (stay) expect(push).toHaveBeenCalledWith(item.target_path)
    else expect(push).not.toHaveBeenCalled()
  })
})
