import { computed, ref } from 'vue'
import type { useChatSubmissions } from '@/composables/useChatSubmissions'
import type { useChatMessageContext } from '@/composables/useChatMessageContext'
import { dedupeMessages, messageIdentity } from '../shared/messageIdentity'

type Submissions = ReturnType<typeof useChatSubmissions>
type HistoryContext = ReturnType<typeof useChatMessageContext>

/**
 * 对话气泡存储（仅自然语言 user/assistant 文本与结果卡片消息）。
 * 去重、历史页合并、本地发送时间固定都在这里收敛；
 * 发送回执气泡的拼装仍由 useChatSubmissions.bubbles 提供。
 */
export function useChatMessages(options: {
  submissions: Submissions
  historyContext: HistoryContext
  getWorkspaceId: () => string
  getCreatorMeta: () => Record<string, any>
}) {
  const { submissions, historyContext } = options

  const messages = ref<any[]>([])

  // 服务端落库时间可能比本地发送晚数秒；本次会话内按发送时刻固定显示，避免气泡时间跳变
  const localSentTimes = new Map<string, string>()

  const visibleMessages = computed(() => submissions.bubbles(messages.value, options.getCreatorMeta())
    .map((message: any) => {
      const clientId = String(message?.client_message_id || '')
      const sentAt = clientId ? localSentTimes.get(clientId) : undefined
      return sentAt && sentAt !== message.created_at ? { ...message, created_at: sentAt } : message
    }))

  const noteSentTime = (clientMessageId: string) => {
    localSentTimes.set(clientMessageId, new Date().toISOString())
  }

  const reset = () => {
    messages.value = []
  }

  const replaceAll = (items: any[]) => {
    messages.value = items
  }

  const findById = (messageId: string) => messages.value.find(item => String(item.id || '') === String(messageId || ''))

  const findByIdentity = (identity: string) => messages.value.find(item => messageIdentity(item) === identity)

  const removeByIds = (removedIds: Set<string>) => {
    messages.value = messages.value.filter(item => !removedIds.has(String(item.id)))
  }

  /** 请求发起「之前」捕获身份 → 对象引用快照，供 reset 合并时识别请求期间的新增消息。 */
  const captureIdentitySnapshot = () => new Map(messages.value.map(item => [messageIdentity(item), item]))

  /** 历史页合并：reset 时保留请求期间新增的本地消息，追加页向上 prepend 并整体去重。 */
  const applyHistoryPage = (mapped: any[], reset: boolean, snapshot?: Map<string, any>) => {
    if (reset) {
      const initialMessages = snapshot ?? captureIdentitySnapshot()
      const duringRequest = messages.value.filter(item => initialMessages.get(messageIdentity(item)) !== item)
      messages.value = dedupeMessages([...mapped, ...duringRequest])
      return
    }
    messages.value = dedupeMessages([...mapped, ...messages.value])
  }

  /** 锚点上下文方向加载：before 向前拼接，after 向后拼接。 */
  const appendPage = (mapped: any[], direction: 'before' | 'after') => {
    messages.value = dedupeMessages(direction === 'before' ? [...mapped, ...messages.value] : [...messages.value, ...mapped])
  }

  const upsert = (item: any) => {
    if (historyContext.anchored.value && !messages.value.some(m => messageIdentity(m) === messageIdentity(item))) {
      historyContext.hasNew.value = true
      return
    }
    const key = messageIdentity(item)
    if (!key) {
      messages.value.push(item)
      return
    }
    const index = messages.value.findIndex(existing => messageIdentity(existing) === key)
    if (index >= 0) {
      const merged = {
        ...messages.value[index],
        ...item,
      }
      // 定位结果卡片更新时把它移到会话末尾，确保最新结果展示在最后一次返回上
      if (String(item.message_type || item.type || '') === 'diagnosis_result') {
        messages.value.splice(index, 1)
        messages.value.push(merged)
        return
      }
      messages.value[index] = merged
      return
    }
    messages.value.push(item)
  }

  return {
    messages,
    visibleMessages,
    noteSentTime,
    reset,
    replaceAll,
    findById,
    findByIdentity,
    removeByIds,
    captureIdentitySnapshot,
    applyHistoryPage,
    appendPage,
    upsert,
  }
}
