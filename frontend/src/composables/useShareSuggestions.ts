/**
 * 发起人收到的分享输入：编辑、复制、采纳、忽略。
 *
 * 更新策略：不轮询。后端在访客提交/发起人操作建议后向任务房间广播
 * share_suggestion_update（由会话 WS 路由转发到 handleSuggestionNudge），
 * 前端收到 nudge 后经 REST 权限过滤拉取；页面重新聚焦时也补拉一次。
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

  let nudgeInFlight: Promise<void> | null = null

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

  /** WS share_suggestion_update：静默刷新（单飞合并短窗口内的重复 nudge）。 */
  const handleSuggestionNudge = () => {
    if (!options.getTaskId()) return
    if (nudgeInFlight) return
    nudgeInFlight = loadSuggestions()
      .catch(() => undefined)
      .finally(() => {
        nudgeInFlight = null
      })
  }

  // 会话选择/切换：立即清空旧列表并补拉新任务的待采纳输入。
  // ChatView 挂载早于 currentTask 就绪，仅靠 onMounted 首拉会落空——
  // 这里以 taskId 为准及时刷新。
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

  const onVisibilityChange = () => {
    if (document.visibilityState === 'visible') {
      void loadSuggestions()
    }
  }

  onMounted(() => {
    document.addEventListener('visibilitychange', onVisibilityChange)
  })

  onUnmounted(() => {
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
    handleSuggestionNudge,
    patchSuggestion,
    copySuggestion,
  }
}
