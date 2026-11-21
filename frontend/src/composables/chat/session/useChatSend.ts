import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { generateClientMessageId } from '../shared/messageIdentity'
import type { HitlCard } from '../types'
import type { AgentModelSelection } from '@/composables/useAgentModels'
import type { useChatSubmissions } from '@/composables/useChatSubmissions'
import type { ContextAnnotations } from '../annotations/useContextAnnotations'
import { formatAnnotationMessage } from '../annotations/contextAnnotations'

/**
 * 消息发送（composer）：普通输入、HITL 回复、快捷验证三种入口共用
 * 普通消息和中断恢复共用持久回执，HITL 回复走 WebSocket 确认通道。
 */
export function useChatSend(options: {
  getSteeringJobId?: () => string
  agentSessionSendBlocked?: () => boolean
  replacingAgentSession?: () => boolean
  onAgentSessionAccepted?: () => void
  annotations?: ContextAnnotations
  collaborationBlocked?: () => boolean
  getSubmissionMetadata?: () => Record<string, unknown>
  getModelSelection?: () => AgentModelSelection | undefined
  onModelSubmitted?: (value?: AgentModelSelection) => void
  resourceBlocked?: () => boolean
  suggestionOnly?: () => boolean
  getWorkspaceId: () => string
  getTaskId: () => string
  task: {
    getCurrentTask: () => any
    isTaskPreStart: { value: boolean }
    isTaskProvisioning: { value: boolean }
    isTaskInterrupted: { value: boolean }
    isTerminalStatus: { value: boolean }
  }
  submissions: {
    busy: { value: boolean }
    send: ReturnType<typeof useChatSubmissions>['send']
    current: { value: any[] }
  }
  messages: {
    upsert: (message: any) => void
  }
  noteSentTime: (clientMessageId: string) => void
  findHitlCard: (cardId: string) => HitlCard | undefined
  getPendingConfirmation?: () => HitlCard | undefined
  engine: {
    engineRunning: { value: boolean }
  }
  ws: {
    isOpen: () => boolean
    sendFrame: (type: string, payload: Record<string, any>) => boolean
    connect: (taskId: string) => void
  }
  recoverSession: (reason: string) => Promise<boolean>
  isUndoing: () => boolean
  isInitializing?: () => boolean
  isHistoryAnchored: () => boolean
  returnToLatest: () => Promise<void>
  getCreatorMeta: () => Record<string, any>
  scrollTo: (target: 'chat') => void
}) {
  const { t } = useI18n()

  const chatInput = ref('')
  const sendingChat = ref(false)
  let unconfirmedSteering: { jobId: string; taskId: string; content: string; clientMessageId: string } | undefined
  const chatInputPlaceholder = computed(() => {
    if (!options.suggestionOnly?.() && options.resourceBlocked?.()) return '本地资源未连接，恢复在线后可发送消息'
    if (options.suggestionOnly?.()) return '输入建议，提交后由任务创建者采纳'
    if (options.task.isTaskProvisioning.value) return t('chat.task_provisioning_hint')
    if (options.task.isTaskPreStart.value) return t('chat.start_before_chat')
    if (options.task.isTerminalStatus.value) return t('chat.terminal_status_hint')
    if (options.task.isTaskInterrupted.value) return t('chat.resume_interrupted_placeholder')
    return t('dashboard.desc_placeholder')
  })

  const releaseSendingChatSoon = () => {
    window.setTimeout(() => {
      sendingChat.value = false
    }, 250)
  }

  const sendChatContent = async (
    content: string,
    sendOptions: { displayContent?: string; metadata?: Record<string, any> } = {},
  ): Promise<boolean> => {
    if (options.isInitializing?.()) return false
    if (options.task.isTerminalStatus.value || options.task.isTaskProvisioning.value) return false
    const confirmation = options.task.getCurrentTask()?.status === 'AWAITING_INPUT' ? options.getPendingConfirmation?.() : undefined
    if (confirmation && !sendOptions.metadata?.interaction_id) {
      sendOptions = { ...sendOptions, metadata: { ...sendOptions.metadata,
        interaction_id: confirmation.interaction_id, reply_to_message_id: confirmation.message_id,
        confirmation_value: content, job_id: confirmation.job_id } }
    }
    const confirmationReply = Boolean(sendOptions.metadata?.interaction_id || sendOptions.metadata?.reply_to_message_id)
    if (!confirmationReply && options.collaborationBlocked?.()) {
      ElMessage.warning(t('collaboration.blocked'))
      return false
    }
    if (!options.suggestionOnly?.() && options.resourceBlocked?.()) {
      ElMessage.warning('本地资源未连接，恢复在线后才能操作')
      return false
    }
    if (options.suggestionOnly?.()) {
      if (confirmationReply) { ElMessage.warning('本地任务仅创建者或专家可以处理确认'); return false }
      if (sendingChat.value || !content.trim()) return false
      sendingChat.value = true
      try {
        await api.post(`/workspaces/${options.getWorkspaceId()}/tasks/${options.getTaskId()}/member-suggestions`, { content: content.trim(), client_submission_id: generateClientMessageId() })
        ElMessage.success('建议已提交给任务创建者')
        return true
      } catch (e) { ElMessage.error(formatApiError(e, '提交建议失败')); return false }
      finally { sendingChat.value = false }
    }
    if (options.task.isTaskPreStart.value) {
      ElMessage.warning(t('chat.start_before_chat'))
      return false
    }
    if (sendingChat.value || options.isUndoing()) return false
    if (!confirmationReply && options.submissions.busy.value && (
      !options.task.isTaskInterrupted.value
      || options.submissions.current.value.some(row => ['SENDING', 'UNKNOWN', 'PREPARING'].includes(row.status))
    )) return false
    const normalized = String(content || '').trim()
    if (!normalized) return false
    const targetTaskId = options.getTaskId()
    const targetWorkspaceId = options.getWorkspaceId()
    if (options.isHistoryAnchored()) await options.returnToLatest()
    if (options.getTaskId() !== targetTaskId || options.getWorkspaceId() !== targetWorkspaceId) return false
    if (confirmationReply && options.task.isTaskInterrupted.value) return false
    if (!confirmationReply && options.agentSessionSendBlocked?.()) return false
    const newAgentSession = options.replacingAgentSession?.() || undefined
    const displayContent = String(sendOptions.displayContent || normalized).trim()
    const clientMessageId = generateClientMessageId()
    const modelSelection = options.getModelSelection?.()
    if (!confirmationReply) sendOptions = { ...sendOptions, metadata: { ...sendOptions.metadata, ...options.getSubmissionMetadata?.() } }
    if (modelSelection && !confirmationReply) {
      sendOptions = { ...sendOptions, metadata: { ...sendOptions.metadata, agent_model: modelSelection } }
    }
    options.noteSentTime(clientMessageId)
    sendingChat.value = true
    const taskId = options.getTaskId()
    if (!confirmationReply && taskId) {
      try {
        // POST 回执直接应用；后续状态由 outbox 事件（chat_submission_update）驱动。
        const submission = options.task.isTaskInterrupted.value
          ? options.submissions.send(taskId, clientMessageId, normalized, sendOptions.metadata, newAgentSession, true)
          : newAgentSession
            ? options.submissions.send(taskId, clientMessageId, normalized, sendOptions.metadata, true)
            : options.submissions.send(taskId, clientMessageId, normalized, sendOptions.metadata)
        options.scrollTo('chat')
        const accepted = await submission
        if (accepted && options.getTaskId() === taskId) options.onAgentSessionAccepted?.()
        if (accepted) options.onModelSubmitted?.(modelSelection)
        if (options.getTaskId() === taskId && accepted) options.scrollTo('chat')
        if (options.getTaskId() === taskId && options.getWorkspaceId() === targetWorkspaceId
          && options.submissions.current.value.some((row: any) =>
          row.client_message_id === clientMessageId && row.creator_id === options.getCreatorMeta().creator_id
          && row.status === 'UNKNOWN')) {
          void options.recoverSession('send-unknown')
        }
        return accepted
      } finally {
        sendingChat.value = false
      }
    }
    if (!options.ws.isOpen()) {
      if (taskId) options.ws.connect(taskId)
      sendingChat.value = false
      return false
    }

    // 显示到本地对话气泡
    options.messages.upsert({
      id: `local-${clientMessageId}`,
      role: 'user',
      content: displayContent,
      created_at: new Date().toISOString(),
      message_type: 'text',
      client_message_id: clientMessageId,
      delivery_status: 'sending',
      ...options.getCreatorMeta(),
      metadata: sendOptions.metadata || null,
    })

    // 通过 WebSocket 发送给后端 → CLI 引擎
    try {
      options.ws.sendFrame('chat_message', {
        role: 'user',
        content: normalized,
        client_message_id: clientMessageId,
        metadata: sendOptions.metadata || undefined,
      })
      options.engine.engineRunning.value = true
      if (!options.isHistoryAnchored()) options.scrollTo('chat')
      return true
    } finally {
      releaseSendingChatSoon()
    }
  }

  const sendSteeringContent = async (jobId: string, content: string): Promise<boolean> => {
    const taskId = options.getTaskId()
    const workspaceId = options.getWorkspaceId()
    if (!content.trim() || !taskId || sendingChat.value || options.isUndoing()
      || options.collaborationBlocked?.() || options.agentSessionSendBlocked?.()) return false
    if (options.isHistoryAnchored()) await options.returnToLatest()
    if (options.getTaskId() !== taskId || options.getWorkspaceId() !== workspaceId) return false
    if (jobId !== options.getSteeringJobId?.()) {
      ElMessage.warning(t('chat.steering.run_changed'))
      return false
    }
    const previous = unconfirmedSteering
    const clientMessageId = previous?.jobId === jobId && previous.taskId === taskId && previous.content === content
      ? previous.clientMessageId : generateClientMessageId()
    const revision = options.task.getCurrentTask()?.session_revision
    unconfirmedSteering = { jobId, taskId, content, clientMessageId }
    options.noteSentTime(clientMessageId)
    sendingChat.value = true
    try {
      const { data } = await api.post(`/workspaces/${workspaceId}/tasks/${taskId}/chat-steering`, {
        content, job_id: jobId, client_message_id: clientMessageId,
      })
      unconfirmedSteering = undefined
      if (options.getTaskId() === taskId && options.getWorkspaceId() === workspaceId
        && options.task.getCurrentTask()?.session_revision === revision) {
        options.messages.upsert({ ...data, streaming: false, delivery_status: 'sent' })
        if (!options.isHistoryAnchored()) options.scrollTo('chat')
      }
      return true
    } catch (error) {
      const response = (error as { response?: { status?: number } })?.response
      if (response?.status && response.status < 500) unconfirmedSteering = undefined
      if (options.getTaskId() === taskId && options.getWorkspaceId() === workspaceId) {
        ElMessage.error(formatApiError(error, t('chat.steering.send_failed'), t))
        if (unconfirmedSteering) void options.recoverSession('steering-unknown')
      }
      return false
    } finally {
      sendingChat.value = false
    }
  }

  const sendComposer = async (steeringJobId?: string) => {
    const annotations = options.replacingAgentSession?.() ? undefined : options.annotations?.snapshot()
    if (!chatInput.value.trim() && !annotations?.items.length) return
    const content = chatInput.value
    const taskId = options.getTaskId()
    // The submission bubble owns this text during the request. Clearing now
    // also prevents a slow response from carrying the sent prompt into another task.
    chatInput.value = ''
    const prompt = formatAnnotationMessage(content, annotations?.items || [])
    const sent = steeringJobId ? await sendSteeringContent(steeringJobId, prompt) : await sendChatContent(prompt)
    if (sent && annotations) options.annotations?.consume(annotations)
    if (!sent && options.getTaskId() === taskId && !chatInput.value) {
      chatInput.value = content
    }
  }

  const submitHitl = async (cardId: string, response: string) => {
    if (!response || options.isUndoing()) return
    const card = options.findHitlCard(cardId)
    if (!card) return
    await sendChatContent(response, {
      displayContent: response,
      metadata: {
        reply_to_message_id: card?.message_id,
        interaction_id: card?.interaction_id,
        confirmation_value: response,
        job_id: card?.job_id || undefined,
      },
    })
  }

  // ─── 执行高阶 MCP 验证 ───
  const sendVerification = async (type: 'ui' | 'api' | 'e2e') => {
    let prompt = ''
    if (type === 'ui') {
      prompt = t('chat.verification_prompt_ui')
    } else if (type === 'api') {
      prompt = t('chat.verification_prompt_api')
    } else if (type === 'e2e') {
      prompt = t('chat.verification_prompt_e2e')
    }
    if (options.task.isTaskInterrupted.value) {
      await sendChatContent(prompt)
      return
    }
    if (!options.ws.isOpen()) {
      const taskId = options.getTaskId()
      if (taskId) options.ws.connect(taskId)
      return
    }

    await sendChatContent(prompt, {
      displayContent: `[${t('chat.verification_tag')}] ${prompt}`,
    })
  }

  return {
    chatInput,
    sendingChat,
    chatInputPlaceholder,
    sendChat: () => sendComposer(),
    sendSteeringChat: (jobId: string) => sendComposer(jobId),
    sendSteeringContent,
    sendChatContent,
    submitHitl,
    sendVerification,
  }
}
