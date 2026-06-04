<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import { buildBackendWsUrl } from '@/utils/ws'
import { useAuthStore } from '@/stores/auth'
import type {
  ApiMockDocument,
  ApiMockEndpoint,
  ApiMockEntity,
  ApiMockJob,
  ApiMockMockCase,
  ApiMockProject,
  ApiMockSourceVersion,
} from '@/types/apiMock'
import ApiMockTaskBar from '@/components/api-mock/ApiMockTaskBar.vue'
import ApiMockEndpointCatalog from '@/components/api-mock/ApiMockEndpointCatalog.vue'
import ApiMockEndpointWorkspace from '@/components/api-mock/ApiMockEndpointWorkspace.vue'
import ApiMockConfigDrawer from '@/components/api-mock/ApiMockConfigDrawer.vue'
import ApiMockGlobalEntityDrawer from '@/components/api-mock/ApiMockGlobalEntityDrawer.vue'
import ApiMockTaskPickerPanel from '@/components/api-mock/ApiMockTaskPickerPanel.vue'
import ShortcutHelpModal from '@/components/api-mock/ShortcutHelpModal.vue'

type TaskOption = {
  id: string
  name: string
}

type WorkspaceMemberProfile = {
  user_id: string
  display_name: string
  email: string
  avatar_svg?: string | null
  avatar_url?: string | null
}

type OnlinePresenceUser = {
  id: string
  displayName: string
  email?: string | null
  avatarSvg?: string | null
  avatarUrl?: string | null
}

type PermissionFlags = {
  view_api_mock?: boolean
  manage_api_mock?: boolean
  publish_api_mock?: boolean
}

type ActiveJobState = Pick<ApiMockJob, 'id' | 'job_type' | 'status' | 'progress' | 'message' | 'result_json'>
type ApiMockLockedDetail = {
  code?: unknown
  message?: unknown
  meta?: unknown
}
type ApiMockErrorBody = {
  detail?: ApiMockLockedDetail | string
}
type ApiMockJobListResponse = {
  items?: ApiMockJob[]
  total?: number
}
const AUTO_MOCK_JOB_TYPE = 'AUTO_GENERATE_MOCK_CASES'

const route = useRoute()
const { t } = useI18n()
const authStore = useAuthStore()

const wsId = computed(() => String(route.params.wsId || ''))
const endpointCatalogRef = ref<InstanceType<typeof ApiMockEndpointCatalog> | null>(null)
const workspaceRef = ref<InstanceType<typeof ApiMockEndpointWorkspace> | null>(null)

const tasks = ref<TaskOption[]>([])
const selectedTaskId = ref('')
const project = ref<ApiMockProject | null>(null)
const sourceVersions = ref<ApiMockSourceVersion[]>([])
const endpoints = ref<ApiMockEndpoint[]>([])
const endpointCache = ref<Record<string, ApiMockEndpoint>>({})
const entities = ref<ApiMockEntity[]>([])
const mockCases = ref<ApiMockMockCase[]>([])
const selectedEndpointId = ref('')
const selectedMockCaseId = ref('')
const documentData = ref<ApiMockDocument | null>(null)
const permissions = ref<PermissionFlags | null>(null)
const workspaceMemberMap = ref<Record<string, OnlinePresenceUser>>({})
const onlineUserIds = ref<string[]>([])

const loading = ref(false)
const permissionsReady = ref(false)
const syncBusy = ref(false)
const importBusy = ref(false)
const cancelJobBusy = ref(false)
const savingEndpoint = ref(false)
const savingDocument = ref(false)
const savingCase = ref(false)
const deletingCase = ref(false)
const documentLoading = ref(false)
const showConfigDrawer = ref(false)
const showGlobalEntityDrawer = ref(false)
const globalEntityDrawerRef = ref<InstanceType<typeof ApiMockGlobalEntityDrawer> | null>(null)
const configDrawerMode = ref<'sync' | 'versions' | 'proxy' | 'import'>('sync')
const showShortcuts = ref(false)
const showSideTaskPicker = ref(false)
const endpointKeyword = ref('')
const pageError = ref('')
const activeJob = ref<ActiveJobState | null>(null)
const activeAutoMockJob = ref<ActiveJobState | null>(null)
const autoMockStartBusy = ref(false)
const collabConnected = ref(false)
let collabSocket: WebSocket | null = null
let collabSocketManualClose = false
let collabReconnectTimer: number | null = null
let keywordTimer: number | null = null
let autoMockPollTimer: number | null = null
let autoMockPolling = false
const handledAutoMockDoneJobIds = new Set<string>()
let jobWaitSeq = 0
const COLLAB_RECONNECT_DELAY_MS = 1200
const AUTO_MOCK_POLL_INTERVAL_MS = 1500

const canView = computed(() => Boolean(permissions.value?.view_api_mock))
const canManage = computed(() => Boolean(permissions.value?.manage_api_mock))
const canPublish = computed(() => Boolean(permissions.value?.publish_api_mock))
const selectedTask = computed(() => tasks.value.find((item) => item.id === selectedTaskId.value) || null)
const selectedEndpoint = computed(() => {
  if (!selectedEndpointId.value) return null
  const fromVisibleList = endpoints.value.find((item) => item.id === selectedEndpointId.value)
  if (fromVisibleList) return fromVisibleList
  return endpointCache.value[selectedEndpointId.value] || null
})
const currentSource = computed(() => sourceVersions.value.find((item) => item.is_active) || null)
const currentSourceLabel = computed(() => {
  if (!selectedTaskId.value) return t('api_mock.task_empty')
  if (!currentSource.value) return t('api_mock.source_empty_hint')
  return `${currentSource.value.source_type} · ${currentSource.value.source_name || currentSource.value.id.slice(0, 8)}`
})
const canManageSwagger = computed(() => canManage.value && !isProjectSwaggerMutationLocked.value)
const isAutoMockRunning = computed(() => {
  const status = activeAutoMockJob.value?.status || ''
  return status === 'PENDING' || status === 'RUNNING'
})
const autoMockTargetEndpointId = computed(() => {
  const payload = activeAutoMockJob.value?.result_json
  if (!payload || typeof payload !== 'object') return ''
  return String((payload as Record<string, unknown>).target_endpoint_id || '').trim()
})
const isCurrentEndpointAutoMockLocked = computed(
  () => isAutoMockRunning.value && !!selectedEndpointId.value && autoMockTargetEndpointId.value === selectedEndpointId.value,
)
const isProjectSwaggerMutationLocked = computed(() => isAutoMockRunning.value)
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

