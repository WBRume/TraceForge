import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('@/utils/api', () => ({
  default: apiMock,
}))

describe('agentApi service', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
  })

  it('lists agent tasks with expected query params', async () => {
    const { listAgentTasks } = await import('@/services/agentApi')
    apiMock.get.mockResolvedValueOnce({ data: { items: [], total: 0, page: 2, page_size: 25 } })

    await expect(listAgentTasks(2, 25)).resolves.toMatchObject({ total: 0 })
    expect(apiMock.get).toHaveBeenCalledWith('/agent/tasks', {
      params: { page: 2, page_size: 25 },
    })
  })

  it('downloads proposal patch as text', async () => {
    const { downloadChangeProposalPatch } = await import('@/services/agentApi')
    apiMock.get.mockResolvedValueOnce({ data: 'diff --git a/a b/a' })

    await expect(downloadChangeProposalPatch('proposal-1')).resolves.toContain('diff --git')
    expect(apiMock.get).toHaveBeenCalledWith('/agent/change-proposals/proposal-1/patch', {
      responseType: 'text',
      transformResponse: [expect.any(Function)],
    })
  })

  it('returns null when latest proposal is empty', async () => {
    const { getLatestChangeProposal } = await import('@/services/agentApi')
    apiMock.get.mockResolvedValueOnce({ data: null })

    await expect(getLatestChangeProposal('task-1')).resolves.toBeNull()
    expect(apiMock.get).toHaveBeenCalledWith('/agent/tasks/task-1/change-proposals/latest')
  })

  it('creates task change proposal with longer timeout', async () => {
    const { createTaskChangeProposal } = await import('@/services/agentApi')
    apiMock.post.mockResolvedValueOnce({ data: { id: 'proposal-1' } })

    await expect(createTaskChangeProposal({
      workspaceId: 'ws-1',
      taskId: 'task-1',
      summary: 'ready',
      riskNotes: 'low',
    })).resolves.toMatchObject({ id: 'proposal-1' })

    expect(apiMock.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/tasks/task-1/change-proposals',
      { summary: 'ready', risk_notes: 'low' },
      { timeout: 180000 },
    )
  })

  it('uploads verification logs using multipart form data', async () => {
    const { uploadVerificationLog } = await import('@/services/agentApi')
    apiMock.post.mockResolvedValueOnce({ data: { id: 'run-1' } })

    await uploadVerificationLog({
      taskId: 'task-1',
      runId: 'run-1',
      logText: 'ok',
      logExcerpt: 'ok',
    })

    expect(apiMock.post).toHaveBeenCalledWith(
      '/agent/tasks/task-1/verification-runs/run-1/logs',
      expect.any(FormData),
    )
  })
})
