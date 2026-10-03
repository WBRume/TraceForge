import { afterEach, describe, expect, it, vi } from 'vitest'
import { createDraftPersistence } from '../draftPersistence'
import { buildDraft, createSplitItem, restoreSplitItems } from '../model'
import type { RequirementImportBatch, RequirementSplitDraft } from '@/types/workspaceAssets'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

afterEach(() => vi.useRealTimers())

describe('split draft persistence lifecycle', () => {
  it('serializes writes and saves the newest edit after the current request', async () => {
    const first = deferred<boolean>()
    let title = 'first'
    const save = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue(true)
    const draft = createDraftPersistence({ snapshot: () => ({ items: [], change_reason: title }), save, status: vi.fn() })
    draft.open()
    draft.schedule()
    const pending = draft.flush()
    title = 'latest'
    draft.schedule()
    expect(draft.flush()).toBe(pending)
    expect(save).toHaveBeenCalledTimes(1)
    first.resolve(true)
    expect(await pending).toBe(true)
    expect(save.mock.calls.map(([payload]) => payload.change_reason)).toEqual(['first', 'latest'])
    draft.dispose()
  })

  it.each(['discard', 'confirm'])('waits for sent writes before %s and forbids late saves', async () => {
    vi.useFakeTimers()
    const request = deferred<boolean>()
    const save = vi.fn(() => request.promise)
    const consume = vi.fn()
    const draft = createDraftPersistence({ snapshot: () => ({ items: [] }), save, status: vi.fn() })
    draft.open()
    draft.schedule()
    const writing = draft.flush()
    const closing = draft.close().then(consume)
    draft.schedule()
    expect(consume).not.toHaveBeenCalled()
    request.resolve(true)
    await Promise.all([writing, closing])
    draft.schedule()
    await vi.runAllTimersAsync()
    await draft.flush()
    expect(save).toHaveBeenCalledTimes(1)
    expect(consume).toHaveBeenCalledTimes(1)
    expect(draft.canSaveOnExit()).toBe(false)
  })

  it('debounces edits and refuses autosave while data is being restored', async () => {
    vi.useFakeTimers()
    const save = vi.fn().mockResolvedValue(true)
    const draft = createDraftPersistence({ snapshot: () => ({ items: [] }), save, status: vi.fn() })
    draft.schedule()
    await vi.runAllTimersAsync()
    expect(save).not.toHaveBeenCalled()
    draft.open()
    draft.schedule()
    await vi.advanceTimersByTimeAsync(500)
    draft.schedule()
    await vi.advanceTimersByTimeAsync(799)
    expect(save).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(save).toHaveBeenCalledTimes(1)
    draft.dispose()
  })

  it('retains unsaved revisions after failure and allows retry after failed consumption', async () => {
    const status = vi.fn()
    const save = vi.fn().mockResolvedValueOnce(false).mockResolvedValue(true)
    const draft = createDraftPersistence({ snapshot: () => ({ items: [] }), save, status })
    draft.open()
    draft.schedule()
    expect(await draft.flush()).toBe(false)
    expect(status).toHaveBeenLastCalledWith('error')
    await draft.close()
    draft.open()
    expect(draft.canSaveOnExit()).toBe(true)
    expect(await draft.flush()).toBe(true)
    expect(status).toHaveBeenLastCalledWith('saved')
    draft.dispose()
  })

  it('disposal prevents pending edits from starting another request', async () => {
    const request = deferred<boolean>()
    const save = vi.fn(() => request.promise)
    const draft = createDraftPersistence({ snapshot: () => ({ items: [] }), save, status: vi.fn() })
    draft.open()
    draft.schedule()
    const writing = draft.flush()
    draft.schedule()
    draft.dispose()
    request.resolve(true)
    await writing
    expect(save).toHaveBeenCalledTimes(1)
  })
})

describe('split editing model', () => {
  const batch = { items: [{ id: 'a', title: 'A', status: 'DRAFT' }, { id: 'b', title: 'B', status: 'DRAFT' }] } as RequirementImportBatch

  it('restores the draft as the full editing state so deleted suggestions stay deleted', () => {
    const draft: RequirementSplitDraft = { items: [{ item_id: 'b', include: false, title: 'Edited', acceptance_criteria: [] }] }
    const items = restoreSplitItems(batch, draft)
    expect(items.map(item => item.item_id)).toEqual(['b'])
    expect(items[0]).toMatchObject({ title: 'Edited', include: false })
    expect(restoreSplitItems(batch, { items: [] })).toEqual([])
  })

  it('takes immutable snapshots so edits cannot mutate an in-flight request body', () => {
    const item = createSplitItem()
    item.acceptance_criteria = ['first']
    const draft = buildDraft([item], 'reason')
    item.title = 'later'
    item.acceptance_criteria.push('second')
    expect(draft.items[0]?.title).toBe('')
    expect(draft.items[0]?.acceptance_criteria).toEqual(['first'])
  })
})