const endpointIdentity = (endpoint: ApiMockEndpoint | null | undefined) =>
  endpoint ? `${endpoint.method.toUpperCase()} ${endpoint.path}` : ''

const notifySuccess = (text: string) => {
  ElMessage({
    type: 'success',
    message: text,
    duration: 1500,
    grouping: true,
  })
}

const notifyError = (err: unknown, fallback: string) => {
  ElMessage({
    type: 'error',
    message: formatApiError(err, fallback, t),
    duration: 2600,
    grouping: true,
  })
}

const notifyProjectSwaggerLocked = () => {
  ElMessage({
    type: 'warning',
    message: t('api_mock.ai_auto_mock_locked_project_swagger_mutation'),
    duration: 2600,
    grouping: true,
  })
}

const notifyCurrentEndpointCreateLocked = () => {
  ElMessage({
    type: 'warning',
    message: t('api_mock.ai_auto_mock_locked_current_endpoint'),
    duration: 2600,
    grouping: true,
  })
}

const isConflictError = (err: unknown) => {
  const status = Number((err as { response?: { status?: number } } | null)?.response?.status || 0)
  return status === 409
}

const isAutoMockProjectLockError = (err: unknown) => {
  const status = Number((err as { response?: { status?: number } } | null)?.response?.status || 0)
  if (status !== 409) return false
  const detail = parseLockedDetail(err)
  return String(detail?.code || '') === 'ai_auto_mock_locked_project_swagger_mutation'
}

const isAutoMockEndpointLockError = (err: unknown) => {
  const status = Number((err as { response?: { status?: number } } | null)?.response?.status || 0)
  if (status !== 409) return false
  const detail = parseLockedDetail(err)
  return String(detail?.code || '') === 'ai_auto_mock_locked_current_endpoint'
}

const normalizeJobStatus = (value: unknown): ActiveJobState['status'] => {
  const status = String(value || '').toUpperCase()
  if (status === 'RUNNING' || status === 'SUCCESS' || status === 'FAILED' || status === 'PENDING') {
    return status
  }
  return 'PENDING'
}

const sanitizeJobResultJson = (value: unknown): Record<string, unknown> | null => {
  if (!value || typeof value !== 'object') return null
  return { ...(value as Record<string, unknown>) }
}

const toActiveJobState = (value: unknown): ActiveJobState | null => {
  if (!value || typeof value !== 'object') return null
  const job = value as Record<string, unknown>
  const id = String(job.id || '').trim()
  const jobType = String(job.job_type || '').trim()
  if (!id || !jobType) return null
  return {
    id,
    job_type: jobType,
    status: normalizeJobStatus(job.status),
    progress: Number(job.progress || 0),
    message: typeof job.message === 'string' ? job.message : null,
    result_json: sanitizeJobResultJson(job.result_json),
  }
}

const mergeIncomingJobState = (incoming: ActiveJobState) => {
  const current = activeJob.value
  if (!current) {
    activeJob.value = incoming
    return
  }
  if (current.id === incoming.id) {
    activeJob.value = incoming
    return
  }
  const currentDone = current.status === 'SUCCESS' || current.status === 'FAILED'
  if (currentDone) {
    activeJob.value = incoming
  }
}

const mergeIncomingAutoMockJobState = (incoming: ActiveJobState) => {
  if (incoming.job_type !== AUTO_MOCK_JOB_TYPE) return
  if (incoming.status === 'PENDING' || incoming.status === 'RUNNING') {
    activeAutoMockJob.value = incoming
    return
  }
  if (activeAutoMockJob.value?.id === incoming.id) {
    activeAutoMockJob.value = null
  }
}

const parseLockedDetail = (err: unknown): ApiMockLockedDetail | null => {
  const detail = ((err as { response?: { data?: ApiMockErrorBody } })?.response?.data?.detail || null) as
    | ApiMockLockedDetail
    | string
    | null
  if (!detail || typeof detail === 'string') return null
  return detail
}

const clearCollabReconnectTimer = () => {
  if (collabReconnectTimer !== null) {
    window.clearTimeout(collabReconnectTimer)
    collabReconnectTimer = null
  }
}

const scheduleCollabReconnect = () => {
  if (!project.value?.id || collabReconnectTimer !== null) return
  collabReconnectTimer = window.setTimeout(() => {
    collabReconnectTimer = null
    if (!project.value?.id) return
    if (collabSocket && collabSocket.readyState !== WebSocket.CLOSED) return
    connectCollab()
  }, COLLAB_RECONNECT_DELAY_MS)
}

const stopAutoMockPolling = () => {
  if (autoMockPollTimer !== null) {
    window.clearTimeout(autoMockPollTimer)
    autoMockPollTimer = null
  }
}

const handleAutoMockJobCompletion = (parsedJob: ActiveJobState) => {
  if (parsedJob.job_type !== AUTO_MOCK_JOB_TYPE) return
  if (parsedJob.status !== 'SUCCESS' && parsedJob.status !== 'FAILED') return

  if (!handledAutoMockDoneJobIds.has(parsedJob.id)) {
    handledAutoMockDoneJobIds.add(parsedJob.id)
    if (parsedJob.status === 'SUCCESS') {
      const payload = parsedJob.result_json || {}
      const created = Number((payload as Record<string, unknown>).created_count || 0)
      const updated = Number((payload as Record<string, unknown>).updated_count || 0)
      notifySuccess(
        t('api_mock.ai_auto_mock_done_summary', {
          created: Number.isFinite(created) ? created : 0,
          updated: Number.isFinite(updated) ? updated : 0,
        }),
      )
    } else {
      ElMessage({
        type: 'error',
        message: parsedJob.message || t('api_mock.ai_auto_mock_failed'),
        duration: 2600,
        grouping: true,
      })
    }
  }

  const targetEndpointId = String((parsedJob.result_json?.target_endpoint_id as string) || '').trim()
  if (targetEndpointId && targetEndpointId === selectedEndpointId.value) {
    selectedMockCaseId.value = ''
    void loadMockCases()
  }
}

