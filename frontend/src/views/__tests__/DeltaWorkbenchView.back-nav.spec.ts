import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  put: vi.fn(),
}))

vi.mock('@/utils/api', () => ({
  default: apiMock,
}))

describe('useTaskDetailSections — back navigation refresh', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
  })

  it('loadSection with force:true re-fetches even when already loaded', async () => {
    const { useTaskDetailSections } = await import('@/composables/useTaskDetailSections')
    const { loadSection } = useTaskDetailSections()

    apiMock.get.mockResolvedValueOnce({
      data: { items: [{ id: 'delta-1' }], total: 1, page: 1, page_size: 20 },
    })
    const first = await loadSection('ws-1', 'task-1', 'humanDelta')
    expect(first).toEqual([{ id: 'delta-1' }])
    expect(apiMock.get).toHaveBeenCalledTimes(1)

    const second = await loadSection('ws-1', 'task-1', 'humanDelta')
    expect(second).toEqual([{ id: 'delta-1' }])
    expect(apiMock.get).toHaveBeenCalledTimes(1)

    apiMock.get.mockResolvedValueOnce({
      data: { items: [{ id: 'delta-1' }, { id: 'delta-2' }], total: 2, page: 1, page_size: 20 },
    })
    const third = await loadSection('ws-1', 'task-1', 'humanDelta', { force: true })
    expect(third).toEqual([{ id: 'delta-1' }, { id: 'delta-2' }])
    expect(apiMock.get).toHaveBeenCalledTimes(2)
  })

  it('invalidateSection clears loaded state so next loadSection re-fetches', async () => {
    const { useTaskDetailSections } = await import('@/composables/useTaskDetailSections')
    const { loadSection, invalidateSection, sections } = useTaskDetailSections()

    apiMock.get.mockResolvedValueOnce({
      data: { items: [{ id: 'd-1' }], total: 1, page: 1, page_size: 20 },
    })
    await loadSection('ws-1', 'task-1', 'humanDelta')
    expect(sections.humanDelta.loaded).toBe(true)

    invalidateSection('humanDelta')
    expect(sections.humanDelta.loaded).toBe(false)
    expect(sections.humanDelta.data).toBeNull()

    apiMock.get.mockResolvedValueOnce({
      data: { items: [{ id: 'd-2' }], total: 1, page: 1, page_size: 20 },
    })
    const result = await loadSection('ws-1', 'task-1', 'humanDelta')
    expect(result).toEqual([{ id: 'd-2' }])
    expect(apiMock.get).toHaveBeenCalledTimes(2)
  })

  it('loadSection re-fetches after invalidateSection + loadSection(force:true) sequence', async () => {
    const { useTaskDetailSections } = await import('@/composables/useTaskDetailSections')
    const { loadSection, invalidateSection, sections } = useTaskDetailSections()

    apiMock.get.mockResolvedValueOnce({
      data: { items: [{ id: 'old-delta' }], total: 1, page: 1, page_size: 20 },
    })
    await loadSection('ws-1', 'task-1', 'humanDelta')
    expect(sections.humanDelta.loaded).toBe(true)

    invalidateSection('humanDelta')

    apiMock.get.mockResolvedValueOnce({
      data: { items: [{ id: 'old-delta' }, { id: 'new-delta' }], total: 2, page: 1, page_size: 20 },
    })
    const result = await loadSection('ws-1', 'task-1', 'humanDelta', { force: true })
    expect(result).toHaveLength(2)
    expect(result).toEqual([{ id: 'old-delta' }, { id: 'new-delta' }])
  })
})
