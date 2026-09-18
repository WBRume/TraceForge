import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { generateClientMessageId } from '../shared/messageIdentity'
import { createResolveActionError } from '../shared/requestGuards'
import type { HitlCard } from '../types'

/**
 * 消息发送（composer）：普通输入、HITL 回复、快捷验证三种入口共用
 * sendChatContent 的三通道分发——
 * 1. 常规任务 → REST 提交（submissions，后续由 outbox 事件驱动）；
 * 2. 中断任务 → resume-interrupted 接口恢复执行；
 * 3. 其余 → WebSocket 直发。
 */
export function useChatSend(options: {
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
    send: (taskId: string, clientMessageId: string, content: string, metadata?: Record<string, any>) => Promise<boolean>
    current: { value: any[] }
  }
  messages: {
    upsert: (message: any) => void
  }
  noteSentTime: (clientMessageId: string) => void
  findHitlCard: (cardId: string) => HitlCard | undefined
  engine: {
    engineRunning: { value: boolean }
  }
  ws: {
    isOpen: () => boolean
    sendFrame: (type: string, payload: Record<string, any>) => boolean
    connect: (taskId: string) => void
  }
  recoverSession: (reason: string) => Promise<boolean>
  resumeInterruptedTask: (taskId: string, resumeOptions: { prompt?: string; clientMessageId?: string }) => Promise<any>
  applyTaskSessionPayload: (payload: any) => void
  isUndoing: () => boolean
  isHistoryAnchored: () => boolean
  returnToLatest: () => Promise<void>
  getCreatorMeta: () => Record<string, any>
  scrollTo: (target: 'chat') => void
  resolveActionError: ReturnType<typeof createResolveActionError>
}) {
  const { t } = useI18n()

  const chatInput = ref('')
  const sendingChat = ref(false)

  const chatInputPlaceholder = computed(() => {
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
    if (options.task.isTaskPreStart.value) {
      ElMessage.warning(t('chat.start_before_chat'))
      return false
    }
    if (sendingChat.value || options.isUndoing()) return false
    if (!sendOptions.metadata?.interaction_id && options.submissions.busy.value) return false
    const normalized = String(content || '').trim()
    if (!normalized) return false
    if (options.isHistoryAnchored()) await options.returnToLatest()
    const displayContent = String(sendOptions.displayContent || normalized).trim()
    const clientMessageId = generateClientMessageId()
    options.noteSentTime(clientMessageId)
    sendingChat.value = true
    const taskId = options.getTaskId()
    if (!options.task.isTaskInterrupted.value && !sendOptions.metadata?.interaction_id && taskId) {
      try {
        // POST 回执直接应用；后续状态由 outbox 事件（chat_submission_update）驱动。
        const accepted = await options.submissions.send(taskId, clientMessageId, normalized, sendOptions.metadata)
        if (options.getTaskId() === taskId && accepted) options.scrollTo('chat')
        if (!accepted && options.submissions.current.value.some((row: any) =>
          row.client_message_id === clientMessageId && row.status === 'UNKNOWN')) {
          void options.recoverSession('send-unknown')
        }
        return accepted
      } finally {
        sendingChat.value = false
      }
    }
    if (options.task.isTaskInterrupted.value && taskId) {
      try {
        const payload = await options.resumeInterruptedTask(taskId, {
          prompt: normalized,
          clientMessageId,
        })
        options.messages.upsert({
          id: `local-${clientMessageId}`,
          role: 'user',
          content: displayContent,
          created_at: new Date().toISOString(),
          message_type: 'text',
          client_message_id: clientMessageId,
          delivery_status: 'sent',
          ...options.getCreatorMeta(),
          metadata: sendOptions.metadata || null,
        })
        options.applyTaskSessionPayload(payload)
        options.engine.engineRunning.value = true
        if (!options.isHistoryAnchored()) options.scrollTo('chat')
        return true
      } catch (e) {
        console.error('Resume interrupted task failed', e)
        ElMessage.error(options.resolveActionError(e, 'chat.errors.resume_interrupted_failed', 'chat.errors.no_permission_start_task'))
        return false
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

  const sendChat = async () => {
    if (!chatInput.value.trim()) return
    const content = chatInput.value
    const taskId = options.getTaskId()
    // The submission bubble owns this text during the request. Clearing now
    // also prevents a slow response from carrying the sent prompt into another task.
    chatInput.value = ''
    const sent = await sendChatContent(content)
    if (!sent && options.getTaskId() === taskId && !chatInput.value) {
      chatInput.value = content
    }
  }

  const submitHitl = async (cardId: string, response: string) => {
    if (!response || options.isUndoing()) return
    const card = options.findHitlCard(cardId)
    const sent = await sendChatContent(response, {
      displayContent: response,
      metadata: {
        reply_to_message_id: card?.message_id,
        interaction_id: card?.interaction_id,
        confirmation_value: response,
        job_id: card?.job_id || undefined,
      },
    })
    if (sent && card) {
      card.answered = true
      card.answer = response
    }
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
    sendChat,
    sendChatContent,
    submitHitl,
    sendVerification,
  }
}
