import { onMounted, onScopeDispose, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import { buildBackendWsUrl } from '@/utils/ws'
import { sendResyncComplete } from '@/utils/wsCursor'
import { canvasId, canvasUrl, type CanvasAsset, type CanvasEdit, type CanvasNodeInput, type CanvasSnapshot,
  type PlanFilesPage } from './model'

interface Operation { id: string; edit: CanvasEdit; anchors: CanvasNodeInput[] }

export function useWorkspaceCanvas(workspaceId: string) {
  const { t } = useI18n()
  const auth = useAuthStore()
  const url = canvasUrl(workspaceId)
  const snapshot = shallowRef<CanvasSnapshot | null>(null)
  const loading = shallowRef(true)
  const saving = shallowRef(false)
  const syncError = shallowRef('')
  const saveError = shallowRef('')
  const canRetry = shallowRef(false)
  const planFiles = shallowRef<CanvasAsset[]>([])
  const readingPlans = shallowRef(false)
  const controller = new AbortController()
  let failedOperation: Operation | null = null
  let reading: Promise<boolean> | null = null
  let socket: WebSocket | null = null
  let readTimer: ReturnType<typeof setTimeout> | undefined
  let connectTimer: ReturnType<typeof setTimeout> | undefined
  let planTimer: ReturnType<typeof setTimeout> | undefined
  let plansRequest: AbortController | null = null
  let disposed = false

  async function refresh(afterCurrent = false): Promise<boolean> {
    if (reading) {
      if (!afterCurrent) return reading
      await reading
      return refresh()
    }
    if (disposed) return false
    reading = api.get<CanvasSnapshot>(url, { signal: controller.signal }).then(({ data }) => {
      if (disposed) return false
      if (!snapshot.value || data.revision >= snapshot.value.revision) snapshot.value = data
      syncError.value = ''
      return true
    }).catch((error: unknown) => {
      if (disposed) return false
      const status = (error as { response?: { status?: number } }).response?.status
      if (status === 401 || status === 403) {
        snapshot.value = null
        closeSocket()
      }
      syncError.value = formatApiError(error, t('workspace_canvas.load_failed'), t)
      return false
    }).finally(() => {
      reading = null
      loading.value = false
    })
    return reading
  }

  async function submit(request: () => Promise<unknown>, operation?: Operation): Promise<boolean> {
    if (saving.value || disposed) return false
    saving.value = true
    saveError.value = ''
    failedOperation = null
    canRetry.value = false
    try {
      await request()
      await refresh(true)
      return true
    } catch (error) {
      if (disposed) return false
      const response = (error as { response?: { status?: number; data?: { detail?: unknown } } }).response
      const conflict = response?.data?.detail === 'CANVAS_TEXT_CHANGED'
      saveError.value = conflict ? t('workspace_canvas.edit_conflict') : formatApiError(error, t('workspace_canvas.save_failed'), t)
      if (operation && (!response?.status || response.status >= 500)) {
        failedOperation = operation
        canRetry.value = true
      }
      await refresh(true)
      return false
    } finally {
      saving.value = false
    }
  }

  const send = (operation: Operation) => submit(() => api.post(`${url}/operations`, operation), operation)
  const edit = (change: CanvasEdit, anchors: CanvasNodeInput[] = []) => send({ id: canvasId(), edit: change, anchors })
  const retry = () => failedOperation ? send(failedOperation) : refresh(true)

  function closeSocket() {
    clearTimeout(connectTimer)
    const previous = socket
    socket = null
    previous?.close()
  }

  function connect() {
    closeSocket()
    if (disposed || !auth.token) return
    const path = `/ws/workspace-canvas/${encodeURIComponent(workspaceId)}`
    const activeSocket = new WebSocket(buildBackendWsUrl(path, { token: auth.token }))
    socket = activeSocket
    activeSocket.onmessage = async (event) => {
      if (socket !== activeSocket) return
      try {
        const frame = JSON.parse(event.data)
        if (frame?.type === 'resync_required') {
          await refresh(true)
          if (socket === activeSocket && activeSocket.readyState === WebSocket.OPEN) {
            sendResyncComplete(activeSocket, frame, `workspace-canvas:${workspaceId}`)
          }
        } else if (frame?.type === 'canvas_changed' && !saving.value) void refresh(true)
      } catch { /* snapshot refresh remains available */ }
    }
    activeSocket.onclose = () => {
      if (socket !== activeSocket || disposed) return
      socket = null
      connectTimer = setTimeout(connect, 6000)
    }
  }

  function poll() {
    const interval = socket?.readyState === WebSocket.OPEN ? 6000 : 3000
    readTimer = setTimeout(async () => {
      if (!document.hidden && !saving.value) await refresh()
      if (!disposed) poll()
    }, interval)
  }

  async function refreshPlanFiles() {
    if (disposed || plansRequest) return
    const request = new AbortController()
    plansRequest = request
    readingPlans.value = true
    const items: CanvasAsset[] = []
    let cursor: string | null = null
    try {
      do {
        const { data }: { data: PlanFilesPage } = await api.get(`${url}/plan-files`, {
          params: { cursor }, signal: request.signal, timeout: 25_000,
        })
        if (request.signal.aborted) return
        items.push(...data.items)
        cursor = data.next_cursor
      } while (cursor)
      planFiles.value = items
    } catch {
      // Plan storage can be offline while the database-backed assets remain available.
    } finally {
      if (plansRequest === request) {
        plansRequest = null
        readingPlans.value = false
        planTimer = setTimeout(pollPlanFiles, 45_000)
      }
    }
  }

  function pollPlanFiles() {
    if (disposed || !snapshot.value?.access.source_kinds.includes('plan_document')) return
    if (document.hidden) planTimer = setTimeout(pollPlanFiles, 45_000)
    else void refreshPlanFiles()
  }

  watch(() => snapshot.value?.access.source_kinds.includes('plan_document'), allowed => {
    if (allowed) {
      void refreshPlanFiles()
    } else {
      clearTimeout(planTimer)
      plansRequest?.abort()
      plansRequest = null
      readingPlans.value = false
      planFiles.value = []
    }
  })

  const refreshOnFocus = () => { if (!document.hidden) void refresh(true) }

  onMounted(() => {
    void refresh()
    connect()
    poll()
    window.addEventListener('focus', refreshOnFocus)
    window.addEventListener('sdd-server-changed', connect)
    document.addEventListener('visibilitychange', refreshOnFocus)
  })
  watch(() => auth.token, connect)
  onScopeDispose(() => {
    disposed = true
    controller.abort()
    plansRequest?.abort()
    plansRequest = null
    clearTimeout(readTimer)
    clearTimeout(planTimer)
    closeSocket()
    window.removeEventListener('focus', refreshOnFocus)
    window.removeEventListener('sdd-server-changed', connect)
    document.removeEventListener('visibilitychange', refreshOnFocus)
  })

  return { snapshot, loading, saving, syncError, saveError, canRetry, planFiles, readingPlans, refresh, edit, retry, submit }
}
