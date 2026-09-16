import { computed, ref } from 'vue'
import api from '@/utils/api'

export interface ChatSubmission {
  id?: string
  task_id: string
  client_message_id: string
  content: string
  status: string
  creator_id?: string
  version?: number
  chat_message_id?: string | null
  ai_job_id?: string | null
  error_message?: string | null
  created_at?: string
  metadata?: Record<string, any>
}

const rank: Record<string, number> = { SENDING: 0, UNKNOWN: 0, PREPARING: 1, EXECUTING: 2, FAILED: 3, SUCCEEDED: 4 }

/** Task-scoped receipts survive route switches; REST is also available without a WS. */
export function useChatSubmissions(options: {
  workspaceId: () => string
  taskId: () => string
  userId: () => string
}) {
  const receipts = ref<Record<string, ChatSubmission>>({})
  const storageKey = `traceforge.chat-submissions:${options.userId()}`
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey) || '{}')
    for (const [id, row] of Object.entries(saved)) {
      const item = row as ChatSubmission
      if (item?.task_id && item.client_message_id && typeof item.content === 'string') {
        receipts.value[id] = { ...item, status: 'UNKNOWN', version: 0 }
      }
    }
  } catch { /* Storage is optional; durable receipts still recover through REST. */ }
  const persistUnconfirmed = () => {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(Object.fromEntries(Object.entries(receipts.value)
        .filter(([, row]) => ['SENDING', 'UNKNOWN'].includes(row.status)))))
    } catch { /* A full or disabled session store must not fail a send. */ }
  }
  const invalidated = new Set<string>()
  const provisional = new Set<string>()
  const revisions = new Map<string, number>()
  const key = (task: string, client: string) => `${options.workspaceId()}:${task}:${client}`
  const current = computed(() => Object.values(receipts.value).filter(row => row.task_id === options.taskId()
    && receipts.value[key(row.task_id, row.client_message_id)] === row))
  const busy = computed(() => current.value.some(row => ['SENDING', 'UNKNOWN', 'PREPARING', 'EXECUTING'].includes(row.status)))
  /** Unconfirmed idempotency keys (SENDING/UNKNOWN) for recovery snapshots. */
  const unconfirmedKeys = (): string[] => current.value
    .filter(row => ['SENDING', 'UNKNOWN'].includes(row.status))
    .map(row => row.client_message_id)
  const put = (row: ChatSubmission) => {
    const identity = key(row.task_id, row.client_message_id)
    if (invalidated.has(identity)) return
    const old = receipts.value[identity]
    // Server receipts carry a monotonically increasing version; a stale or
    // out-of-order update never downgrades applied state. Rank remains the
    // fallback for locally seeded rows that have no version yet.
    if (old) {
      const oldVersion = Number(old.version || 0)
      const nextVersion = Number(row.version || 0)
      if (oldVersion > 0 || nextVersion > 0) {
        if (nextVersion < oldVersion) return
      } else if ((rank[old.status] ?? 0) > (rank[row.status] ?? 0)) return
    }
    receipts.value[identity] = { ...old, ...row }
    if (['SENDING', 'UNKNOWN', 'PREPARING', 'EXECUTING'].includes(row.status)) provisional.add(identity)
    persistUnconfirmed()
  }
  const send = async (taskId: string, clientId: string, content: string, metadata?: Record<string, any>) => {
    const workspace = options.workspaceId()
    put({ task_id: taskId, client_message_id: clientId, content, metadata, status: 'SENDING',
      creator_id: options.userId(), created_at: new Date().toISOString() })
    try {
      const { data } = await api.post(`/workspaces/${workspace}/tasks/${taskId}/chat-submissions`, {
        client_message_id: clientId, content, metadata,
      })
      if (options.workspaceId() === workspace) put(data)
      return true
    } catch (error: any) {
      if (options.workspaceId() !== workspace) return false
      const row = receipts.value[key(taskId, clientId)]
      if (row?.id) return true // A server receipt received over WS takes precedence.
      const status = error.response?.status
      const definitive = status >= 400 && status < 500 && ![408, 429].includes(status)
      put({ ...row!, status: definitive ? 'FAILED' : 'UNKNOWN',
        error_message: definitive ? (error.response?.data?.detail?.message || '消息未被接收，请重试') : '正在确认发送结果，请勿重复发送' })
      // Keep an ambiguous send in its recoverable bubble, rather than leaving
      // the same prompt in the composer to be sent again under a new key.
      return !definitive
    }
  }
  const clear = (taskId: string) => {
    revisions.set(taskId, (revisions.get(taskId) || 0) + 1)
    for (const [id, row] of Object.entries(receipts.value)) if (row.task_id === taskId) {
      invalidated.add(id)
      delete receipts.value[id]
    }
    persistUnconfirmed()
  }
  const removeMessages = (taskId: string, messageIds: Set<string>) => {
    revisions.set(taskId, (revisions.get(taskId) || 0) + 1)
    for (const [id, row] of Object.entries(receipts.value)) if (row.task_id === taskId && row.chat_message_id && messageIds.has(row.chat_message_id)) {
      invalidated.add(id)
      delete receipts.value[id]
    }
    persistUnconfirmed()
  }
  const bubbles = (messages: any[], creatorMeta?: Record<string, any>) => {
    const mapped = messages.map(message => {
      const row = current.value.find(item => item.chat_message_id === message.id)
      if (row) provisional.delete(key(row.task_id, row.client_message_id))
      return row ? { ...message, delivery_status: row.status.toLowerCase(), delivery_error: row.error_message } : message
    })
    for (const row of current.value) {
      const awaitingHistory = provisional.has(key(row.task_id, row.client_message_id))
      if ((row.status === 'SUCCEEDED' && !awaitingHistory)
        || (row.status === 'FAILED' && row.chat_message_id && !awaitingHistory)
        || mapped.some(message => message.id === row.chat_message_id
        || message.client_message_id === row.client_message_id)) continue
      // The pending bubble must render exactly like the eventual server message:
      // creator profile decides the expert badge/avatar, metadata decides the body.
      const creator = creatorMeta && String(row.creator_id || '') === options.userId() ? creatorMeta : null
      mapped.push({ id: `submission-${row.client_message_id}`, role: 'user', content: row.content,
        client_message_id: row.client_message_id, creator_id: row.creator_id, created_at: row.created_at,
        message_type: 'text', can_undo: false, metadata: row.metadata || null,
        delivery_status: row.status.toLowerCase(), delivery_error: row.error_message,
        ...(creator || {}) })
    }
    return mapped
  }
  return { current, busy, put, send, clear, removeMessages, bubbles, unconfirmedKeys }
}
