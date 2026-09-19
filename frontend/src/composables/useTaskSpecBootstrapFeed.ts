import { onBeforeUnmount, ref, shallowRef, toValue, watch, type MaybeRefOrGetter } from 'vue'
import { useAuthStore } from '@/stores/auth'
import api from '@/utils/api'
import { buildBackendWsUrl } from '@/utils/ws'
import { buildWsCursorQuery, sendResyncComplete } from '@/utils/wsCursor'
import { wsBackoffDelay } from '@/utils/wsBackoff'
import { createSerializedWsConsumer } from '@/utils/serializedWsConsumer'
import type { TaskSpecBootstrap } from '@/composables/chat/types'

/**
 * Spec 基线状态订阅（无会话 WS 的页面用）：REST 快照 + 任务房间 WS 增量，
 * 服务端每次状态变更都会广播 spec_bootstrap_update，前端不做轮询。
 * 会话内（ChatView）已有同源状态，抽屉等场景直接复用 vm.specBootstrap。
 */
export function useTaskSpecBootstrapFeed(options: {
  wsId: MaybeRefOrGetter<string>
  taskId: MaybeRefOrGetter<string>
}) {
  const authStore = useAuthStore()

  const bootstrap = ref<TaskSpecBootstrap | null>(null)
  const ws = shallowRef<WebSocket | null>(null)
  let consumer: ReturnType<typeof createSerializedWsConsumer> | null = null
  let reconnectTimer: number | null = null
  let reconnectAttempt = 0
  let manualClose = false

  const clearReconnectTimer = () => {
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
  }

  const closeSocket = () => {
    consumer?.close()
    consumer = null
    if (ws.value) {
      ws.value.onopen = null
      ws.value.onmessage = null
      ws.value.onerror = null
      ws.value.onclose = null
      ws.value.close()
      ws.value = null
    }
  }

  const loadSnapshot = async () => {
    const wsId = String(toValue(options.wsId) || '')
    const taskId = String(toValue(options.taskId) || '')
    if (!wsId || !taskId) return
    try {
      const res = await api.get(`/workspaces/${wsId}/tasks/${taskId}/spec-bootstrap`)
      bootstrap.value = res.data || null
    } catch (e: any) {
      if (e?.response?.status === 404) {
        bootstrap.value = null
        return
      }
      console.warn('Failed to load spec bootstrap snapshot', e)
    }
  }

  const scheduleReconnect = (taskId: string) => {
    if (manualClose || reconnectTimer !== null) return
    const delay = wsBackoffDelay(reconnectAttempt)
    reconnectAttempt += 1
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null
      if (String(toValue(options.taskId) || '') !== taskId) return
      connect()
    }, delay)
  }

  const connect = () => {
    clearReconnectTimer()
    const wsId = String(toValue(options.wsId) || '')
    const taskId = String(toValue(options.taskId) || '')
    closeSocket()
    if (!wsId || !taskId) {
      bootstrap.value = null
      return
    }
    const room = `task:${taskId}`
    manualClose = false
    let socket: WebSocket
    try {
      socket = new WebSocket(buildBackendWsUrl(`/ws/task/${taskId}`, {
        token: authStore.token || undefined,
        ...buildWsCursorQuery(room),
      }))
    } catch (error) {
      console.error('Failed to open task spec bootstrap WebSocket', error)
      scheduleReconnect(taskId)
      return
    }
    ws.value = socket
    consumer = createSerializedWsConsumer({
      room,
      onEvent: (event) => {
        if (String(event?.event_type || '') === 'spec_bootstrap_update') {
          bootstrap.value = (event.payload as TaskSpecBootstrap) || null
        }
      },
      onResync: async (frame, reason, context, signal) => {
        if (reason === 'gap') {
          context.socket.close(4000, 'sequence_gap')
          return
        }
        // 屏障协议保证：先拉快照，再发 resync_complete，后续增量必然晚于快照
        await loadSnapshot()
        if (!signal.aborted && context.socket === ws.value && context.socket.readyState === WebSocket.OPEN) {
          sendResyncComplete(context.socket, frame, room)
        }
      },
      onControl: (frame) => {
        // resume_ok：回放已完成，此刻的快照不会被回放事件覆盖
        if (String(frame?.type || '') === 'resume_ok') void loadSnapshot()
      },
      onFailure: (_error, context) => {
        if (context.socket.readyState === WebSocket.OPEN) context.socket.close(4002, 'ws_consumer_failed')
      },
    })
    const generation = consumer.resetForConnection(socket)
    socket.onopen = () => {
      reconnectAttempt = 0
    }
    socket.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data)
        consumer?.enqueue(data, generation)
      } catch {
        // Ignore malformed frames
      }
    }
    socket.onerror = () => {
      // onclose 统一处理重连
    }
    socket.onclose = (event) => {
      consumer?.close(generation)
      consumer = null
      if (event.code === 1008) return
      if (!manualClose && String(toValue(options.taskId) || '') === taskId) {
        scheduleReconnect(taskId)
      }
    }
  }

  watch(
    () => [String(toValue(options.wsId) || ''), String(toValue(options.taskId) || '')] as const,
    ([, taskId]) => {
      bootstrap.value = null
      reconnectAttempt = 0
      manualClose = false
      if (taskId) void loadSnapshot()
      connect()
    },
    { immediate: true },
  )

  onBeforeUnmount(() => {
    manualClose = true
    clearReconnectTimer()
    closeSocket()
  })

  return {
    bootstrap,
  }
}
