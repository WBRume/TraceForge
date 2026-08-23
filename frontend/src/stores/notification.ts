import { ref } from 'vue'
import { defineStore } from 'pinia'
import api from '@/utils/api'
import { useAuthStore } from '@/stores/auth'
import { buildBackendWsUrl } from '@/utils/ws'

export type AppNotificationItem = {
  id: string
  workspace_id: string | null
  type: string
  title: string
  body: string | null
  payload: Record<string, any> | null
  read_at: string | null
  created_at: string | null
}

export const useNotificationStore = defineStore('appNotification', () => {
  const authStore = useAuthStore()

  const items = ref<AppNotificationItem[]>([])
  const unreadCount = ref(0)
  const loading = ref(false)
  const connected = ref(false)

  let ws: WebSocket | null = null
  let reconnectTimer: number | null = null
  let started = false

  const refreshUnreadCount = async () => {
    if (!authStore.isAuthenticated) return
    try {
      const res = await api.get('/notifications/unread-count')
      unreadCount.value = Number(res.data?.count || 0)
    } catch {
      // 静默失败：铃铛徽章兜底显示当前值
    }
  }

  const fetchList = async (options?: { unread_only?: boolean; page?: number; page_size?: number }) => {
    loading.value = true
    try {
      const res = await api.get('/notifications', {
        params: {
          unread_only: options?.unread_only || undefined,
          page: options?.page ?? 1,
          page_size: options?.page_size ?? 20,
        },
      })
      const list: AppNotificationItem[] = res.data?.items || []
      if ((options?.page ?? 1) <= 1) {
        items.value = list
      } else {
        items.value = [...items.value, ...list]
      }
      return list
    } catch {
      return []
    } finally {
      loading.value = false
    }
  }

  const markRead = async (id: string) => {
    const target = items.value.find((item) => item.id === id)
    if (target && target.read_at) return
    try {
      await api.post(`/notifications/${id}/read`)
      if (target) target.read_at = new Date().toISOString()
      if (unreadCount.value > 0) unreadCount.value -= 1
    } catch {
      // 忽略：下次刷新纠正
    }
  }

  const markAllRead = async () => {
    try {
      await api.post('/notifications/read-all')
      items.value = items.value.map((item) => ({ ...item, read_at: item.read_at || new Date().toISOString() }))
      unreadCount.value = 0
    } catch {
      // 忽略
    }
  }

  const removeItem = async (id: string) => {
    const target = items.value.find((item) => item.id === id)
    if (!target) return
    const wasUnread = !target.read_at
    // 乐观移除,失败时以刷新兜底恢复
    items.value = items.value.filter((item) => item.id !== id)
    if (wasUnread && unreadCount.value > 0) unreadCount.value -= 1
    try {
      await api.delete(`/notifications/${id}`)
    } catch {
      void fetchList()
      void refreshUnreadCount()
    }
  }

  const clearAll = async () => {
    if (items.value.length === 0) return
    items.value = []
    unreadCount.value = 0
    try {
      await api.delete('/notifications')
    } catch {
      void fetchList()
      void refreshUnreadCount()
    }
  }

  const handleIncoming = (item: AppNotificationItem) => {
    if (!item?.id) return
    const index = items.value.findIndex((existing) => existing.id === item.id)
    if (index >= 0) {
      items.value[index] = { ...items.value[index], ...item }
      return
    }
    items.value = [item, ...items.value]
    if (!item.read_at) unreadCount.value += 1
  }

  const clearReconnectTimer = () => {
    if (reconnectTimer === null) return
    window.clearTimeout(reconnectTimer)
    reconnectTimer = null
  }

  const connectWs = () => {
    if (!started || !authStore.token) return
    if (ws) {
      ws.onopen = null
      ws.onmessage = null
      ws.onerror = null
      ws.onclose = null
      ws.close()
      ws = null
    }
    ws = new WebSocket(buildBackendWsUrl('/ws/notifications', { token: authStore.token }))
    ws.onopen = () => {
      connected.value = true
    }
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data?.type === 'notification' && data.payload) {
          handleIncoming(data.payload as AppNotificationItem)
        }
      } catch {
        // 忽略非 JSON 帧
      }
    }
    ws.onerror = () => {
      connected.value = false
    }
    ws.onclose = (event) => {
      connected.value = false
      if (event.code === 1008 || !started) return
      clearReconnectTimer()
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null
        if (started && authStore.isAuthenticated) {
          connectWs()
          void refreshUnreadCount()
        }
      }, 3000)
    }
  }

  const start = () => {
    if (started || !authStore.isAuthenticated) return
    started = true
    void refreshUnreadCount()
    void fetchList()
    connectWs()
  }

  const stop = () => {
    started = false
    clearReconnectTimer()
    if (ws) {
      ws.onclose = null
      ws.close()
      ws = null
    }
    connected.value = false
  }

  const reset = () => {
    stop()
    items.value = []
    unreadCount.value = 0
  }

  return {
    items,
    unreadCount,
    loading,
    connected,
    refreshUnreadCount,
    fetchList,
    markRead,
    markAllRead,
    removeItem,
    clearAll,
    start,
    stop,
    reset,
  }
})