const pollActiveAutoMockJob = async () => {
  if (autoMockPolling) return
  const currentJob = activeAutoMockJob.value
  const workspaceId = String(wsId.value || '').trim()
  const taskId = String(selectedTaskId.value || '').trim()
  if (!currentJob || !workspaceId || !taskId) return
  if (currentJob.status !== 'PENDING' && currentJob.status !== 'RUNNING') return

  autoMockPolling = true
  try {
    const snapshot = await fetchJobSnapshot(currentJob.id, workspaceId, taskId)
    if (!snapshot || snapshot.job_type !== AUTO_MOCK_JOB_TYPE) {
      await loadActiveJobs()
      return
    }
    if (snapshot.status === 'SUCCESS' || snapshot.status === 'FAILED') {
      handleAutoMockJobCompletion(snapshot)
      return
    }
  } catch {
    // polling is a fallback path; keep silent and retry.
    await loadActiveJobs()
  } finally {
    autoMockPolling = false
  }

  const nextJob = activeAutoMockJob.value
  if (nextJob && (nextJob.status === 'PENDING' || nextJob.status === 'RUNNING')) {
    autoMockPollTimer = window.setTimeout(() => {
      autoMockPollTimer = null
      void pollActiveAutoMockJob()
    }, AUTO_MOCK_POLL_INTERVAL_MS)
  }
}

const closeSocket = () => {
  clearCollabReconnectTimer()
  if (collabSocket) {
    collabSocketManualClose = true
    collabSocket.close()
    collabSocket = null
  }
  collabConnected.value = false
  onlineUserIds.value = []
}

const connectCollab = () => {
  closeSocket()
  if (!project.value?.id) return
  const userId = authStore.user?.id || 'anonymous'
  const url = buildBackendWsUrl(`/ws/api-mock/${project.value.id}`, { userId })
  const socket = new WebSocket(url)
  collabSocket = socket
  socket.onopen = () => {
    if (collabSocket !== socket) return
    collabSocketManualClose = false
    clearCollabReconnectTimer()
    collabConnected.value = true
  }
  socket.onclose = () => {
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
      const data = JSON.parse(event.data || '{}')
      if (Array.isArray(data.online_users)) {
        onlineUserIds.value = data.online_users
          .map((item: unknown) => String(item || '').trim())
          .filter((item: string) => Boolean(item))
      }
      if (data?.type === 'job_update' || data?.type === 'job_done') {
        const parsedJob = toActiveJobState(data.job)
        if (parsedJob) {
          mergeIncomingJobState(parsedJob)
          mergeIncomingAutoMockJobState(parsedJob)
          if (data?.type === 'job_done') {
            handleAutoMockJobCompletion(parsedJob)
          }
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
    } catch {
      // ignore ws parse errors
    }
  }
}

const sendCollabEvent = (event: string, payload: Record<string, unknown>) => {
  if (!collabSocket || collabSocket.readyState !== WebSocket.OPEN) return
  collabSocket.send(JSON.stringify({ type: event, payload, endpoint_id: selectedEndpointId.value }))
}

const loadPermissions = async () => {
  const res = await api.get(`/workspaces/${wsId.value}/permissions/me`)
  permissions.value = res.data?.permissions || null
  permissionsReady.value = true
}

const loadWorkspaceMembers = async () => {
  const resultMap: Record<string, OnlinePresenceUser> = {}
  const pageSize = 100
  let page = 1
  while (true) {
    const res = await api.get(`/workspaces/${wsId.value}/members`, { params: { page, page_size: pageSize } })
    const owner = (res.data?.owner || null) as WorkspaceMemberProfile | null
    const items = Array.isArray(res.data?.items) ? (res.data.items as WorkspaceMemberProfile[]) : []
    const merged = owner ? [owner, ...items] : items
    for (const member of merged) {
      if (!member?.user_id) continue
      resultMap[member.user_id] = {
        id: member.user_id,
        displayName: member.display_name || member.email || member.user_id,
        email: member.email || '',
        avatarSvg: member.avatar_svg || null,
        avatarUrl: member.avatar_url || null,
      }
    }
    if (items.length < pageSize) break
    page += 1
  }
  workspaceMemberMap.value = resultMap
}

const loadTasks = async () => {
  const merged: TaskOption[] = []
  const pageSize = 100
  let page = 1
  while (true) {
    const res = await api.get(`/workspaces/${wsId.value}/tasks`, { params: { page, page_size: pageSize } })
    const items = Array.isArray(res.data?.items) ? res.data.items : []
    for (const item of items) {
      if (item?.id && item?.name) {
        merged.push({ id: item.id, name: item.name })
      }
    }
    if (items.length < pageSize) break
    page += 1
  }
  tasks.value = merged
}

const resetTaskContext = () => {
  project.value = null
  sourceVersions.value = []
  endpoints.value = []
  endpointCache.value = {}
  entities.value = []
  mockCases.value = []
  selectedEndpointId.value = ''
  selectedMockCaseId.value = ''
  documentData.value = null
  activeJob.value = null
  activeAutoMockJob.value = null
  autoMockStartBusy.value = false
  handledAutoMockDoneJobIds.clear()
  stopAutoMockPolling()
  closeSocket()
}

const loadProject = async () => {
  if (!selectedTaskId.value) return null
  const res = await api.get(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}`)
  project.value = res.data
  return res.data as ApiMockProject
}

const loadActiveJobs = async () => {
  if (!selectedTaskId.value) {
    activeJob.value = null
    activeAutoMockJob.value = null
    return []
  }
  const res = await api.get(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/jobs`, {
    params: {
      active_only: true,
      limit: 50,
    },
  })
  const items = ((res.data as ApiMockJobListResponse)?.items || [])
    .map((item) => toActiveJobState(item))
    .filter((item): item is ActiveJobState => Boolean(item))
  activeJob.value = items[0] || null
  activeAutoMockJob.value = items.find((item) => item.job_type === AUTO_MOCK_JOB_TYPE) || null
  return items
}

