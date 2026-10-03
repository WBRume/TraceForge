import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { buildBackendWsUrl } from '@/utils/ws'
import { wsBackoffDelay } from '@/utils/wsBackoff'
import { buildWsCursorQuery, sendResyncComplete } from '@/utils/wsCursor'
import { createSerializedWsConsumer } from '@/utils/serializedWsConsumer'
import { useAuthStore } from '@/stores/auth'
import type { OnlinePresenceUser } from './types'
import type { ProjectContext } from './useProjectContext'
import type { WorkspaceContext } from './useWorkspaceContext'
import type { ProjectJobs } from './useProjectJobs'
import type { WorkbenchNotifications } from './notifications'

export function useProjectCollaboration(context: ProjectContext, notifications: WorkbenchNotifications, jobs: ProjectJobs, workspace: WorkspaceContext, refresh: () => Promise<void>) {
  const { workspaceMemberMap } = workspace

  const { project, selectedEndpointId } = context

  const { toActiveJobState, acceptJobState } = jobs

  const { notifySuccess } = notifications

  const { t } = useI18n()

  const authStore = useAuthStore()

  const onlineUserIds = ref<string[]>([])

  const collabConnected = ref(false)

  let collabSocket: WebSocket | null = null

  let collabConsumer: ReturnType<typeof createSerializedWsConsumer> | null = null

  let collabSocketManualClose = false

  let collabReconnectTimer: number | null = null

  let collabProjectId = ''

  const COLLAB_RECONNECT_DELAY_MS = 1200

  let collabReconnectAttempt = 0

  const onlineUsers = computed<OnlinePresenceUser[]>(() =>
    onlineUserIds.value.map((userId) => {
      const mapped = workspaceMemberMap.value[userId]
      if (mapped) return mapped
      if (authStore.user?.id === userId) {
        return {
          id: userId,
          displayName: authStore.user.display_name || authStore.user.email || userId,
          email: authStore.user.email,
          avatarSvg: authStore.user.avatar_svg || null,
          avatarUrl: authStore.user.avatar_url || null,
        }
      }
      return { id: userId, displayName: userId }
    }),
  )

  const clearCollabReconnectTimer = () => {
    if (collabReconnectTimer !== null) {
      window.clearTimeout(collabReconnectTimer)
      collabReconnectTimer = null
    }
  }

  const scheduleCollabReconnect = () => {
    if (!project.value?.id || collabReconnectTimer !== null) return
    const delay = wsBackoffDelay(collabReconnectAttempt, COLLAB_RECONNECT_DELAY_MS)
    collabReconnectAttempt += 1
    collabReconnectTimer = window.setTimeout(() => {
      collabReconnectTimer = null
      if (!project.value?.id) return
      if (collabSocket && collabSocket.readyState !== WebSocket.CLOSED) return
      connectCollab()
    }, delay)
  }

  const closeSocket = () => {
    clearCollabReconnectTimer()
    collabConsumer?.close()
    collabConsumer = null
    if (collabSocket) {
      collabSocketManualClose = true
      collabSocket.close()
      collabSocket = null
    }
    collabProjectId = ''
    collabConnected.value = false
    onlineUserIds.value = []
  }

  const connectCollab = () => {
    if (collabProjectId === project.value?.id && collabSocket &&
        (collabSocket.readyState === WebSocket.OPEN || collabSocket.readyState === WebSocket.CONNECTING)) return
    closeSocket()
    if (!project.value?.id) return
    const token = authStore.token || ''
    const room = `api-mock:${project.value.id}`
    const url = buildBackendWsUrl(`/ws/api-mock/${project.value.id}`, {
      token,
      ...buildWsCursorQuery(room),
    })
    const socket = new WebSocket(url)
    collabSocket = socket
    collabProjectId = project.value.id
    const consumer = createSerializedWsConsumer({
      room,
      onEvent: (event) => applyCollabMessage(event.payload || {}),
      onResync: async (frame, reason, context, signal) => {
        if (reason === 'gap') {
          context.socket.close(4000, 'sequence_gap')
          return
        }
        await refresh()
        if (!signal.aborted && collabSocket === context.socket && context.socket.readyState === WebSocket.OPEN) {
          sendResyncComplete(context.socket, frame, room)
        }
      },
      onControl: (frame) => {
        if (!['resume_ok', 'resync_ok'].includes(String(frame?.type || ''))) applyCollabMessage(frame)
      },
      onFailure: (_error, context) => {
        if (context.socket.readyState === WebSocket.OPEN) context.socket.close(4002, 'ws_consumer_failed')
      },
    })
    collabConsumer = consumer
    const generation = consumer.resetForConnection(socket)
    socket.onopen = () => {
      if (collabSocket !== socket) return
      collabSocketManualClose = false
      clearCollabReconnectTimer()
      collabReconnectAttempt = 0
      collabConnected.value = true
    }
    socket.onclose = () => {
      consumer.close(generation)
      if (collabSocket !== socket) return
      collabConnected.value = false
      collabSocket = null
      if (collabSocketManualClose) {
        collabSocketManualClose = false
        return
      }
      scheduleCollabReconnect()
    }
    socket.onerror = () => {
      if (collabSocket !== socket) return
      collabConnected.value = false
    }
    socket.onmessage = (event) => {
      if (collabSocket !== socket) return
      try {
        const raw = JSON.parse(event.data || '{}')
        consumer.enqueue(raw, generation)
      } catch {
        // ignore ws parse errors
      }
    }

    const applyCollabMessage = (data: any) => {
        if (Array.isArray(data.online_users)) {
          onlineUserIds.value = data.online_users
            .map((item: unknown) => String(item || '').trim())
            .filter((item: string) => Boolean(item))
        }
        if (data?.type === 'job_update' || data?.type === 'job_done') {
          const parsedJob = toActiveJobState(data.job)
          if (parsedJob) {
            acceptJobState(parsedJob)
          }
        }
        if (data?.type === 'event' && data?.user_id && data.user_id !== authStore.user?.id) {
          if (data.event === 'save') {
            notifySuccess(t('api_mock.collab_saved_notice'))
          }
          if (data.event === 'conflict') {
            ElMessage({
              type: 'warning',
              message: t('api_mock.collab_conflict_notice'),
              duration: 2600,
              grouping: true,
            })
          }
        }
    }
  }

  const sendCollabEvent = (event: string, payload: Record<string, unknown>) => {
    if (!collabSocket || collabSocket.readyState !== WebSocket.OPEN) return
    collabSocket.send(JSON.stringify({ type: event, payload, endpoint_id: selectedEndpointId.value }))
  }

  onBeforeUnmount(closeSocket)

  return { onlineUserIds, collabConnected, onlineUsers, clearCollabReconnectTimer, scheduleCollabReconnect, closeSocket, connectCollab, sendCollabEvent }
}

export type ProjectCollaboration = ReturnType<typeof useProjectCollaboration>
