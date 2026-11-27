import { computed, ref } from 'vue'
import api from '@/utils/api'
import { noteTaskRunInitiated, forgetTaskRunIntent } from '@/utils/taskAwarenessIntent'
import { messageIdentity } from './chat/shared/messageIdentity'
import type { useTaskSessionControls } from './useTaskSessionControls'
import type { ChatImageReference } from './chat/session/useChatImageDraft'

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
  new_agent_session?: boolean
  resume_interrupted?: boolean
}

const rank: Record<string, number> = { SENDING: 0, UNKNOWN: 0, PREPARING: 1, EXECUTING: 2, FAILED: 3, SUCCEEDED: 4 }

/** Task-scoped receipts survive route switches; REST is also available without a WS. */
export function useChatSubmissions(options: {
  workspaceId: () => string
  taskId: () => string
  userId: () => string
  resumeInterruptedTask: ReturnType<typeof useTaskSessionControls>['resumeInterruptedTask']
  onAgentSessionUnavailable?: (taskId: string) => void
  onAgentSessionChanged?: (taskId: string) => void
}) {
  const receipts = ref<Record<string, ChatSubmission>>({})
  const storageKey = `traceforge.chat-submissions:${options.userId()}`
  const key = (task: string, client: string, creator = options.userId(), workspace = options.workspaceId()) =>
    `${workspace}:${task}:${creator}:${client}`
  const readUnconfirmed = (): Record<string, ChatSubmission> => {
    try {
      const saved = JSON.parse(sessionStorage.getItem(storageKey) || '{}')
      const normalized: Record<string, ChatSubmission> = {}
      if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
        for (const [id, item] of Object.entries<ChatSubmission>(saved)) {
          if (!item?.task_id || !item.client_message_id || typeof item.content !== 'string') continue
          const workspace = id.split(':', 1)[0]
          const creator = item.creator_id || options.userId()
          normalized[key(item.task_id, item.client_message_id, creator, workspace)] = { ...item, creator_id: creator }
        }
      }
      return normalized
    } catch { /* Storage is optional; durable receipts still recover through REST. */ }
    return {}
  }
  for (const [identity, item] of Object.entries(readUnconfirmed())) {
    receipts.value[identity] = { ...item, status: 'UNKNOWN', version: 0 }
  }
  const persistUnconfirmed = (identities: string[]) => {
    if (!identities.length) return
    try {
      // A retired view can still complete an earlier POST while the new view has pending sends.
      const saved = readUnconfirmed()
      let changed = false
      for (const identity of identities) {
        const row = receipts.value[identity]
        if (row && ['SENDING', 'UNKNOWN'].includes(row.status)) {
          saved[identity] = row
          changed = true
        } else if (Object.prototype.hasOwnProperty.call(saved, identity)) {
          delete saved[identity]
          changed = true
        }
      }
      if (changed) sessionStorage.setItem(storageKey, JSON.stringify(saved))
    } catch { /* A full or disabled session store must not fail a send. */ }
  }
  const invalidated = new Set<string>()
  const provisional = new Set<string>()
  const keyForReceipt = (row: ChatSubmission, workspace = options.workspaceId()) =>
    key(row.task_id, row.client_message_id, row.creator_id || options.userId(), workspace)
  const current = computed(() => Object.values(receipts.value).filter(row => row.task_id === options.taskId()
    && receipts.value[keyForReceipt(row)] === row))
  const busy = computed(() => current.value.some(row => ['SENDING', 'UNKNOWN', 'PREPARING', 'EXECUTING'].includes(row.status)))
  /** Unconfirmed idempotency keys (SENDING/UNKNOWN) for recovery snapshots. */
  const unconfirmedKeys = (): string[] => current.value
    .filter(row => row.creator_id === options.userId() && ['SENDING', 'UNKNOWN'].includes(row.status))
    .map(row => row.client_message_id)
  const put = (row: ChatSubmission, workspace = options.workspaceId()) => {
    const identity = keyForReceipt(row, workspace)
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
    receipts.value[identity] = { ...old, ...row, creator_id: row.creator_id || options.userId() }
    if (['SENDING', 'UNKNOWN', 'PREPARING', 'EXECUTING'].includes(row.status)) provisional.add(identity)
    persistUnconfirmed([identity])
  }
  const send = async (
    taskId: string, clientId: string, content: string, metadata?: Record<string, any>,
    newAgentSession?: boolean, resumeInterrupted = false,
  ) => {
    const workspace = options.workspaceId()
    const creator = options.userId()
    const identity = key(taskId, clientId, creator, workspace)
    const { chat_images: images, ...requestMetadata } = metadata || {}
    const imageIds = (images as ChatImageReference[] | undefined)?.map(image => image.id)
    noteTaskRunInitiated(taskId, clientId)
    put({ task_id: taskId, client_message_id: clientId, content, metadata, new_agent_session: newAgentSession,
      resume_interrupted: resumeInterrupted, status: 'SENDING',
      creator_id: creator, created_at: new Date().toISOString() }, workspace)
    try {
      const data: ChatSubmission = resumeInterrupted
        ? (await options.resumeInterruptedTask(taskId, {
          prompt: content, clientMessageId: clientId, agentModel: metadata?.agent_model, newAgentSession,
          ...(imageIds?.length ? { imageIds } : {}),
        })).submission
        : (await api.post(`/workspaces/${workspace}/tasks/${taskId}/chat-submissions`, {
          client_message_id: clientId, content, metadata: imageIds?.length ? requestMetadata : metadata,
          ...(imageIds?.length ? { image_ids: imageIds } : {}),
          ...(newAgentSession ? { new_agent_session: true } : {}),
        })).data
      put({ ...data, creator_id: data.creator_id || creator }, workspace)
      if (data.ai_job_id) noteTaskRunInitiated(taskId, clientId, data.ai_job_id)
      return true
    } catch (error: any) {
      const row = receipts.value[identity]
      if (!row) return false
      if (row?.id) return true // A server receipt received over WS takes precedence.
      const status = error.response?.status
      const detail = error.response?.data?.detail
      const code = detail?.code
      const inOriginalWorkspace = options.workspaceId() === workspace && options.userId() === creator
      if (code === 'AGENT_SESSION_CHANGED' && inOriginalWorkspace) options.onAgentSessionChanged?.(taskId)
      if (code === 'AGENT_SESSION_UNAVAILABLE') {
        forgetTaskRunIntent(taskId, clientId)
        delete receipts.value[identity]
        provisional.delete(identity)
        persistUnconfirmed([identity])
        if (inOriginalWorkspace) options.onAgentSessionUnavailable?.(taskId)
        return false
      }
      const definitive = status >= 400 && status < 500 && ![408, 429].includes(status)
      if (definitive) forgetTaskRunIntent(taskId, clientId)
      put({ ...row, status: definitive ? 'FAILED' : 'UNKNOWN',
        error_message: definitive ? ((typeof detail === 'string' ? detail : detail?.message) || '消息未被接收，请重试') : '正在确认发送结果，请勿重复发送' }, workspace)
      // Keep an ambiguous send in its recoverable bubble, rather than leaving
      // the same prompt in the composer to be sent again under a new key.
      return !definitive
    }
  }
  const clear = (taskId: string) => {
    const removed: string[] = []
    for (const [id, row] of Object.entries(receipts.value)) if (row.task_id === taskId) {
      invalidated.add(id)
      provisional.delete(id)
      delete receipts.value[id]
      removed.push(id)
    }
    persistUnconfirmed(removed)
  }
  const removeMessages = (taskId: string, messageIds: Set<string>) => {
    const removed: string[] = []
    for (const [id, row] of Object.entries(receipts.value)) if (row.task_id === taskId && row.chat_message_id && messageIds.has(row.chat_message_id)) {
      invalidated.add(id)
      provisional.delete(id)
      delete receipts.value[id]
      removed.push(id)
    }
    persistUnconfirmed(removed)
  }
  const bubbles = (messages: any[], creatorMeta?: Record<string, any>) => {
    const mapped = messages.map(message => {
      const row = current.value.find(item => item.chat_message_id && item.chat_message_id === message.id)
      if (row) provisional.delete(keyForReceipt(row))
      return row ? { ...message, delivery_status: row.status.toLowerCase(), delivery_error: row.error_message } : message
    })
    for (const row of current.value) {
      const awaitingHistory = provisional.has(keyForReceipt(row))
      const identity = messageIdentity(row)
      if ((row.status === 'SUCCEEDED' && !awaitingHistory)
        || (row.status === 'FAILED' && row.chat_message_id && !awaitingHistory)
        || mapped.some(message => (row.chat_message_id && message.id === row.chat_message_id)
        || messageIdentity(message) === identity)) continue
      // The pending bubble must render exactly like the eventual server message:
      // creator profile decides the expert badge/avatar, metadata decides the body.
      const creator = creatorMeta && String(row.creator_id || '') === options.userId() ? creatorMeta : null
      mapped.push({ id: `submission-${identity}`, role: 'user', content: row.content,
        client_message_id: row.client_message_id, creator_id: row.creator_id, created_at: row.created_at,
        message_type: 'text', can_undo: false, metadata: row.metadata || null,
        delivery_status: row.status.toLowerCase(), delivery_error: row.error_message,
        ...(creator || {}) })
    }
    return mapped
  }
  return { current, busy, put, send, clear, removeMessages, bubbles, unconfirmedKeys }
}
