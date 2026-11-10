import { ref, shallowRef } from 'vue'
import { buildBackendWsUrl } from '@/utils/ws'
import { wsBackoffDelay } from '@/utils/wsBackoff'
import { buildWsCursorQuery, sendResyncComplete } from '@/utils/wsCursor'
import { createSerializedWsConsumer } from '@/utils/serializedWsConsumer'
import type { AssetAiJob, AssetResolutionProposal, AssetThread, AssetThreadMessage } from './types'
import type { AssetRequestOwner } from './requestScope'
import type { AssetDocumentModel, RefreshAssetDocument } from './useAssetDocument'
import type { AssetThreadsModel } from './useAssetThreads'
import { resolveThreadJobKind, type AssetThreadJobsModel } from './useAssetThreadJobs'

export function useAssetDiscussionSubscription(
  document: AssetDocumentModel,
  discussion: AssetThreadsModel,
  jobs: AssetThreadJobsModel,
  refresh: RefreshAssetDocument,
  getToken: () => string,
) {
  const onlineUsers = ref<string[]>([])
  const wsConnected = shallowRef(false)
  let socket: WebSocket | null = null
  let consumer: ReturnType<typeof createSerializedWsConsumer> | null = null
  let reconnectTimer: number | undefined
  let reconnectAttempt = 0
  let manualClose = true

  const clearReconnect = () => {
    if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer)
    reconnectTimer = undefined
  }

  const closeConnection = () => {
    consumer?.close()
    consumer = null
    if (socket) {
      socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null
      socket.close()
      socket = null
    }
    wsConnected.value = false
  }

  const handleWsEvent = async (eventData: any, owner: AssetRequestOwner) => {
    if (!owner.isCurrent()) return
    const eventType = String(eventData?.type || '')
    if (eventType === 'presence') {
      onlineUsers.value = Array.isArray(eventData.online_users) ? eventData.online_users : []
      return
    }
    if (eventType === 'thread_created' && eventData.thread) {
      discussion.setThread(eventData.thread as AssetThread, owner)
      await document.loadDocument(document.activeVersionId.value || undefined, owner)
      return
    }
    if (eventType === 'thread_updated' && eventData.thread) {
      discussion.setThread(eventData.thread as AssetThread, owner)
      await document.loadDocument(document.activeVersionId.value || undefined, owner)
      return
    }
    if (eventType === 'message_created' && eventData.thread_id && eventData.message) {
      const threadId = String(eventData.thread_id)
      const message = eventData.message as AssetThreadMessage
      const thread = discussion.threads.value.find(item => item.id === threadId)
      if (thread) {
        if (!thread.messages.some(item => item.id === message.id)) {
          thread.messages.push(message)
          thread.messages.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
          document.setMarkerCount(threadId, 1)
        }
      } else {
        try {
          await discussion.fetchThread(threadId, owner)
        } catch {
          // Ignore transient fetch failure for delayed sync.
        }
      }
      if (!owner.isCurrent()) return
      if (message.role === 'ai') {
        jobs.clearThreadJobByKind(threadId, 'THREAD_AI_REPLY')
      }
      return
    }
    if (eventType === 'proposal_created' && eventData.thread_id && eventData.proposal) {
      const threadId = String(eventData.thread_id)
      const thread = discussion.threads.value.find(item => item.id === threadId)
      const proposal = eventData.proposal as AssetResolutionProposal
      if (thread) {
        const idx = thread.proposals.findIndex(item => item.id === proposal.id)
        if (idx >= 0) {
          thread.proposals[idx] = proposal
        } else {
          thread.proposals.unshift(proposal)
        }
      }
      jobs.clearThreadJobByKind(threadId, 'RESOLUTION_PROPOSAL')
      jobs.clearThreadJobByKind(threadId, 'RESOLUTION_REWRITE')
      return
    }
    if (eventType === 'version_applied' && eventData.version?.id) {
      await refresh(String(eventData.version.id), owner)
      return
    }
    if (
      (eventType === 'ai_job_update' || eventType === 'ai_job_done' || eventType === 'ai_job_failed')
      && eventData.job
    ) {
      const job = eventData.job as AssetAiJob
      const kind = resolveThreadJobKind(job)
      jobs.setThreadJob(job, owner)
      // Proposal/rewrite jobs may finish before `proposal_created` arrives or when that
      // event is transiently dropped; force a thread refresh as a reliable fallback.
      if (
        (eventType === 'ai_job_done' || eventType === 'ai_job_failed')
        && job.thread_id
        && (kind === 'RESOLUTION_PROPOSAL' || kind === 'RESOLUTION_REWRITE')
      ) {
        try {
          await discussion.fetchThread(String(job.thread_id), owner)
        } catch {
          // Ignore transient pull failures; polling/reconnect will retry.
        }
      }
    }
  }

  const connect = (resource: AssetRequestOwner) => {
    if (!resource.isCurrent()) return
    clearReconnect()
    closeConnection()
    manualClose = false
    const connection = new WebSocket(buildBackendWsUrl(`/ws/assets/${resource.assetId}/discussion`, {
      token: getToken(), ...buildWsCursorQuery(`asset:${resource.assetId}`),
    }))
    socket = connection
    const isCurrent = () => resource.isCurrent() && socket === connection && !manualClose
    const eventOwner = (signal: AbortSignal): AssetRequestOwner => ({
      ...resource, signal, isCurrent: () => isCurrent() && !signal.aborted,
    })
    const currentConsumer = createSerializedWsConsumer({
      room: `asset:${resource.assetId}`,
      onEvent: (event, _context, signal) => handleWsEvent(event.payload, eventOwner(signal)),
      onControl: (frame, _context, signal) => handleWsEvent(frame, eventOwner(signal)),
      onResync: async (frame, reason, _context, signal) => {
        const owner = eventOwner(signal)
        if (!owner.isCurrent()) return
        if (reason === 'gap' || reason === 'contract_invalid') {
          connection.close(4000, 'sequence_gap')
          return
        }
        await refresh(undefined, owner)
        if (owner.isCurrent() && connection.readyState === WebSocket.OPEN) {
          sendResyncComplete(connection, frame, `asset:${resource.assetId}`)
        }
      },
      onFailure: () => {
        if (isCurrent() && connection.readyState === WebSocket.OPEN) connection.close(4002, 'ws_consumer_failed')
      },
    })
    consumer = currentConsumer
    const generation = currentConsumer.resetForConnection(connection)
    connection.onopen = () => {
      if (!isCurrent()) return
      wsConnected.value = true
      reconnectAttempt = 0
    }
    connection.onmessage = (event) => {
      if (!isCurrent()) return
      try { currentConsumer.enqueue(JSON.parse(event.data), generation) } catch { /* Ignore malformed frames. */ }
    }
    connection.onerror = () => { if (isCurrent()) wsConnected.value = false }
    connection.onclose = () => {
      currentConsumer.close(generation)
      if (!isCurrent()) return
      wsConnected.value = false
      if (reconnectTimer !== undefined) return
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = undefined
        if (isCurrent()) connect(resource)
      }, wsBackoffDelay(reconnectAttempt++))
    }
  }

  const disconnect = () => {
    manualClose = true
    clearReconnect()
    closeConnection()
    onlineUsers.value = []
    reconnectAttempt = 0
  }

  return { onlineUsers, wsConnected, connect, disconnect }
}
