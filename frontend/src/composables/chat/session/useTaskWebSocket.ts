import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { buildBackendWsUrl } from '@/utils/ws'
import { buildWsCursorQuery } from '@/utils/wsCursor'
import { wsBackoffDelay } from '@/utils/wsBackoff'
import { createSerializedWsConsumer } from '@/utils/serializedWsConsumer'

/**
 * 任务会话 WebSocket 传输层：连接生命周期、指数退避重连、序列化消费器、
 * 订阅就绪握手状态。它不知道任何业务领域——所有业务反应通过 handlers 注入。
 */
export function useTaskWebSocket(options: {
  buildUrl: (taskId: string) => string
  isCurrentTask: (taskId: string) => boolean
  handlers: {
    /** 业务事件帧（chat_message / tool_use / status / ...） */
    onEvent: (event: { event_type: string; payload: any }) => void
    /** 控制帧：resume_ok/resync_ok 及未识别的控制类型 */
    onControlFrame: (frame: any, taskId: string) => void
    /** 恢复屏障：resync_required 时重建快照，完成后由实现方发送 resync_complete */
    onResync: (taskId: string, frame: any, reason: string, context: { socket: WebSocket }, signal: AbortSignal) => Promise<void> | void
    onSocketOpen: (taskId: string) => void
    onSocketClose: (taskId: string, code: number) => void
    /** 复用既有连接或新建连接时确保会话快照（ready=true 补齐 / false 武装兜底） */
    onConnectionReuse: (taskId: string, subscriptionReady: boolean) => void
    /** 连接构造失败（未就绪即失败）：HTTP 兜底 */
    onConnectionError: (taskId: string) => void
  }
}) {
  const authStore = useAuthStore()

  let ws: WebSocket | null = null
  let wsTaskId = ''
  let wsReconnectTimer: number | null = null
  let wsManualClose = false
  let wsReconnectAttempt = 0
  let taskWsConsumer: ReturnType<typeof createSerializedWsConsumer> | null = null
  let wsSubscriptionReady = false
  let wsSubscriptionReadyTaskId = ''

  const clearReconnectTimer = () => {
    if (wsReconnectTimer === null) return
    window.clearTimeout(wsReconnectTimer)
    wsReconnectTimer = null
  }

  const isSubscriptionReady = (taskId: string) => (
    wsSubscriptionReady && wsSubscriptionReadyTaskId === taskId
  )

  const markSubscriptionReady = (taskId: string) => {
    wsSubscriptionReady = true
    wsSubscriptionReadyTaskId = taskId
  }

  const scheduleReconnect = (taskId: string) => {
    if (wsManualClose || wsReconnectTimer !== null) return
    const delay = wsBackoffDelay(wsReconnectAttempt)
    wsReconnectAttempt += 1
    wsReconnectTimer = window.setTimeout(() => {
      wsReconnectTimer = null
      if (!options.isCurrentTask(taskId)) return
      connect(taskId)
    }, delay)
  }

  const isOpen = () => Boolean(ws && ws.readyState === WebSocket.OPEN)

  const getSocket = () => ws

  const buildTaskWsUrl = (taskId: string): string => (
    buildBackendWsUrl(`/ws/task/${taskId}`, {
      token: authStore.token || undefined,
      ...buildWsCursorQuery(`task:${taskId}`),
    })
  )

  const connect = (taskId: string) => {
    // 同一任务的连接已建立（或正在建立）时不再重建，避免重复 select/重复挂载
    // 触发 socket 抖动，服务端会把旧连接判定为 send_failed 后淘汰。
    if (
      ws
      && wsTaskId === taskId
      && taskWsConsumer
      && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)
    ) {
      options.handlers.onConnectionReuse(taskId, isSubscriptionReady(taskId))
      return
    }
    clearReconnectTimer()
    wsManualClose = false
    taskWsConsumer?.close()
    taskWsConsumer = null
    if (ws) {
      ws.onopen = null
      ws.onmessage = null
      ws.onerror = null
      ws.onclose = null
      ws.close()
      ws = null
    }
    wsSubscriptionReady = false
    wsSubscriptionReadyTaskId = ''
    try {
      ws = new WebSocket(options.buildUrl(taskId))
    } catch (error) {
      console.error('Failed to open task WebSocket', error)
      wsTaskId = taskId
      options.handlers.onConnectionError(taskId)
      return
    }
    wsTaskId = taskId
    options.handlers.onConnectionReuse(taskId, false)
    const socket = ws
    const consumer = createSerializedWsConsumer({
      room: `task:${taskId}`,
      onEvent: (event) => {
        options.handlers.onEvent({ event_type: event.event_type, payload: event.payload })
      },
      onResync: async (frame, reason, context, signal) => {
        if (reason === 'gap') {
          context.socket.close(4000, 'sequence_gap')
          return
        }
        // 恢复屏障：快照完成后才发 resync_complete，WS 增量必然晚于快照落地
        markSubscriptionReady(taskId)
        await options.handlers.onResync(taskId, frame, reason, context, signal)
      },
      onControl: (frame) => {
        options.handlers.onControlFrame(frame, taskId)
      },
      onFailure: (_error, context) => {
        if (context.socket.readyState === WebSocket.OPEN) context.socket.close(4002, 'ws_consumer_failed')
      },
    })
    taskWsConsumer = consumer
    const generation = consumer.resetForConnection(socket)
    ws.onopen = () => {
      console.log(`WS Connected: task=${taskId}`)
      wsReconnectAttempt = 0
      options.handlers.onSocketOpen(taskId)
    }
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        consumer.enqueue(data, generation)
      } catch {
        // Ignore malformed frames; the next reconnect will resync from REST.
      }
    }
    ws.onerror = (event) => {
      console.error('WS Error', event)
    }
    ws.onclose = (event) => {
      consumer.close(generation)
      console.log(`WS Disconnected: task=${taskId}`)
      options.handlers.onSocketClose(taskId, event.code)
    }
  }

  /** 发送一帧业务消息；连接不可用时返回 false（调用方决定是否重连）。 */
  const sendFrame = (type: string, payload: Record<string, any>): boolean => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return false
    ws.send(JSON.stringify({ type, payload }))
    return true
  }

  const closeForDispose = () => {
    wsManualClose = true
    clearReconnectTimer()
    if (ws) ws.close()
  }

  return {
    connect,
    sendFrame,
    isOpen,
    getSocket,
    isSubscriptionReady,
    markSubscriptionReady,
    scheduleReconnect,
    clearReconnectTimer,
    isHealthy: (taskId: string) => isOpen() && isSubscriptionReady(taskId),
    buildTaskWsUrl,
    closeForDispose,
    showAuthExpiredToast: () => {
      ElMessage.error('Task WebSocket authentication failed. Please sign in again.')
    },
  }
}
