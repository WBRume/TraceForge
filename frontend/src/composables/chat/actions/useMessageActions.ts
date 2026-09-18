import { computed } from 'vue'
import { nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { generateClientMessageId } from '../shared/messageIdentity'
import type { ChatDecisionPayload } from '@/composables/useChatDecision'

/**
 * 消息级动作：撤销用户消息（回滚会话轮次）与标记决策（气泡内 Popover 提交）。
 */
export function useMessageActions(options: {
  getCurrentTask: () => any
  canManageTaskStatus: { value: boolean }
  getWorkspaceId: () => string
  undoingMessageId: { value: string }
  sendingChat: () => boolean
  submissions: {
    current: () => any[]
    removeMessages: (taskId: string, messageIds: Set<string>) => void
  }
  messages: {
    removeByIds: (ids: Set<string>) => void
    findById: (messageId: string) => any
  }
  terminalLogsClear: () => void
  cardsClear: () => void
  engineRunning: { value: boolean }
  engineResetThinking: () => void
  jobsReset: () => void
  bumpHistoryGeneration: () => void
  loadHistory: (taskId: string, reset?: boolean) => Promise<void>
  undoTaskMessage: (taskId: string, messageId: string, undoOptions: { operationId: string }) => Promise<any>
  restoreComposer: (content: string) => void
  scheduleContextWindowRefresh: () => void
  resolveActionError: (error: unknown, fallbackKey: string, noPermissionKey: string) => string
  markMessageAsDecision: (workspaceId: string, taskId: string, messageId: string, payload: ChatDecisionPayload) => Promise<any | null>
  decisionError: { value: string | null }
}) {
  const { t } = useI18n()

  const isUndoing = computed(() => Boolean(options.undoingMessageId.value))

  const canMarkMessageAsDecision = (msg: any): boolean => {
    if (String(msg?.id || '').startsWith('submission-')) return false
    if (msg?.metadata?.submission_id && msg.metadata.knowledge_state !== 'published') return false
    const id = String(msg?.id || '').trim()
    if (!id || id.startsWith('local-')) return false
    if (!options.getCurrentTask()?.id || !options.canManageTaskStatus.value) return false
    if (msg?.decision_id) return false
    if (msg?.message_type === 'init_reason') return false
    if (String(msg?.role || '').toLowerCase() !== 'user') return false
    return Boolean(String(msg?.content || '').trim())
  }

  const canUndoMessage = (msg: any): boolean => {
    const id = String(msg?.id || '').trim()
    if (!id || id.startsWith('local-')) return false
    if (!options.getCurrentTask()?.id || !options.canManageTaskStatus.value || options.sendingChat()) return false
    if (options.submissions.current().some(row => ['SENDING', 'UNKNOWN', 'PREPARING'].includes(row.status))) return false
    if (String(msg?.role || '').toLowerCase() !== 'user') return false
    if (msg?.decision_id || msg?.message_type === 'init_reason') return false
    if (!msg?.session_turn_id || !String(msg?.content || '')) return false
    const currentGeneration = Number(options.getCurrentTask()?.session_generation || 0)
    if (!currentGeneration || Number(msg?.session_generation || 0) !== currentGeneration) return false
    return msg?.can_undo !== false
  }

  const undoMessage = async (msg: any): Promise<boolean> => {
    if (!canUndoMessage(msg) || !options.getCurrentTask()?.id) return false
    const messageId = String(msg.id)
    options.undoingMessageId.value = messageId
    try {
      const payload = await options.undoTaskMessage(
        options.getCurrentTask().id,
        messageId,
        { operationId: generateClientMessageId() },
      )
      const removedIds = new Set<string>(
        (Array.isArray(payload?.removed_message_ids) ? payload.removed_message_ids : []).map((id: any) => String(id)),
      )
      removedIds.add(messageId)
      options.bumpHistoryGeneration()
      options.submissions.removeMessages(String(options.getCurrentTask().id), removedIds)
      options.messages.removeByIds(removedIds)
      options.terminalLogsClear()
      options.jobsReset()
      options.cardsClear()
      options.engineResetThinking()
      options.engineRunning.value = false
      if (options.getCurrentTask()) {
        options.getCurrentTask().status = 'CODING'
        options.getCurrentTask().session_generation = Number(payload?.session_generation || options.getCurrentTask().session_generation || 0)
      }
      options.restoreComposer(String(payload?.restored_content ?? msg.content ?? ''))
      await nextTick()
      document.querySelector<HTMLTextAreaElement>('.card-textarea')?.focus()
      if (options.getCurrentTask()?.id) {
        await options.loadHistory(options.getCurrentTask().id, true)
      }
      ElMessage.success(t('chat.undo.success'))
      options.scheduleContextWindowRefresh()
      return true
    } catch (e: any) {
      console.error('Undo task message failed', e)
      ElMessage.error(options.resolveActionError(e, 'chat.undo.failed', 'chat.undo.failed'))
      return false
    } finally {
      options.undoingMessageId.value = ''
    }
  }

  /**
   * 标记决策：由气泡内的 DecisionMarkPopover 直接提交（消息 id 显式传入）。
   */
  const submitMessageDecision = async (messageId: string, payload: ChatDecisionPayload): Promise<boolean> => {
    const task = options.getCurrentTask()
    if (!task?.id || !messageId) return false
    const result = await options.markMessageAsDecision(
      options.getWorkspaceId(),
      String(task.id),
      String(messageId),
      payload,
    )
    if (!result) {
      ElMessage.error(options.decisionError.value || t('chat.decision.save_failed'))
      return false
    }
    const target = options.messages.findById(messageId)
    if (target) target.decision_id = result.id
    ElMessage.success(t('chat.decision.saved'))
    options.scheduleContextWindowRefresh()
    return true
  }

  return {
    isUndoing,
    canMarkMessageAsDecision,
    canUndoMessage,
    undoMessage,
    submitMessageDecision,
  }
}
