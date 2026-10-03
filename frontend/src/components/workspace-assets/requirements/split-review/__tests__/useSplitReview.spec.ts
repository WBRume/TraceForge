import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { useSplitReview } from '../useSplitReview'

const mocks = vi.hoisted(() => ({
  save: vi.fn(), clear: vi.fn(), confirm: vi.fn(), push: vi.fn(), message: vi.fn(),
  leave: undefined as (() => Promise<boolean>) | undefined,
}))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: mocks.push }), onBeforeRouteLeave: (guard: () => Promise<boolean>) => { mocks.leave = guard } }))
vi.mock('element-plus', () => ({ ElMessage: { error: mocks.message, info: mocks.message, success: mocks.message } }))
vi.mock('@/stores/provisioning', () => ({ useProvisioningStore: () => ({ jobList: [], dismiss: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ token: 'test' }) }))
vi.mock('@/composables/useWorkspaceAssets', () => ({ useWorkspaceAssets: () => ({
  loadRequirementDetail: async () => ({ requirement: { id: 'parent' } }),
  loadImportBatch: async () => ({ items: [{ id: 'item', title: 'Original', status: 'DRAFT' }] }),
  saveRequirementSplitDraft: mocks.save, clearRequirementSplitDraft: mocks.clear,
  confirmRequirementSplit: mocks.confirm,
}) }))

let cleanup: (() => void) | undefined
beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  mocks.save.mockResolvedValue(true)
  mocks.clear.mockResolvedValue(true)
  mocks.confirm.mockResolvedValue({ id: 'confirmed' })
})
afterEach(() => { cleanup?.(); vi.useRealTimers() })
async function setup() {
  let review!: ReturnType<typeof useSplitReview>
  const wrapper = mount(defineComponent({ setup() {
    review = useSplitReview({ wsId: 'workspace', requirementId: 'parent', batchId: 'batch' })
    return () => null
  } }))
  cleanup = () => wrapper.unmount()
  await flushPromises()
  return review
}

describe('split review workflow', () => {
  it.each(['discard', 'confirm'])('does not consume the draft before pending PUT finishes: %s', async action => {
    let resolveSave!: (value: boolean) => void
    mocks.save.mockImplementationOnce(() => new Promise(resolve => { resolveSave = resolve }))
    const review = await setup()
    review.items.value[0]!.title = 'Edited'
    await vi.advanceTimersByTimeAsync(800)
    const completing = action === 'discard' ? review.confirmDiscard() : review.handleConfirm()
    expect(mocks.clear).not.toHaveBeenCalled()
    expect(mocks.confirm).not.toHaveBeenCalled()
    resolveSave(true)
    await completing
    expect(action === 'discard' ? mocks.clear : mocks.confirm).toHaveBeenCalledTimes(1)
    await vi.runAllTimersAsync()
    expect(mocks.save).toHaveBeenCalledTimes(1)
    expect(mocks.push).toHaveBeenCalledTimes(1)
  })

  it('resumes autosave if confirmation fails', async () => {
    mocks.confirm.mockResolvedValue(null)
    const review = await setup()
    await review.handleConfirm()
    review.items.value[0]!.title = 'Retry edit'
    await vi.advanceTimersByTimeAsync(800)
    expect(mocks.save).toHaveBeenCalledWith('workspace', 'batch', expect.objectContaining({
      items: [expect.objectContaining({ title: 'Retry edit' })],
    }))
    expect(mocks.push).not.toHaveBeenCalled()
  })

  it('blocks navigation if the draft cannot be saved', async () => {
    mocks.save.mockResolvedValue(false)
    const review = await setup()
    review.items.value[0]!.title = 'Unsaved'
    expect(await mocks.leave!()).toBe(false)
    await review.goBack()
    expect(mocks.push).not.toHaveBeenCalled()
    expect(review.draftStatus.value).toBe('error')
  })

  it('keeps the active item selected when removing an earlier item', async () => {
    const review = await setup()
    review.addNewItem()
    const selected = review.activeItem.value!.item_id
    review.removeItem(0)
    expect(review.activeItem.value!.item_id).toBe(selected)
    expect(review.activeIndex.value).toBe(0)
  })
})
