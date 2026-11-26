import { onMounted, onScopeDispose, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import { buildBackendWsUrl } from '@/utils/ws'
import { sendResyncComplete } from '@/utils/wsCursor'
import { canvasId, canvasUrl, type CanvasAsset, type CanvasEdit, type CanvasNodeInput, type CanvasSnapshot, type CanvasViewer,
  type PlanFilesPage } from './model'

interface Operation { id: string; edit: CanvasEdit; anchors: CanvasNodeInput[] }

export function useWorkspaceCanvas(workspaceId: string, getQuarter: () => string | undefined) {
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
  const planTaskIds = shallowRef<string[]>([])
  const onlineViewers = shallowRef<CanvasViewer[]>([])
  const calendarRevision = shallowRef(0)
  let failedOperation: Operation | null = null
  let reading: Promise<boolean> | null = null
  let readingRequest: AbortController | null = null
  let readingQuarter: string | undefined
  let socket: WebSocket | null = null
  let initialLoadTimer: ReturnType<typeof setTimeout> | undefined
  let refreshTimer: ReturnType<typeof setTimeout> | undefined
  let connectTimer: ReturnType<typeof setTimeout> | undefined
  let plansRequest: AbortController | null = null
  let plansPending = false
  let snapshotPending = false
  let disposed = false

  async function refresh(afterCurrent = false): Promise<boolean> {
    const quarter = getQuarter()
    if (reading && readingQuarter === quarter) {
      if (!afterCurrent) return reading
      await reading
      return refresh()
    }
    if (disposed) return false
    readingRequest?.abort()
    const request = new AbortController()
    readingRequest = request
    readingQuarter = quarter
    reading = api.get<CanvasSnapshot>(url, { params: { quarter }, signal: request.signal, timeout: 5000 }).then(({ data }) => {
      if (disposed || request.signal.aborted) return false
      if (!snapshot.value || data.quarter?.id !== snapshot.value.quarter?.id || data.revision >= snapshot.value.revision) snapshot.value = data
      syncError.value = ''
      return true
    }).catch((error: unknown) => {
      if (disposed || request.signal.aborted) return false
      const response = (error as { response?: { status?: number; data?: { detail?: unknown } } }).response
      const status = response?.status
      if (status === 401 || status === 403) {
        snapshot.value = null
        closeSocket()
      }
      syncError.value = response?.data?.detail === 'CANVAS_QUERY_BUSY' ? t('workspace_canvas.domains.query_busy')
        : formatApiError(error, t('workspace_canvas.load_failed'), t)
      return false
    }).finally(() => {
      if (readingRequest === request) {
        reading = null
        readingRequest = null
        loading.value = false
      }
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
      snapshotPending = false
      await refresh(true)
      return true
    } catch (error) {
      if (disposed) return false
      const response = (error as { response?: { status?: number; data?: { detail?: unknown } } }).response
      const conflict = response?.data?.detail === 'CANVAS_TEXT_CHANGED'
      const capacity = response?.data?.detail === 'CANVAS_ANNOTATION_LIMIT'
      saveError.value = conflict ? t('workspace_canvas.edit_conflict') : capacity ? t('workspace_canvas.domains.annotation_limit')
        : formatApiError(error, t('workspace_canvas.save_failed'), t)
      if (operation && (!response?.status || response.status >= 500)) {
        failedOperation = operation
        canRetry.value = true
      }
      snapshotPending = false
      await refresh(true)
      return false
    } finally {
      saving.value = false
      if (snapshotPending) scheduleRefresh()
    }
  }

  const send = (operation: Operation) => submit(() => api.post(`${url}/operations`, operation), operation)
  const edit = (change: CanvasEdit, anchors: CanvasNodeInput[] = []) => send({ id: canvasId(), edit: change, anchors })
  const retry = () => failedOperation ? send(failedOperation) : refresh(true)

  function scheduleRefresh() {
    snapshotPending = true
    clearTimeout(refreshTimer)
    refreshTimer = setTimeout(() => {
      if (disposed || saving.value || !snapshotPending) return
      snapshotPending = false
      void refresh(true)
    }, 60)
  }

  function closeSocket() {
    clearTimeout(connectTimer)
    const previous = socket
    socket = null
    onlineViewers.value = []
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
          clearTimeout(initialLoadTimer)
          const loaded = await refresh(true)
          if (socket === activeSocket && activeSocket.readyState === WebSocket.OPEN) {
            if (!loaded) { activeSocket.close(); return }
            sendResyncComplete(activeSocket, frame, `workspace-canvas:${workspaceId}`)
            calendarRevision.value++
            void refreshPlanFiles()
          }
        } else if (frame?.type === 'presence' && Array.isArray(frame.online_users)) {
          onlineViewers.value = frame.online_users
        } else if (frame?.type === 'canvas_changed') {
          if (frame.calendar) calendarRevision.value++
          if (typeof frame.plan_task_id === 'string' && planTaskIds.value.includes(frame.plan_task_id)) void refreshPlanFiles()
          if (frame.assets !== false) scheduleRefresh()
        }
      } catch { /* snapshot refresh remains available */ }
    }
    activeSocket.onclose = () => {
      if (socket !== activeSocket || disposed) return
      socket = null
      onlineViewers.value = []
      if (loading.value && !reading) void refresh()
      connectTimer = setTimeout(connect, 6000)
    }
  }

  async function refreshPlanFiles() {
    if (disposed || !planTaskIds.value.length || !snapshot.value?.access.source_kinds.includes('plan_document')) return
    if (plansRequest) { plansPending = true; return }
    plansPending = false
    const request = new AbortController()
    plansRequest = request
    readingPlans.value = true
    const taskIds = planTaskIds.value
    const items: CanvasAsset[] = []
    let cursor: string | null = null
    try {
      do {
        const params = new URLSearchParams(taskIds.map(id => ['task_id', id]))
        if (cursor) params.set('cursor', cursor)
        const { data }: { data: PlanFilesPage } = await api.get(`${url}/plan-files`, {
          params, signal: request.signal, timeout: 25_000,
        })
        if (request.signal.aborted) return
        items.push(...data.items)
        cursor = data.next_cursor
      } while (cursor && items.length < 72)
      const refreshed = new Set(taskIds)
      planFiles.value = [...planFiles.value.filter(file => !refreshed.has(file.reference.id)), ...items].slice(-96)
    } catch {
      // Plan storage can be offline while the database-backed assets remain available.
    } finally {
      if (plansRequest === request) {
        plansRequest = null
        readingPlans.value = false
        if (plansPending) void refreshPlanFiles()
      }
    }
  }

  function setPlanTasks(ids: string[]) {
    const next = [...new Set(ids)].slice(0, 12).sort()
    if (next.join(',') !== planTaskIds.value.join(',')) planTaskIds.value = next
  }

  watch([() => snapshot.value?.access.source_kinds.includes('plan_document'), planTaskIds], ([allowed, ids]) => {
    plansPending = false
    plansRequest?.abort()
    plansRequest = null
    readingPlans.value = false
    if (!allowed) planFiles.value = []
    if (allowed && ids.length) void refreshPlanFiles()
  })

  onMounted(() => {
    connect()
    initialLoadTimer = setTimeout(() => { if (!snapshot.value && !reading) void refresh() }, 2000)
    window.addEventListener('sdd-server-changed', connect)
  })
  watch(getQuarter, quarter => {
    if (quarter && quarter !== snapshot.value?.quarter?.id) {
      loading.value = true
      setPlanTasks([])
      planFiles.value = []
    }
    void refresh()
  })
  watch(() => auth.token, connect)
  onScopeDispose(() => {
    disposed = true
    readingRequest?.abort()
    plansRequest?.abort()
    plansRequest = null
    clearTimeout(initialLoadTimer)
    clearTimeout(refreshTimer)
    closeSocket()
    window.removeEventListener('sdd-server-changed', connect)
  })

  return { snapshot, loading, saving, syncError, saveError, canRetry, planFiles, readingPlans, onlineViewers,
    calendarRevision, setPlanTasks, refresh, edit, retry, submit }
}
