/**
 * 发起人收到的分享输入：轮询拉取、编辑、复制、采纳、忽略。
 *
 * 轮询策略（第一版）：进入会话立即查询；页面可见时每 10 秒增量拉取，
 * 失焦暂停，重新聚焦立即补拉。不依赖任务 WS 广播。
 */
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import api from '@/utils/api'

export type ShareSuggestion = {
  id: string
  task_id: string
  session_generation: number
  visitor_id: string
  sender_user_id: string | null
  display_name: string | null
  original_content: string
  edited_content: string | null
  status: string
  version: number
  created_at: string
  updated_at: string | null
  adopted_at: string | null
  effective_content: string
}

const POLL_INTERVAL_MS = 10_000

export function useShareSuggestions(options: {
  getWorkspaceId: () => string
  getTaskId: () => string
}) {
  const { t } = useI18n()

  const suggestions = shallowRef<ShareSuggestion[]>([])
  const loading = ref(false)
  const panelOpen = ref(false)
  const actingIds = ref<Set<string>>(new Set())

  const pendingSuggestions = computed(() =>
    suggestions.value.filter((item) => item.status === 'PENDING')
  )
  const pendingCount = computed(() => pendingSuggestions.value.length)

  let pollTimer: number | null = null

  const loadSuggestions = async (silent = true) => {
    const taskId = options.getTaskId()
    if (!taskId) return
    if (!silent) loading.value = true
    try {
      const res = await api.get(
        `/workspaces/${options.getWorkspaceId()}/tasks/${taskId}/share-suggestions`
      )
      suggestions.value = res.data?.items || []
    } catch {
      // 轮询失败静默；手动刷新时提示
      if (!silent) ElMessage.error(t('share.errors.load_suggestions_failed'))
    } finally {
      if (!silent) loading.value = false
    }
  }

  const patchSuggestion = async (
    suggestion: ShareSuggestion,
    action: 'edit' | 'adopt' | 'dismiss',
    editedContent?: string
  ): Promise<ShareSuggestion | null> => {
    if (actingIds.value.has(suggestion.id)) return null
    actingIds.value = new Set(actingIds.value).add(suggestion.id)
    try {
      const res = await api.patch(
        `/workspaces/${options.getWorkspaceId()}/tasks/${options.getTaskId()}/share-suggestions/${suggestion.id}`,
        {
          action,
          expected_version: suggestion.version,
          ...(action === 'edit' ? { edited_content: editedContent } : {}),
        }
      )
      const updated = res.data as ShareSuggestion
      suggestions.value = suggestions.value.map((item) =>
        item.id === updated.id ? updated : item
      )
      return updated
    } catch (error) {
      const status = (error as { response?: { status?: number } })?.response?.status
      if (status === 409) {
        ElMessage.warning(t('share.errors.suggestion_conflict'))
      } else {
        ElMessage.error(t('share.errors.action_failed'))
      }
      return null
    } finally {
      const next = new Set(actingIds.value)
      next.delete(suggestion.id)
      actingIds.value = next
    }
  }

  const copySuggestion = async (suggestion: ShareSuggestion) => {
    const text = suggestion.effective_content
    try {
      await navigator.clipboard.writeText(text)
      ElMessage.success(t('chat.copied'))
    } catch {
      ElMessage.error(t('chat.copy_failed'))
    }
  }

  // 会话选择/切换：立即清空旧列表并补拉新任务的待采纳输入。
  // ChatView 挂载早于 currentTask 就绪，仅靠 onMounted 首拉会落空、
  // 只能等下一轮 10s 轮询——这里以 taskId 为准及时刷新。
  watch(
    () => options.getTaskId(),
    (taskId) => {
      if (!taskId) {
        suggestions.value = []
        return
      }
      suggestions.value = []
      void loadSuggestions()
    },
    { immediate: true },
  )

  const startPolling = () => {
    if (pollTimer !== null) return
    pollTimer = window.setInterval(() => {
      if (document.visibilityState === 'visible') {
        void loadSuggestions()
      }
    }, POLL_INTERVAL_MS)
  }

  const stopPolling = () => {
    if (pollTimer !== null) {
      window.clearInterval(pollTimer)
      pollTimer = null
    }
  }

  const onVisibilityChange = () => {
    if (document.visibilityState === 'visible') {
      void loadSuggestions()
    }
  }

  onMounted(() => {
    void loadSuggestions()
    startPolling()
    document.addEventListener('visibilitychange', onVisibilityChange)
  })

  onUnmounted(() => {
    stopPolling()
    document.removeEventListener('visibilitychange', onVisibilityChange)
  })

  return {
    suggestions,
    loading,
    panelOpen,
    actingIds,
    pendingSuggestions,
    pendingCount,
    loadSuggestions,
    patchSuggestion,
    copySuggestion,
  }
}
