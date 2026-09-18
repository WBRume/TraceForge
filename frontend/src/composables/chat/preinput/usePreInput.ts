import { computed, ref } from 'vue'
import api from '@/utils/api'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { isCanceledRequest } from '../shared/requestGuards'
import type { ActivePreInput, PreInputEditPermission, PreInputMember } from '../types'

/**
 * 协作预输入（共享文档：多人就地修改/增加提示词，按行追踪归属）。
 * 状态变更全部经由任务 WS 通道（sendAction 注入）；HTTP 仅负责初始快照与成员搜索。
 */
export function usePreInput(options: {
  getWorkspaceId: () => string
  getCurrentTask: () => any
  isEngineRunning: () => boolean
  isChatLocked: () => boolean
  isWorkspaceExpert: () => boolean
  sendAction: (action: string, payload?: Record<string, any>) => boolean
  getSignal: () => AbortSignal | undefined
}) {
  const { t } = useI18n()
  const authStore = useAuthStore()

  const activePreInput = ref<ActivePreInput | null>(null)
  // WS pre_input_* 事件版本号：HTTP 初始快照返回时若已被增量事件改写则丢弃旧快照
  let preInputRevision = 0

  const preInputIsCollecting = computed(() => activePreInput.value?.status === 'COLLECTING')
  const isPreInputCreator = computed(() => {
    const pi = activePreInput.value
    return Boolean(pi && String(authStore.user?.id || '') === String(pi.creator?.user_id || ''))
  })
  const myPreInputParticipation = computed(() => {
    const pi = activePreInput.value
    if (!pi) return false
    const selfId = String(authStore.user?.id || '')
    return isPreInputCreator.value || (pi.participant_ids || []).some((id) => String(id) === selfId)
  })
  // 可修改/删除已有内容（插入新行不受限）
  const canEditPreInputShared = computed(() => {
    const pi = activePreInput.value
    if (!pi || pi.status !== 'COLLECTING') return false
    if (isPreInputCreator.value) return true
    const uid = String(authStore.user?.id || '')
    if (pi.edit_permission === 'ALL') return true
    if (pi.edit_permission === 'MENTIONED') return (pi.mentioned_user_ids || []).some((m) => String(m) === uid)
    if (pi.edit_permission === 'EXPERTS') {
      return options.isWorkspaceExpert()
    }
    return false
  })

  const reset = () => {
    activePreInput.value = null
  }

  /** HTTP 初始快照：仅 COLLECTING 状态落地；被 WS 事件超越的旧快照直接丢弃。 */
  const loadActive = async (taskId: string): Promise<boolean> => {
    if (!taskId) return false
    const workspace = options.getWorkspaceId()
    const revision = preInputRevision
    try {
      const res = await api.get(`/workspaces/${workspace}/tasks/${taskId}/pre-input/active`, {
        signal: options.getSignal(),
      })
      if (
        revision !== preInputRevision
        || String(options.getCurrentTask()?.id || '') !== String(taskId)
        || options.getWorkspaceId() !== workspace
      ) return false
      const pre = res.data?.pre_input || null
      if (pre && pre.status === 'COLLECTING') {
        activePreInput.value = pre
      } else if (activePreInput.value?.task_id === taskId) {
        activePreInput.value = null
      }
      return true
    } catch (e) {
      if (!isCanceledRequest(e)) console.warn('Failed to load active pre input', e)
      return false
    }
  }

  /** WS pre_input_* 事件分发。 */
  const handleEvent = (type: string, payload: any) => {
    if (type === 'pre_input_update') {
      if (payload?.task_id && String(payload.task_id) !== String(options.getCurrentTask()?.id || '')) return
      preInputRevision += 1
      if (payload?.status === 'COLLECTING') {
        activePreInput.value = payload
      } else if (activePreInput.value?.id === payload?.id) {
        activePreInput.value = null
      }
      return
    }
    if (type === 'pre_input_submitted') {
      // 合并后的消息由随后的 chat_message 事件 upsert 进消息列表
      preInputRevision += 1
      if (activePreInput.value?.id === payload?.id) {
        activePreInput.value = null
      }
      ElMessage.success(t('preInput.submitted_toast'))
      return
    }
    if (type === 'pre_input_error') {
      ElMessage.error(payload?.message || t('preInput.errors.generic'))
      const taskId = String(payload?.task_id || options.getCurrentTask()?.id || '')
      if (taskId) void loadActive(taskId)
    }
  }

  const startPreInput = (opts: {
    main_text: string
    mentioned_user_ids: string[]
    edit_permission: PreInputEditPermission
    wait_seconds: number
  }): boolean => {
    if (!options.getCurrentTask()?.id) return false
    if (activePreInput.value) {
      ElMessage.warning(t('preInput.errors.already_active'))
      return false
    }
    if (options.isEngineRunning()) {
      ElMessage.warning(t('preInput.errors.engine_running'))
      return false
    }
    if (options.isChatLocked()) {
      ElMessage.warning(t('chat.start_before_chat'))
      return false
    }
    return options.sendAction('pre_input_create', opts)
  }

  // 编辑共享文档（全文）：插入新文字人人可为；修改/删除已有文字需编辑权限（服务端字符级 diff 校验）
  const editPreInputDocument = (text: string): boolean => {
    const pi = activePreInput.value
    if (!pi || pi.status !== 'COLLECTING') return false
    if (!text.trim()) return false
    return options.sendAction('pre_input_edit_document', { text })
  }

  // 框选提交：把选中的一段文字替换为输入（无选中/等价纯插入人人可为，替换所选需编辑权限）
  const replacePreInputSpan = (
    start: number,
    end: number,
    anchorText: string,
    replacement: string,
  ): boolean => {
    const pi = activePreInput.value
    if (!pi || pi.status !== 'COLLECTING') return false
    return options.sendAction('pre_input_replace_span', {
      start,
      end,
      anchor_text: anchorText,
      replacement,
    })
  }

  // 无补充，标记完成（记为参与）
  const markPreInputDone = (): boolean => {
    const pi = activePreInput.value
    if (!pi || pi.status !== 'COLLECTING') return false
    return options.sendAction('pre_input_mark_done', {})
  }

  const submitPreInputManually = (): boolean => {
    if (!isPreInputCreator.value) return false
    return options.sendAction('pre_input_submit', {})
  }

  const cancelPreInput = (): boolean => {
    if (!isPreInputCreator.value) return false
    return options.sendAction('pre_input_cancel', {})
  }

  const searchPreInputMembers = async (keyword: string): Promise<PreInputMember[]> => {
    try {
      const res = await api.get(`/workspaces/${options.getWorkspaceId()}/members`, {
        params: { page: 1, page_size: 50, keyword: keyword.trim() || undefined },
      })
      // 后端把工作区所有者(OWNER)放在 owner 字段单独返回且不参与 keyword 过滤，
      // 这里合并进候选列表，并对 owner 做本地关键词匹配
      const keywordLower = keyword.trim().toLowerCase()
      const selfId = String(authStore.user?.id || '')
      const candidates: any[] = []
      const owner = res.data?.owner
      if (owner && String(owner.user_id || '') !== selfId) {
        const ownerName = String(owner.display_name || '').toLowerCase()
        const ownerEmail = String(owner.email || '').toLowerCase()
        if (!keywordLower || ownerName.includes(keywordLower) || ownerEmail.includes(keywordLower)) {
          candidates.push(owner)
        }
      }
      for (const item of (res.data?.items || [])) {
        if (String(item.user_id || '') !== selfId) candidates.push(item)
      }
      return candidates.map((item) => ({
        user_id: String(item.user_id || ''),
        display_name: String(item.display_name || item.email || 'Member'),
        avatar_url: item.avatar_url || null,
        avatar_svg: item.avatar_svg || null,
        is_expert: Boolean(item.is_expert),
      }))
    } catch (e) {
      console.warn('Failed to search workspace members', e)
      return []
    }
  }

  return {
    activePreInput,
    preInputIsCollecting,
    isPreInputCreator,
    myPreInputParticipation,
    canEditPreInputShared,
    startPreInput,
    editPreInputDocument,
    replacePreInputSpan,
    markPreInputDone,
    submitPreInputManually,
    cancelPreInput,
    searchPreInputMembers,
    loadActive,
    handleEvent,
    reset,
  }
}
