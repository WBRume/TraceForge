import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  post: vi.fn(),
  patch: vi.fn(),
  put: vi.fn(),
}))

vi.mock('@/utils/api', () => ({
  default: apiMock,
}))

describe('useTaskDetailAssets', () => {
  beforeEach(() => {
    apiMock.post.mockReset()
    apiMock.patch.mockReset()
    apiMock.put.mockReset()
  })

  it('creates Human Review records through the Task Detail write API', async () => {
    const { useTaskDetailAssets } = await import('@/composables/useTaskDetailAssets')
    apiMock.post.mockResolvedValueOnce({ data: { task: { id: 'task-1' }, human_reviews: [{ id: 'review-1' }] } })

    const assets = useTaskDetailAssets()
    const result = await assets.createHumanReview('ws-1', 'task-1', {
      outcome: 'ACCEPT_WITH_MODIFICATION',
      status: 'OPEN',
      title: 'Manual review',
    })

    expect(apiMock.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/workspace-assets/tasks/task-1/human-reviews',
      {
        outcome: 'ACCEPT_WITH_MODIFICATION',
        status: 'OPEN',
        title: 'Manual review',
      },
    )
    expect(result?.human_reviews?.[0].id).toBe('review-1')
  })

  it('creates Evidence with real source fields instead of local mock data', async () => {
    const { useTaskDetailAssets } = await import('@/composables/useTaskDetailAssets')
    apiMock.post.mockResolvedValueOnce({ data: { task: { id: 'task-1' }, evidence: [{ id: 'evidence-1' }] } })

    const assets = useTaskDetailAssets()
    const result = await assets.createEvidence('ws-1', 'task-1', {
      evidence_type: 'CODE',
      source_type: 'DIFF',
      source_uri: 'https://example.com/diff/123',
      title: 'External diff',
    })

    expect(apiMock.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/workspace-assets/tasks/task-1/evidence',
      {
        evidence_type: 'CODE',
        source_type: 'DIFF',
        source_uri: 'https://example.com/diff/123',
        title: 'External diff',
      },
    )
    expect(result?.evidence?.[0].id).toBe('evidence-1')
  })

  it('upserts Final Summary through a guarded endpoint', async () => {
    const { useTaskDetailAssets } = await import('@/composables/useTaskDetailAssets')
    apiMock.put.mockResolvedValueOnce({ data: { task: { id: 'task-1' }, final_summary: { final_status: 'PENDING' } } })

    const assets = useTaskDetailAssets()
    const result = await assets.upsertFinalSummary('ws-1', 'task-1', {
      final_status: 'PENDING',
      summary: 'Waiting for real evidence.',
    })

    expect(apiMock.put).toHaveBeenCalledWith(
      '/workspaces/ws-1/workspace-assets/tasks/task-1/final-summary',
      {
        final_status: 'PENDING',
        summary: 'Waiting for real evidence.',
      },
    )
    expect(result?.final_summary?.final_status).toBe('PENDING')
  })
})
