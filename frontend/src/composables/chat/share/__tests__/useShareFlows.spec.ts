import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'

/**
 * useShareFlows 编排测试：mock 两个下游数据源（分享链接 / 待采纳建议），
 * 只验证分享弹窗生命周期与「采纳 → 填入草稿」的追加/替换决策流。
 */
const shareModelStub = vi.hoisted(() => ({
  loadShares: vi.fn(),
  createShare: vi.fn(),
  revokeShare: vi.fn(),
}))

const suggestionsModelStub = vi.hoisted(() => ({
  patchSuggestion: vi.fn(),
  copySuggestion: vi.fn(),
}))

vi.mock('@/composables/useTaskSessionShares', () => ({
  useTaskSessionShares: () => shareModelStub,
}))

vi.mock('@/composables/useShareSuggestions', () => ({
  useShareSuggestions: () => suggestionsModelStub,
}))

import { useShareFlows } from '@/composables/chat/share/useShareFlows'

const mountFlows = () => {
  let captured: ReturnType<typeof useShareFlows> | null = null
  const draft = ref('')
  const Harness = defineComponent({
    setup() {
      captured = useShareFlows({
        getWorkspaceId: () => 'ws-1',
        getTaskId: () => 'task-1',
        getChatDraft: () => draft.value,
        setChatDraft: (content) => { draft.value = content },
      })
      return {}
    },
    template: '<div />',
  })
  mount(Harness)
  return { flows: captured!, draft }
}

const makeSuggestion = (overrides: Partial<Record<string, unknown>> = {}) => ({
  id: 'sug-1',
  effective_content: '建议内容',
  ...overrides,
})

describe('useShareFlows', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('opens the share dialog, resets the just-created highlight and loads the list', () => {
    const { flows } = mountFlows()
    shareModelStub.loadShares.mockResolvedValueOnce([])

    flows.openShareDialog()

    expect(flows.showShareDialog.value).toBe(true)
    expect(flows.justCreatedShare.value).toBeNull()
    expect(shareModelStub.loadShares).toHaveBeenCalledTimes(1)
  })

  const makeCreatedShare = (id: string) => ({
    id,
    mode: 'READ',
    expires_at: '',
    instruction_text: null,
    session_generation: 1,
    share_token: 't',
    share_url: 'u',
  })

  it('clears the just-created highlight only when the revoked share matches it', async () => {
    const { flows } = mountFlows()
    shareModelStub.createShare.mockResolvedValueOnce(makeCreatedShare('share-1'))
    await flows.handleCreateShare({ mode: 'READ', expires_in_days: 7 })
    expect(flows.justCreatedShare.value?.id).toBe('share-1')

    shareModelStub.revokeShare.mockResolvedValueOnce(true)
    await flows.handleRevokeShare('share-1')
    expect(flows.justCreatedShare.value).toBeNull()
  })

  it('keeps the highlight when revoking a different share', async () => {
    const { flows } = mountFlows()
    flows.justCreatedShare.value = makeCreatedShare('share-1')
    shareModelStub.revokeShare.mockResolvedValueOnce(true)

    await flows.handleRevokeShare('share-other')

    expect(flows.justCreatedShare.value?.id).toBe('share-1')
  })

  it('fills an empty draft directly after adopting a suggestion', async () => {
    const { flows, draft } = mountFlows()
    suggestionsModelStub.patchSuggestion.mockResolvedValueOnce(makeSuggestion())

    await flows.handleAdoptSuggestion(makeSuggestion() as any)

    expect(draft.value).toBe('建议内容')
    expect(flows.adoptingSuggestion.value).toBeNull()
  })

  it('asks append-or-replace when the draft already has content', async () => {
    const { flows, draft } = mountFlows()
    draft.value = '已有草稿'
    suggestionsModelStub.patchSuggestion.mockResolvedValueOnce(makeSuggestion())

    await flows.handleAdoptSuggestion(makeSuggestion() as any)

    // 不直接写入，等待用户选择
    expect(draft.value).toBe('已有草稿')
    expect(flows.adoptingSuggestion.value?.id).toBe('sug-1')

    flows.confirmAdoptAppend()
    expect(draft.value).toBe('已有草稿\n建议内容')
    expect(flows.adoptingSuggestion.value).toBeNull()
  })

  it('replaces the whole draft when the user chooses replace', async () => {
    const { flows, draft } = mountFlows()
    draft.value = '已有草稿'
    suggestionsModelStub.patchSuggestion.mockResolvedValueOnce(makeSuggestion())

    await flows.handleAdoptSuggestion(makeSuggestion() as any)
    flows.confirmAdoptReplace()

    expect(draft.value).toBe('建议内容')
  })

  it('keeps the draft untouched when the adopt choice is cancelled', async () => {
    const { flows, draft } = mountFlows()
    draft.value = '已有草稿'
    suggestionsModelStub.patchSuggestion.mockResolvedValueOnce(makeSuggestion())

    await flows.handleAdoptSuggestion(makeSuggestion() as any)
    flows.cancelAdoptChoice()

    expect(draft.value).toBe('已有草稿')
    expect(flows.adoptingSuggestion.value).toBeNull()
  })
})