const loadSourceVersions = async () => {
  if (!selectedTaskId.value) return []
  const res = await api.get(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/source-versions`)
  sourceVersions.value = res.data.items || []
  return sourceVersions.value
}

const loadEndpoints = async () => {
  if (!selectedTaskId.value) return []
  const res = await api.get(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/endpoints`, {
    params: { keyword: endpointKeyword.value || undefined },
  })
  endpoints.value = res.data.items || []
  if (endpoints.value.length > 0) {
    const nextCache = { ...endpointCache.value }
    for (const endpoint of endpoints.value) {
      nextCache[endpoint.id] = endpoint
    }
    endpointCache.value = nextCache
  }
  return endpoints.value
}

const loadEntities = async () => {
  if (!selectedTaskId.value) return []
  const res = await api.get(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/entities`)
  entities.value = res.data.items || []
  return entities.value
}

const loadDocument = async () => {
  if (!project.value?.id || !currentSource.value) {
    documentData.value = null
    return
  }
  documentLoading.value = true
  try {
    const res = await api.get(`/workspaces/${wsId.value}/api-mock/projects/${project.value.id}/document`)
    documentData.value = res.data
  } catch (err) {
    documentData.value = null
    notifyError(err, t('api_mock.document_load_failed'))
  } finally {
    documentLoading.value = false
  }
}

const loadMockCases = async (options?: { fallbackToFirst?: boolean }) => {
  if (!selectedEndpointId.value) {
    mockCases.value = []
    selectedMockCaseId.value = ''
    return
  }
  const res = await api.get(`/workspaces/${wsId.value}/api-mock/endpoints/${selectedEndpointId.value}/mock-cases`)
  mockCases.value = res.data.items || []
  const shouldFallbackToFirst = options?.fallbackToFirst === true
  if (!mockCases.value.some((item) => item.id === selectedMockCaseId.value)) {
    selectedMockCaseId.value = shouldFallbackToFirst ? (mockCases.value[0]?.id || '') : ''
  }
}

const refreshProjectContext = async (options?: { preserveKey?: string; explicitEndpointId?: string }) => {
  if (!selectedTaskId.value) return
  loading.value = true
  try {
    await loadProject()
    await Promise.all([loadSourceVersions(), loadEndpoints(), loadEntities()])
    const explicitEndpointId = options?.explicitEndpointId || ''
    if (explicitEndpointId && endpoints.value.some((item) => item.id === explicitEndpointId)) {
      selectedEndpointId.value = explicitEndpointId
    } else if (options?.preserveKey) {
      const matched = endpoints.value.find((item) => endpointIdentity(item) === options.preserveKey)
      selectedEndpointId.value = matched?.id || ''
    } else if (!endpoints.value.some((item) => item.id === selectedEndpointId.value)) {
      selectedEndpointId.value = ''
    }
    await loadMockCases()
    await loadDocument()
    await loadActiveJobs()
    connectCollab()
  } finally {
    loading.value = false
  }
}

const fetchJobSnapshot = async (jobId: string, workspaceId: string, taskId: string) => {
  const res = await api.get(`/workspaces/${workspaceId}/api-mock/projects/${taskId}/jobs/${jobId}`)
  const parsedJob = toActiveJobState(res.data as ApiMockJob)
  if (parsedJob) {
    mergeIncomingJobState(parsedJob)
    mergeIncomingAutoMockJobState(parsedJob)
  }
  return parsedJob
}

const waitForJobDone = async (jobId: string, jobType: ActiveJobState['job_type'], queuedMessage: string) => {
  const workspaceId = String(wsId.value || '').trim()
  const taskId = String(selectedTaskId.value || '').trim()
  if (!workspaceId || !taskId) {
    throw new Error(t('api_mock.job_context_missing'))
  }
  const currentWaitSeq = ++jobWaitSeq

  activeJob.value = {
    id: jobId,
    job_type: jobType,
    status: 'PENDING',
    progress: 0,
    message: queuedMessage,
    result_json: null,
  }

  const startedAt = Date.now()
  while (Date.now() - startedAt < 6 * 60 * 1000) {
    if (currentWaitSeq !== jobWaitSeq) {
      return
    }

    let tracked = activeJob.value?.id === jobId ? activeJob.value : null
    try {
      const snapshot = await fetchJobSnapshot(jobId, workspaceId, taskId)
      if (snapshot) tracked = snapshot
    } catch (err) {
      if (currentWaitSeq !== jobWaitSeq) {
        return
      }
      throw err
    }

    if (tracked && (tracked.status === 'SUCCESS' || tracked.status === 'FAILED')) {
      if (tracked.status === 'SUCCESS') {
        notifySuccess(t('api_mock.job_success'))
        return
      }
      const payload = tracked.result_json as Record<string, unknown> | null
      const cancelled = Boolean(payload?.cancelled)
      throw new Error(cancelled ? t('api_mock.job_cancelled') : (tracked.message || t('api_mock.job_failed')))
    }
    await new Promise((resolve) => setTimeout(resolve, collabConnected.value ? 1200 : 900))
  }
  throw new Error(t('api_mock.job_timeout'))
}

const onSync = async () => {
  if (!selectedTaskId.value) return
  if (isProjectSwaggerMutationLocked.value) {
    notifyProjectSwaggerLocked()
    return
  }
  syncBusy.value = true
  try {
    const res = await api.post(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/sync`)
    await waitForJobDone(res.data.job_id, 'SYNC_TASK_SOURCE', t('api_mock.sync_queued'))
    await refreshProjectContext({ preserveKey: endpointIdentity(selectedEndpoint.value) })
  } catch (err) {
    if (isAutoMockProjectLockError(err)) {
      notifyProjectSwaggerLocked()
      await loadActiveJobs()
      return
    }
    notifyError(err, t('api_mock.sync_failed'))
  } finally {
    syncBusy.value = false
  }
}

