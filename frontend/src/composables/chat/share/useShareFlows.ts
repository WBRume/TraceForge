import { ref } from 'vue'
import { useTaskSessionShares, type CreatedShare } from '@/composables/useTaskSessionShares'
import { useShareSuggestions, type ShareSuggestion } from '@/composables/useShareSuggestions'

/**
 * 任务会话分享域的视图编排：分享弹窗生命周期、待采纳输入面板与
 * 「采纳建议 → 填入会话草稿」的追加/替换决策流。
 *
 * 会话草稿（chatInput）的读写经由 getter/setter 注入，使本模块不依赖
 * 具体的视图模型实例；分享/建议两个数据源在此装配并对视图暴露窄接口。
 */
export function useShareFlows(options: {
  getWorkspaceId: () => string
  getTaskId: () => string
  getChatDraft: () => string
  setChatDraft: (content: string) => void
}) {
  const sessionShares = useTaskSessionShares({
    getWorkspaceId: options.getWorkspaceId,
    getTaskId: options.getTaskId,
  })
  const shareSuggestions = useShareSuggestions({
    getWorkspaceId: options.getWorkspaceId,
    getTaskId: options.getTaskId,
  })

  const showShareDialog = ref(false)
  const justCreatedShare = ref<CreatedShare | null>(null)
  const suggestionPanelOpen = ref(false)
  const adoptingSuggestion = ref<ShareSuggestion | null>(null)

  const openShareDialog = () => {
    justCreatedShare.value = null
    showShareDialog.value = true
    void sessionShares.loadShares()
  }

  const handleCreateShare = async (payload: {
    mode: 'READ' | 'INPUT'
    expires_in_days: number
    instruction_text?: string
  }) => {
    const created = await sessionShares.createShare(payload)
    if (created) {
      justCreatedShare.value = created
    }
  }

  const handleRevokeShare = async (shareId: string) => {
    const ok = await sessionShares.revokeShare(shareId)
    // 撤销的是刚创建的链接：清掉高亮，避免旧 URL 继续被复制
    if (ok && justCreatedShare.value && justCreatedShare.value.id === shareId) {
      justCreatedShare.value = null
    }
  }

  const closeShareDialog = () => {
    showShareDialog.value = false
    justCreatedShare.value = null
  }

  // ── 待采纳输入：采纳填入草稿（先 adopt 再填入；有草稿时让用户选择追加/替换） ──
  const applySuggestionToDraft = (content: string) => {
    const current = options.getChatDraft()
    options.setChatDraft(current ? `${current}\n${content}` : content)
  }

  const handleAdoptSuggestion = async (suggestion: ShareSuggestion) => {
    const updated = await shareSuggestions.patchSuggestion(suggestion, 'adopt')
    if (!updated) return
    const current = options.getChatDraft().trim()
    if (current) {
      // 已有草稿：让用户明确选择追加或替换；取消不改变建议状态
      adoptingSuggestion.value = updated
      return
    }
    applySuggestionToDraft(updated.effective_content)
  }

  const confirmAdoptAppend = () => {
    if (!adoptingSuggestion.value) return
    applySuggestionToDraft(adoptingSuggestion.value.effective_content)
    adoptingSuggestion.value = null
  }

  const confirmAdoptReplace = () => {
    if (!adoptingSuggestion.value) return
    options.setChatDraft(adoptingSuggestion.value.effective_content)
    adoptingSuggestion.value = null
  }

  const cancelAdoptChoice = () => {
    // 取消该选择不改变建议状态；ADOPTED 记录仍可重新填入
    adoptingSuggestion.value = null
  }

  const handleEditSuggestion = async (suggestion: ShareSuggestion, editedContent: string) => {
    await shareSuggestions.patchSuggestion(suggestion, 'edit', editedContent)
  }

  const handleDismissSuggestion = async (suggestion: ShareSuggestion) => {
    await shareSuggestions.patchSuggestion(suggestion, 'dismiss')
  }

  return {
    sessionShares,
    shareSuggestions,
    showShareDialog,
    justCreatedShare,
    suggestionPanelOpen,
    adoptingSuggestion,
    openShareDialog,
    handleCreateShare,
    handleRevokeShare,
    closeShareDialog,
    handleAdoptSuggestion,
    confirmAdoptAppend,
    confirmAdoptReplace,
    cancelAdoptChoice,
    handleEditSuggestion,
    handleDismissSuggestion,
  }
}

export type ShareFlows = ReturnType<typeof useShareFlows>