const onImportSwagger = async (payload: { source_name?: string; raw_content?: string; file?: File | null }) => {
  if (!selectedTaskId.value) return
  if (isProjectSwaggerMutationLocked.value) {
    notifyProjectSwaggerLocked()
    return
  }
  importBusy.value = true
  try {
    console.log('Import payload received:', {
      source_name: payload.source_name,
      raw_content: payload.raw_content ? `${payload.raw_content.substring(0, 100)}...` : null,
      file: payload.file ? { 
        name: payload.file.name, 
        size: payload.file.size, 
        type: payload.file.type,
        lastModified: payload.file.lastModified
      } : null
    })
    
    const formData = new FormData()
    if (payload.source_name) formData.append('source_name', payload.source_name)
    if (payload.raw_content) formData.append('raw_content', payload.raw_content)
    if (payload.file) {
      console.log('File details:', {
        name: payload.file.name,
        size: payload.file.size,
        type: payload.file.type,
        lastModified: payload.file.lastModified
      })
      formData.append('file', payload.file, payload.file.name)
      console.log('File appended to FormData successfully')
    } else {
      console.log('No file in payload!')
    }
    
    const res = await api.post(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/swagger/import`, formData)
    await waitForJobDone(res.data.job_id, 'IMPORT_SWAGGER', t('api_mock.import_queued'))
    await refreshProjectContext({ preserveKey: endpointIdentity(selectedEndpoint.value) })
  } catch (err) {
    if (isAutoMockProjectLockError(err)) {
      notifyProjectSwaggerLocked()
      await loadActiveJobs()
      return
    }
    notifyError(err, t('api_mock.import_failed'))
  } finally {
    importBusy.value = false
  }
}

const onStartAutoMock = async () => {
  if (!selectedTaskId.value || !selectedEndpointId.value) return
  if (isAutoMockRunning.value) {
    ElMessage({
      type: 'warning',
      message: t('api_mock.ai_auto_mock_running'),
      duration: 2200,
      grouping: true,
    })
    return
  }
  autoMockStartBusy.value = true
  try {
    const res = await api.post(
      `/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/endpoints/${selectedEndpointId.value}/auto-mock`,
    )
    const jobId = String(res.data?.job_id || '').trim()
    activeAutoMockJob.value = {
      id: jobId,
      job_type: AUTO_MOCK_JOB_TYPE,
      status: 'PENDING',
      progress: 0,
      message: String(res.data?.message || t('api_mock.ai_auto_mock_running')),
      result_json: { target_endpoint_id: selectedEndpointId.value },
    }
    activeJob.value = activeAutoMockJob.value
    notifySuccess(t('api_mock.ai_auto_mock_started'))
    await loadActiveJobs()
  } catch (err) {
    if (isAutoMockProjectLockError(err)) {
      ElMessage({
        type: 'warning',
        message: t('api_mock.ai_auto_mock_locked_project_swagger_mutation'),
        duration: 2600,
        grouping: true,
      })
      await loadActiveJobs()
      return
    }
    notifyError(err, t('api_mock.ai_auto_mock_start_failed'))
  } finally {
    autoMockStartBusy.value = false
  }
}

const onCancelActiveJob = async () => {
  if (!selectedTaskId.value || !activeJob.value?.id) return
  cancelJobBusy.value = true
  try {
    const res = await api.post(
      `/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/jobs/${activeJob.value.id}/cancel`,
    )
    const parsedJob = toActiveJobState(res.data as ApiMockJob)
    if (parsedJob) {
      mergeIncomingJobState(parsedJob)
    }
    notifySuccess(t('api_mock.cancel_requested'))
  } catch (err) {
    notifyError(err, t('api_mock.cancel_failed'))
  } finally {
    cancelJobBusy.value = false
  }
}

const onActivateSource = async (sourceVersionId: string) => {
  if (!selectedTaskId.value) return
  if (isProjectSwaggerMutationLocked.value) {
    notifyProjectSwaggerLocked()
    return
  }
  try {
    const preserveKey = endpointIdentity(selectedEndpoint.value)
    await api.post(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/sources/activate`, {
      source_version_id: sourceVersionId,
    })
    notifySuccess(t('api_mock.source_switched'))
    await refreshProjectContext({ preserveKey })
  } catch (err) {
    if (isAutoMockProjectLockError(err)) {
      notifyProjectSwaggerLocked()
      await loadActiveJobs()
      return
    }
    notifyError(err, t('api_mock.switch_source_failed'))
  }
}

const onUpdateProxy = async (payload: { proxy_enabled: boolean; proxy_base_url: string }) => {
  if (!selectedTaskId.value) return
  try {
    await api.put(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}`, payload)
    if (project.value) {
      project.value.proxy_enabled = payload.proxy_enabled
      project.value.proxy_base_url = payload.proxy_base_url
    }
    notifySuccess(t('api_mock.proxy_saved'))
  } catch (err) {
    notifyError(err, t('api_mock.proxy_save_failed'))
  }
}

const onSaveEndpoint = async (payload: {
  row_version: number
  method: string
  path: string
  operation_id: string | null
  tag: string | null
  summary: string | null
  parameters_json: Array<Record<string, unknown>> | null
  request_schema_json: Record<string, unknown> | null
  responses_json: Record<string, unknown> | null
  response_schema_json: Record<string, unknown> | null
  entity_refs_json: string[] | null
}) => {
  if (!selectedTaskId.value || !selectedEndpointId.value) return
  if (isProjectSwaggerMutationLocked.value) {
    notifyProjectSwaggerLocked()
    return
  }
  savingEndpoint.value = true
  try {
    const res = await api.put(
      `/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/endpoints/${selectedEndpointId.value}`,
      payload,
    )
    selectedEndpointId.value = res.data.id
    await refreshProjectContext({ explicitEndpointId: res.data.id })
    sendCollabEvent('save', { endpoint_id: res.data.id, target: 'endpoint' })
    notifySuccess(t('api_mock.endpoint_saved'))
  } catch (err) {
    if (isAutoMockProjectLockError(err)) {
      notifyProjectSwaggerLocked()
      await loadActiveJobs()
      return
    }
    if (isConflictError(err)) {
      sendCollabEvent('conflict', { endpoint_id: selectedEndpointId.value, target: 'endpoint' })
      await refreshProjectContext({ preserveKey: `${payload.method.toUpperCase()} ${payload.path}` })
      notifyError(err, t('api_mock.conflict_detected'))
    } else {
      notifyError(err, t('api_mock.endpoint_save_failed'))
    }
  } finally {
    savingEndpoint.value = false
  }
}

const onSaveDocument = async (payload: { content: string }) => {
  if (!project.value?.id) return
  if (isProjectSwaggerMutationLocked.value) {
    notifyProjectSwaggerLocked()
    return
  }
  savingDocument.value = true
  const preserveKey = endpointIdentity(selectedEndpoint.value)
  try {
    await api.put(`/workspaces/${wsId.value}/api-mock/projects/${project.value.id}/document`, payload)
    await refreshProjectContext({ preserveKey })
    sendCollabEvent('save', { endpoint_id: selectedEndpointId.value, target: 'document' })
    notifySuccess(t('api_mock.document_saved'))
  } catch (err) {
    if (isAutoMockProjectLockError(err)) {
      notifyProjectSwaggerLocked()
      await loadActiveJobs()
      return
    }
    notifyError(err, t('api_mock.document_save_failed'))
  } finally {
    savingDocument.value = false
  }
}

const onCreateCase = () => {
  if (isCurrentEndpointAutoMockLocked.value) {
    notifyCurrentEndpointCreateLocked()
    return
  }
  selectedMockCaseId.value = ''
}

const onSaveCase = async (payload: {
  id?: string
  row_version?: number
  name: string
  description: string | null
  is_default: boolean
  sort_order?: number
  mode: 'STATIC' | 'MOCKJS' | 'PROXY'
  request_path_params_json?: Record<string, unknown> | null
  request_query_json?: Record<string, unknown> | null
  request_body_json?: unknown
  static_body_json?: Record<string, unknown> | null
  mockjs_template?: string | null
  status_code: number
  headers_json?: Record<string, unknown> | null
  cookies_json?: Array<Record<string, unknown>> | null
  delay_ms: number
  enabled: boolean
}) => {
  if (!selectedEndpointId.value) return
  if (!payload.id && isCurrentEndpointAutoMockLocked.value) {
    notifyCurrentEndpointCreateLocked()
    return
  }
  savingCase.value = true
  try {
    if (payload.id) {
      const res = await api.put(`/workspaces/${wsId.value}/api-mock/mock-cases/${payload.id}`, payload)
      selectedMockCaseId.value = res.data.id
    } else {
      const res = await api.post(`/workspaces/${wsId.value}/api-mock/endpoints/${selectedEndpointId.value}/mock-cases`, payload)
      selectedMockCaseId.value = res.data.id
    }
    await loadMockCases()
    sendCollabEvent('save', { endpoint_id: selectedEndpointId.value, target: 'mock-case' })
    notifySuccess(t('api_mock.mock_case_saved'))
  } catch (err) {
    if (isAutoMockEndpointLockError(err)) {
      notifyCurrentEndpointCreateLocked()
      await loadActiveJobs()
      return
    }
    if (isConflictError(err)) {
      sendCollabEvent('conflict', { endpoint_id: selectedEndpointId.value, target: 'mock-case' })
      await loadMockCases()
      notifyError(err, t('api_mock.conflict_detected'))
    } else {
      notifyError(err, t('api_mock.mock_case_save_failed'))
    }
  } finally {
    savingCase.value = false
  }
}

const onDeleteCase = async (caseId: string) => {
  deletingCase.value = true
  try {
    await api.delete(`/workspaces/${wsId.value}/api-mock/mock-cases/${caseId}`)
    await loadMockCases()
    notifySuccess(t('api_mock.mock_case_deleted'))
  } catch (err) {
    notifyError(err, t('api_mock.mock_case_delete_failed'))
  } finally {
    deletingCase.value = false
  }
}

const onCreateEntity = async (payload: { name: string; description: string | null; schema_json: Record<string, unknown>; endpoint_id: string | null }) => {
  if (!selectedTaskId.value) return
  if (isProjectSwaggerMutationLocked.value) {
    notifyProjectSwaggerLocked()
    return
  }
  try {
    await api.post(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/entities`, {
      name: payload.name,
      description: payload.description,
      schema_json: payload.schema_json,
      endpoint_id: payload.endpoint_id,
    })
    await loadEntities()
    notifySuccess(t('api_mock.entity_saved'))
  } catch (err) {
    if (isAutoMockProjectLockError(err)) {
      notifyProjectSwaggerLocked()
      await loadActiveJobs()
      return
    }
    notifyError(err, t('api_mock.entity_save_failed'))
  }
}

const onUpdateEntity = async (payload: { id: string; row_version: number; name: string; description: string | null; schema_json: Record<string, unknown>; endpoint_id: string | null }) => {
  if (!selectedTaskId.value) return
  if (isProjectSwaggerMutationLocked.value) {
    notifyProjectSwaggerLocked()
    return
  }
  try {
    await api.put(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/entities/${payload.id}`, {
      row_version: payload.row_version,
      name: payload.name,
      description: payload.description,
      schema_json: payload.schema_json,
      endpoint_id: payload.endpoint_id,
    })
    await loadEntities()
    notifySuccess(t('api_mock.entity_saved'))
  } catch (err) {
    if (isAutoMockProjectLockError(err)) {
      notifyProjectSwaggerLocked()
      await loadActiveJobs()
      return
    }
    if (isConflictError(err)) {
      await loadEntities()
      notifyError(err, t('api_mock.conflict_detected'))
    } else {
      notifyError(err, t('api_mock.entity_save_failed'))
    }
  }
}

const onDeleteEntity = async (entityId: string) => {
  if (isProjectSwaggerMutationLocked.value) {
    notifyProjectSwaggerLocked()
    return
  }
  try {
    await api.delete(`/workspaces/${wsId.value}/api-mock/projects/${selectedTaskId.value}/entities/${entityId}`)
    await loadEntities()
    notifySuccess(t('api_mock.entity_deleted'))
  } catch (err) {
    if (isAutoMockProjectLockError(err)) {
      notifyProjectSwaggerLocked()
      await loadActiveJobs()
      return
    }
    notifyError(err, t('api_mock.entity_delete_failed'))
  }
}

const handleTaskPicked = (taskId: string) => {
  selectedTaskId.value = taskId
  showSideTaskPicker.value = false
}

const handleSelectEndpoint = async (endpointId: string) => {
  selectedEndpointId.value = endpointId
  selectedMockCaseId.value = ''
  await loadMockCases()
  sendCollabEvent('draft', { endpoint_id: endpointId })
}

const openGlobalEntityDrawer = () => {
  if (!canManageSwagger.value) {
    notifyProjectSwaggerLocked()
    return
  }
  showGlobalEntityDrawer.value = true
  setTimeout(() => {
    globalEntityDrawerRef.value?.openCreateForm()
  }, 100)
}

const onShortcuts = (event: KeyboardEvent) => {
  const ctrlOrMeta = event.ctrlKey || event.metaKey
  const key = event.key.toLowerCase()
  if (key === '?' && !ctrlOrMeta) {
    event.preventDefault()
    showShortcuts.value = true
    return
  }
  if (ctrlOrMeta && key === 'k') {
    event.preventDefault()
    endpointCatalogRef.value?.focusSearch()
    return
  }
  if (ctrlOrMeta && key === 's') {
    event.preventDefault()
    if (canManageSwagger.value && selectedEndpoint.value) {
      workspaceRef.value?.triggerPrimarySave()
    }
    return
  }
  if (ctrlOrMeta && event.shiftKey && key === 'p') {
    event.preventDefault()
    if (project.value && canPublish.value) {
      onUpdateProxy({
        proxy_enabled: !project.value.proxy_enabled,
        proxy_base_url: project.value.proxy_base_url || '',
      })
    }
  }
}

watch(selectedTaskId, async (next, prev) => {
  if (next === prev) return
  showSideTaskPicker.value = false
  endpointKeyword.value = ''
  if (!next) {
    resetTaskContext()
    return
  }
  resetTaskContext()
  await refreshProjectContext()
})

watch(endpointKeyword, () => {
  if (!selectedTaskId.value) return
  if (keywordTimer !== null) {
    window.clearTimeout(keywordTimer)
  }
  keywordTimer = window.setTimeout(async () => {
    keywordTimer = null
    await loadEndpoints()
  }, 260)
})

watch(
  activeAutoMockJob,
  (job) => {
    stopAutoMockPolling()
    if (!job) return
    if (job.status !== 'PENDING' && job.status !== 'RUNNING') return
    autoMockPollTimer = window.setTimeout(() => {
      autoMockPollTimer = null
      void pollActiveAutoMockJob()
    }, 350)
  },
  { deep: true },
)

onMounted(async () => {
  window.addEventListener('keydown', onShortcuts)
  if (!authStore.user) {
    await authStore.fetchCurrentUser()
  }
  try {
    await loadPermissions()
    if (!canView.value) {
      pageError.value = t('api_mock.no_view_permission')
      return
    }
    await Promise.all([loadWorkspaceMembers(), loadTasks()])
  } catch (err) {
    pageError.value = formatApiError(err, t('api_mock.load_failed'), t)
    notifyError(err, t('api_mock.load_failed'))
  }
})

onBeforeUnmount(() => {
  jobWaitSeq += 1
  stopAutoMockPolling()
  clearCollabReconnectTimer()
  if (keywordTimer !== null) {
    window.clearTimeout(keywordTimer)
    keywordTimer = null
  }
  window.removeEventListener('keydown', onShortcuts)
  closeSocket()
})
</script>

<template>
  <div class="api-mock-page">
    <ApiMockTaskBar
      v-if="selectedTaskId"
      :selected-task-name="selectedTask?.name || ''"
      :current-source-label="currentSourceLabel"
      :can-view="canView"
      :active-job="activeJob"
      :swagger-mutation-locked="isProjectSwaggerMutationLocked"
      :collab-connected="collabConnected"
      :online-users="onlineUsers"
      @open-config="(mode: string) => { configDrawerMode = mode as 'sync' | 'versions' | 'proxy' | 'import'; showConfigDrawer = true }"
    />

    <section v-if="permissionsReady && !canView" class="state-panel glass-panel">
      <h2>{{ $t('api_mock.no_view_permission') }}</h2>
      <p>{{ pageError || $t('api_mock.load_failed') }}</p>
    </section>

    <section v-else-if="!selectedTaskId" class="workbench-grid empty-workbench-grid">
      <div class="workbench-sidebar">
        <section class="task-side-panel glass-panel">
          <ApiMockTaskPickerPanel
            :tasks="tasks"
            :model-value="selectedTaskId"
            @update:model-value="handleTaskPicked"
          />
        </section>
      </div>

      <section class="state-panel glass-panel empty-canvas-panel">
        <span class="state-kicker">API MOCK</span>
        <h2>{{ $t('api_mock.task_empty') }}</h2>
        <p>{{ $t('api_mock.task_canvas_hint') }}</p>
      </section>
    </section>

    <section v-else class="workbench-grid">
      <div class="workbench-sidebar">
        <section class="task-side-panel glass-panel current-task-panel">
          <div class="task-side-head">
            <div>
              <span class="state-kicker">{{ $t('api_mock.task_ready') }}</span>
              <strong>{{ selectedTask?.name }}</strong>
              <p>{{ selectedTask?.id }}</p>
            </div>

            <button type="button" class="btn-secondary task-side-toggle" @click="showSideTaskPicker = !showSideTaskPicker">
              {{ showSideTaskPicker ? $t('api_mock.collapse_task_picker') : $t('api_mock.change_task') }}
            </button>
          </div>

          <div v-if="showSideTaskPicker" class="task-side-picker">
            <ApiMockTaskPickerPanel
              :tasks="tasks"
              :model-value="selectedTaskId"
              compact
              @update:model-value="handleTaskPicked"
            />
          </div>
        </section>

        <ApiMockEndpointCatalog
          ref="endpointCatalogRef"
          class="catalog-shell"
          :endpoints="endpoints"
          :selected-endpoint-id="selectedEndpointId"
          :keyword="endpointKeyword"
          :can-view="canView"
          @update:keyword="endpointKeyword = $event"
          @select="handleSelectEndpoint"
          @create-global-entity="openGlobalEntityDrawer"
        />
      </div>

      <ApiMockEndpointWorkspace
        ref="workspaceRef"
        :endpoint="selectedEndpoint"
        :entities="entities"
        :document="documentData"
        :document-loading="documentLoading"
        :can-manage="canManageSwagger"
        :can-manage-mock="canManage"
        :swagger-mutation-locked="isProjectSwaggerMutationLocked"
        :project-auto-mock-locked="isAutoMockRunning"
        :current-endpoint-auto-mock-locked="isCurrentEndpointAutoMockLocked"
        :auto-mock-busy="autoMockStartBusy"
        :auto-mock-job="activeAutoMockJob"
        :saving-endpoint="savingEndpoint"
        :saving-document="savingDocument"
        :cases="mockCases"
        :selected-case-id="selectedMockCaseId"
        :saving-case="savingCase"
        :deleting-case="deletingCase"
        :ws-id="wsId"
        :task-id="selectedTaskId"
        @save-endpoint="onSaveEndpoint"
        @save-document="onSaveDocument"
        @select-case="selectedMockCaseId = $event"
        @create-case="onCreateCase"
        @save-case="onSaveCase"
        @delete-case="onDeleteCase"
        @start-auto-mock="onStartAutoMock"
        @create-entity="onCreateEntity"
        @update-entity="onUpdateEntity"
        @delete-entity="onDeleteEntity"
      />
    </section>

    <ApiMockConfigDrawer
      :open="showConfigDrawer"
      :drawer-mode="configDrawerMode"
      :task-name="selectedTask?.name || ''"
      :project="project"
      :source-versions="sourceVersions"
      :can-manage="canManage"
      :can-publish="canPublish"
      :sync-busy="syncBusy"
      :import-busy="importBusy"
      :cancel-busy="cancelJobBusy"
      :active-job="activeJob"
      :swagger-mutation-locked="isProjectSwaggerMutationLocked"
      @close="showConfigDrawer = false"
      @sync="onSync"
      @cancel-job="onCancelActiveJob"
      @activate-source="onActivateSource"
      @update-proxy="onUpdateProxy"
      @import-swagger="onImportSwagger"
    />

    <ApiMockGlobalEntityDrawer
      ref="globalEntityDrawerRef"
      :open="showGlobalEntityDrawer"
      :entities="entities"
      :can-manage="canManageSwagger"
      @close="showGlobalEntityDrawer = false"
      @create-entity="onCreateEntity"
      @update-entity="onUpdateEntity"
      @delete-entity="onDeleteEntity"
    />

    <ShortcutHelpModal :show="showShortcuts" @close="showShortcuts = false" />
  </div>
</template>

<style scoped>
.api-mock-page {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.15rem;
  min-height: 100%;
}

.workbench-grid {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: 1rem;
  min-height: calc(100vh - 240px);
}

.empty-workbench-grid {
  min-height: calc(100vh - 160px);
}

.workbench-sidebar {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-height: 0;
}

.catalog-shell {
  flex: 1;
  min-height: 0;
}

.state-panel {
  min-height: 22rem;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 0.8rem;
  padding: 1.4rem;
  background: #ffffff;
  border: 1px solid #e2e8f0;
}

.state-kicker {
  color: #0369a1;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.state-panel h2 {
  margin: 0.5rem 0 0;
  font-size: 1.8rem;
}

.state-panel p {
  margin: 0;
  max-width: 30rem;
  color: #64748b;
  line-height: 1.7;
}

.task-side-panel {
  padding: 1rem;
  border: 1px solid #e2e8f0;
  background: #ffffff;
}

.current-task-panel {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}

.task-side-head {
  display: flex;
  justify-content: space-between;
  gap: 0.8rem;
  align-items: flex-start;
}

.task-side-head strong {
  display: block;
  margin-top: 0.32rem;
  color: #0f172a;
  font-size: 1rem;
}

.task-side-head p {
  margin: 0.24rem 0 0;
  color: #64748b;
  font-size: 0.8rem;
  line-height: 1.5;
  word-break: break-all;
}

.task-side-toggle {
  flex-shrink: 0;
  min-height: 2.8rem;
  border-radius: 16px;
  font-weight: 700;
}

.task-side-picker {
  padding-top: 0.2rem;
}

.empty-canvas-panel {
  min-height: 0;
}

.empty-canvas-panel h2 {
  margin-top: 0.1rem;
}

.w-5 {
  width: 1.25rem;
  height: 1.25rem;
}

@media (max-width: 1200px) {
  .workbench-grid {
    grid-template-columns: 1fr;
    min-height: auto;
  }
}

@media (max-width: 900px) {
  .api-mock-page {
    padding: 0.85rem;
  }

  .task-side-head {
    flex-direction: column;
  }
}
</style>
