import { ref, onMounted, onUnmounted, nextTick, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import api from '@/utils/api'
import { ElMessage } from 'element-plus'
import { formatApiError } from '@/utils/error'
import { formatTime, formatToolInput } from '@/utils/chatFormatters'
import { buildBackendWsUrl } from '@/utils/ws'
import { useTaskSessionControls } from '@/composables/useTaskSessionControls'
import { useTaskContextWindow } from '@/composables/useTaskContextWindow'
import { useChatDecision, type ChatDecisionPayload } from '@/composables/useChatDecision'
import { useTaskSkillRuntimeTrace } from '@/composables/useTaskSkillRuntimeTrace'
import { useAuthStore } from '@/stores/auth'
import type { ContextCompactionLocatePayload, ContextTokenCategory } from '@/types/contextWindow'
import type { SkillRuntimeEvent } from '@/types/runtimeSkillTrace'
import {
  normalizeDiagnosisPayload,
  type DiagnosisResultPayload,
} from '@/types/diagnosis'


export function useChatViewModel() {
  const { t } = useI18n()
  
  const route = useRoute()
  const router = useRouter()
  const authStore = useAuthStore()
  const taskSessionControls = useTaskSessionControls({
    getWorkspaceId: () => String(route.params.wsId || ''),
  })
  
  type ChatAiJobStatus = 'PENDING' | 'RUNNING' | 'WAITING_HITL' | 'INTERRUPTED' | 'SUCCESS' | 'FAILED' | 'CANCELLED'
  type ChatAiJob = {
    id: string
    task_id?: string | null
    status: ChatAiJobStatus
    progress: number
    message?: string | null
    error_message?: string | null
    context_json?: Record<string, any> | null
  }
  type SpecBootstrapStatus = 'PENDING' | 'RUNNING' | 'READY' | 'FAILED' | 'STALE'
  type TaskSpecBootstrap = {
    task_id: string
    workspace_id: string
    spec_asset_id?: string | null
    spec_version_id?: string | null
    status: SpecBootstrapStatus
    progress: number
    message?: string | null
    baseline_session_id?: string | null
    error_message?: string | null
    updated_at?: string | null
  }
  type SpecDrawerLevel = 0 | 1 | 2 | 3
  type OpenSpecDrawerLevel = 1 | 2 | 3
  type SpecDrawerTab = 'spec_doc' | 'superpowers_docs'
  type TaskSessionFilter = 'ALL' | 'DONE' | 'FAILED'
  type ChatWorkbenchMode = 'platform' | 'cli'
  type RuntimeSkillUsage = {
    is_used: boolean
    used_count: number
    last_used_at?: string | null
    usage_scope_start_at?: string | null
  }
  type RuntimeSkillItem = {
    skill_id: string
    name: string
    description?: string | null
    dimension: 'GLOBAL' | 'WORKSPACE' | string
    publish_state?: 'PUBLISHED' | 'DRAFT' | string
    has_pending_changes?: boolean
    changed_files_count?: number
    materialized_dir?: string | null
    is_materialized?: boolean
    config_deleted?: boolean
    usage?: RuntimeSkillUsage
  }
  type RuntimeSkillFileNode = {
    path: string
    name: string
    node_type: 'file' | 'directory'
    size?: number | null
    children?: RuntimeSkillFileNode[]
  }

  const CHAT_WORKBENCH_MODE_KEY = 'sdd.chat.workbench.mode'
  
  // ─── State ───
  const tasks = ref<any[]>([])
  const currentTask = ref<any>(null)
  const chatInput = ref('')
  const sendingChat = ref(false)
  const currentWorkspace = ref<any>(null)
  const workspacePermissions = ref<any>(null)
  const workspaceCurrentUserIsExpert = ref(false)
  const taskListContainer = ref<HTMLElement | null>(null)
  const taskStatusFilter = ref<TaskSessionFilter>('ALL')
  const taskListPage = ref(1)
  const taskListTotal = ref(0)
  const taskListLoading = ref(false)
  const taskListLoadingMore = ref(false)
  const TASK_LIST_PAGE_SIZE = 20
  
  // Chat bubbles: 仅自然语言 (user / assistant text)
  const messages = ref<any[]>([])
  
  // 终端日志面板：tool_use, tool_result, raw logs
  const terminalLogs = ref<any[]>([])
  const highlightedMessageId = ref('')
  const highlightedTerminalLogId = ref('')
  const chatWorkbenchMode = ref<ChatWorkbenchMode>('platform')
  const specDrawerLevel = ref<SpecDrawerLevel>(0)
  const lastOpenSpecDrawerLevel = ref<OpenSpecDrawerLevel>(1)
  const specDrawerTab = ref<SpecDrawerTab>('spec_doc')
  const preferredSpecAssetId = ref('')
  const preferredSpecTaskId = ref('')
  const specBootstrap = ref<TaskSpecBootstrap | null>(null)
  const specBootstrapLoading = ref(false)
  
  // 分页状�?
  const currentPage = ref(1)
  const hasMore = ref(false)
  const loadingMore = ref(false)
  
  // 置顶富文本卡片区：HITL, status, result (独立于对话流)
  const pinnedCards = ref<any[]>([])
  const activeChatJobs = ref<Record<string, ChatAiJob>>({})
  let referenceHighlightTimer: number | null = null
  
  // AI 思考面�?
  const thinkingContent = ref('')
  const showThinking = ref(false)
  const thinkingExpanded = ref(false)
  const resetThinkingPanel = () => {
    thinkingContent.value = ''
    showThinking.value = false
    thinkingExpanded.value = false
  }
  
  // 运行状况总览
  const resultsSummary = ref({
    visible: false,
    totalDurationMs: 0,
    totalCostUsd: 0,
    history: [] as any[],
    expanded: false
  })
  
  // Task creation modal
  const showTaskModal = ref(false)
  const showDeleteTaskConfirm = ref(false)
  const showStartConfirm = ref(false)
  const showInterruptConfirm = ref(false)
  const showCompleteConfirm = ref(false)
  const closeoutMode = ref<'complete' | 'fail' | null>(null)
  const decisionModalOpen = ref(false)
  const decisionSourceMessage = ref<any>(null)
  const showDeletedRuntimeSkillConfirm = ref(false)
  const interruptOverlayCloseArmed = ref(false)
  const completeOverlayCloseArmed = ref(false)
  const taskToDelete = ref<any>(null)
  const deletingTask = ref(false)
  const startingTask = ref(false)
  
  // Engine state
  const engineRunning = ref(false)
  const showInitReasonModal = ref(false)
  const initReason = ref('')
  const initSkillOptionsLoading = ref(false)
  const initSkillOptions = ref<any[]>([])
  const initSelectedSkillIds = ref<string[]>([])

  const showTaskSkillsDrawer = ref(false)
  const taskRuntimeSkillsLoading = ref(false)
  const taskRuntimeSkills = ref<RuntimeSkillItem[]>([])
  const taskRuntimeSkillsUsageScopeStartAt = ref<string | null>(null)
  const runtimeActiveSkillId = ref('')
  const runtimeFileTreeLoading = ref(false)
  const runtimeFileTree = ref<RuntimeSkillFileNode[]>([])
  const runtimeActiveFilePath = ref('')
  const runtimeActiveFileLoading = ref(false)
  const runtimeActiveFileSaving = ref(false)
  const runtimeActiveFileContent = ref('')
  const runtimeActiveFileOriginalContent = ref('')
  const runtimeActiveFileBinary = ref(false)
  let runtimeUsageRefreshTimer: number | null = null
  const {
    runtimeTraceEvents,
    runtimeTraceLoading,
    loadRuntimeTraceEvents,
    appendRuntimeTraceEvent,
    resetRuntimeTraceEvents,
  } = useTaskSkillRuntimeTrace()
  const contextWindowDrawerOpen = ref(false)
  const contextWindowDrawerLevel = ref<OpenSpecDrawerLevel>(1)
  let contextWindowRefreshTimer: number | null = null
  const contextWindow = useTaskContextWindow({
    getWorkspaceId: () => String(route.params.wsId || ''),
    getTaskId: () => String(currentTask.value?.id || ''),
    getAiJobId: () => {
      const activeJob = Object.values(activeChatJobs.value).find((job) => (
        job.status === 'PENDING'
        || job.status === 'RUNNING'
        || job.status === 'WAITING_HITL'
        || job.status === 'INTERRUPTED'
      ))
      return activeJob?.id || null
    },
  })
  const chatDecision = useChatDecision()
  
  // WebSocket
  let ws: WebSocket | null = null
  let wsReconnectTimer: number | null = null
  let wsManualClose = false
  
  const hasTaskSpecDoc = (task: any): boolean => {
    return Boolean(String(task?.spec_doc_path || '').trim())
  }
  
  const hasTaskSpecification = (task: any): boolean => {
    if (!task) return false
    if (hasTaskSpecDoc(task)) return true
    return String(task?.id || '') === preferredSpecTaskId.value && Boolean(preferredSpecAssetId.value)
  }
  
  // ─── Computed ───
  const activeHitlCards = computed(() =>
    pinnedCards.value.filter(c => c.type === 'hitl' && !c.answered)
  )
  const taskListHasMore = computed(() => tasks.value.length < taskListTotal.value)
  const isTerminalStatus = computed(() => 
    ['DONE', 'FAILED'].includes(currentTask.value?.status)
  )
  const statusCards = computed(() =>
    pinnedCards.value.filter(c => c.type === 'status')
  )
  const canCreateTask = computed(() => Boolean(workspacePermissions.value?.create_task))
  const canStartTask = computed(() => Boolean(workspacePermissions.value?.start_task))
  const canManageTaskStatus = computed(() => Boolean(workspacePermissions.value?.manage_task_status))
  const canDeleteTask = computed(() => Boolean(workspacePermissions.value?.delete_task))
  const canExportTask = computed(() => Boolean(workspacePermissions.value?.export_task))
  const canEditSuperpowersDocs = computed(() => (
    Boolean(workspacePermissions.value?.upload_task_spec || workspacePermissions.value?.manage_task_status)
  ))
  const isTaskPreStart = computed(() => currentTask.value?.status === 'PENDING')
  const isTaskInterrupted = computed(() => currentTask.value?.status === 'INTERRUPTED')
  const isStartActionVisible = computed(() => Boolean(currentTask.value) && isTaskPreStart.value)
  const canClickStartAction = computed(() => (
    isStartActionVisible.value && canStartTask.value && !startingTask.value
  ))
  const canInitializeAction = computed(() => (
    Boolean(currentTask.value) && !isTaskPreStart.value && canManageTaskStatus.value
  ))
  const currentTaskHasSpec = computed(() => hasTaskSpecification(currentTask.value))
  const isSuperpowersDocsAvailable = computed(() => Boolean(currentTask.value) && !isTaskPreStart.value)
  // 问题定位任务：不展示需求文档抽屉（spec drawer），改用诊断文档/代码路径抽屉
  const showSpecEntryButton = computed(() => (currentTaskHasSpec.value || isSuperpowersDocsAvailable.value) && !isDiagnosisTask.value)
  const isSpecDrawerAvailable = computed(() => (
    (currentTaskHasSpec.value || isSuperpowersDocsAvailable.value) && !isTaskPreStart.value && !isDiagnosisTask.value
  ))
  const isSpecPanelOpen = computed(() => specDrawerLevel.value > 0)
  const isChatLocked = computed(() => isTerminalStatus.value || isTaskPreStart.value)

  // 问题定位任务：诊断文档/代码路径抽屉
  const diagnosisDocsDrawerOpen = ref(false)
  const toggleDiagnosisDocsDrawer = () => {
    diagnosisDocsDrawerOpen.value = !diagnosisDocsDrawerOpen.value
  }
  const closeDiagnosisDocsDrawer = () => {
    diagnosisDocsDrawerOpen.value = false
  }

  const localUserMessageMeta = () => ({
    creator_id: authStore.user?.id || null,
    creator_display_name: authStore.user?.display_name || 'You',
    creator_is_workspace_expert: workspaceCurrentUserIsExpert.value || Boolean(currentWorkspace.value?.my_is_expert),
  })

  const generateClientMessageId = (): string => {
    const cryptoApi = globalThis.crypto
    if (cryptoApi?.randomUUID) return cryptoApi.randomUUID()
    return `msg-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  }

  const releaseSendingChatSoon = () => {
    window.setTimeout(() => {
      sendingChat.value = false
    }, 250)
  }

  const messageIdentity = (msg: any): string => {
    const clientMessageId = String(msg?.client_message_id || '').trim()
    if (clientMessageId) return `client:${clientMessageId}`
    const id = String(msg?.id || '').trim()
    return id ? `id:${id}` : ''
  }

  const dedupeMessages = (items: any[]): any[] => {
    const indexByKey = new Map<string, number>()
    const result: any[] = []
    for (const item of items) {
      const key = messageIdentity(item)
      if (!key) {
        result.push(item)
        continue
      }
      const existingIndex = indexByKey.get(key)
      if (existingIndex === undefined) {
        indexByKey.set(key, result.length)
        result.push(item)
        continue
      }
      result[existingIndex] = {
        ...result[existingIndex],
        ...item,
      }
    }
    return result
  }

  const upsertChatMessage = (item: any) => {
    const key = messageIdentity(item)
    if (!key) {
      messages.value.push(item)
      return
    }
    const index = messages.value.findIndex(existing => messageIdentity(existing) === key)
    if (index >= 0) {
      messages.value[index] = {
        ...messages.value[index],
        ...item,
      }
      return
    }
    messages.value.push(item)
  }

  const isMessageFromCurrentUser = (msg: any): boolean => {
    const creatorId = String(msg?.creator_id || '').trim()
    const currentUserId = String(authStore.user?.id || '').trim()
    return Boolean(creatorId && currentUserId && creatorId === currentUserId)
  }

  const messageAuthorLabel = (msg: any): string => {
    const role = String(msg?.role || '').toLowerCase()
    if (role === 'assistant') return 'Claude'
    if (role === 'system') return 'System'
    if (isMessageFromCurrentUser(msg)) return 'You'
    return String(msg?.creator_display_name || '').trim() || 'Member'
  }

  const isMessageWorkspaceExpert = (msg: any): boolean => (
    String(msg?.role || '').toLowerCase() === 'user' && Boolean(msg?.creator_is_workspace_expert)
  )

  const formatMessageTime = (isoStr: string): string => {
    if (!isoStr) return ''
    return new Date(isoStr).toLocaleTimeString([], {
      hour: 'numeric',
      minute: '2-digit',
      second: '2-digit',
    })
  }
  const chatInputPlaceholder = computed(() => {
    if (isTaskPreStart.value) return t('chat.start_before_chat')
    if (isTerminalStatus.value) return t('chat.terminal_status_hint')
    if (isTaskInterrupted.value) return t('chat.resume_interrupted_placeholder')
    return t('dashboard.desc_placeholder')
  })
  const canTemporarilyInterrupt = computed(() => (
    Boolean(currentTask.value?.id)
    && engineRunning.value
    && canManageTaskStatus.value
    && !taskSessionControls.interruptingTask.value
  ))
  const isSpecBootstrapActive = computed(() => (
    specBootstrap.value?.status === 'PENDING' || specBootstrap.value?.status === 'RUNNING'
  ))
  const activeInitialSpecAssetId = computed(() => (
    currentTask.value?.id && currentTask.value.id === preferredSpecTaskId.value
      ? preferredSpecAssetId.value
      : ''
  ))
  const canEditTaskRuntimeSkills = computed(() => (
    Boolean(currentTask.value) && canManageTaskStatus.value
  ))
  const taskRuntimeSkillCount = computed(() => taskRuntimeSkills.value.length)
  const runtimeActiveSkill = computed(() => (
    taskRuntimeSkills.value.find((item) => item.skill_id === runtimeActiveSkillId.value) || null
  ))
  const deletedRuntimeSkillsForInitialize = computed(() => taskRuntimeSkills.value.filter((item) => (
    Boolean(item.config_deleted) || String(item.skill_id || '').startsWith('runtime:')
  )))
  const deletedRuntimeSkillNamesForInitialize = computed(() => deletedRuntimeSkillsForInitialize.value
    .map((skill) => String(skill.name || skill.materialized_dir || skill.skill_id || '').trim())
    .filter(Boolean))
  const activeInitSkillOptionIds = computed(() => new Set(
    initSkillOptions.value.map((item) => String(item.id || '').trim()).filter(Boolean),
  ))
  const runtimeActiveFileDirty = computed(() => (
    !runtimeActiveFileBinary.value
    && runtimeActiveFilePath.value.length > 0
    && runtimeActiveFileContent.value !== runtimeActiveFileOriginalContent.value
  ))

  const setChatWorkbenchMode = (mode: ChatWorkbenchMode) => {
    chatWorkbenchMode.value = mode
    localStorage.setItem(CHAT_WORKBENCH_MODE_KEY, mode)
  }

  const restoreChatWorkbenchMode = () => {
    const cached = String(localStorage.getItem(CHAT_WORKBENCH_MODE_KEY) || '').toLowerCase()
    if (cached === 'cli') {
      chatWorkbenchMode.value = 'cli'
      return
    }
    chatWorkbenchMode.value = 'platform'
  }
  
  const isForbiddenError = (error: unknown): boolean => {
    const status = (error as { response?: { status?: number } })?.response?.status
    return status === 403
  }
  
  const resolveActionError = (
    error: unknown,
    fallbackKey: string,
    noPermissionKey: string,
  ): string => {
    if (isForbiddenError(error)) {
      return t(noPermissionKey)
    }
    return formatApiError(error, t(fallbackKey), t)
  }
  
  const armInlineOverlayClose = (target: 'interrupt' | 'complete', event: PointerEvent) => {
    if (event.button !== 0) return
    if (target === 'interrupt') {
      interruptOverlayCloseArmed.value = true
      return
    }
    completeOverlayCloseArmed.value = true
  }
  
  const cancelInlineOverlayClose = (target: 'interrupt' | 'complete') => {
    if (target === 'interrupt') {
      interruptOverlayCloseArmed.value = false
      return
    }
    completeOverlayCloseArmed.value = false
  }
  
  const finishInlineOverlayClose = (target: 'interrupt' | 'complete') => {
    if (target === 'interrupt') {
      if (!interruptOverlayCloseArmed.value) return
      interruptOverlayCloseArmed.value = false
      showInterruptConfirm.value = false
      return
    }
    if (!completeOverlayCloseArmed.value) return
    completeOverlayCloseArmed.value = false
    showCompleteConfirm.value = false
  }
  
  const cancelAllInlineOverlayClose = () => {
    interruptOverlayCloseArmed.value = false
    completeOverlayCloseArmed.value = false
  }
  
  const isJobActive = (status?: ChatAiJobStatus) => (
    status === 'PENDING' || status === 'RUNNING' || status === 'WAITING_HITL' || status === 'INTERRUPTED'
  )

  const isJobExecuting = (status?: ChatAiJobStatus) => (
    status === 'PENDING' || status === 'RUNNING' || status === 'WAITING_HITL'
  )
  
  const syncEngineRunningFromJobs = () => {
    const hasActiveJob = Object.values(activeChatJobs.value).some(job => isJobExecuting(job.status))
    engineRunning.value = hasActiveJob
  }
  
  const upsertHitlCardFromJob = (job: ChatAiJob) => {
    const pending = job.context_json?.pending_hitl
    if (!pending || typeof pending !== 'object') return
    const cardId = `job-hitl-${job.id}`
    const existing = pinnedCards.value.find(card => card.id === cardId)
    const hitlType = String(pending.hitl_type || 'text')
    const options = Array.isArray(pending.options) ? pending.options : []
    if (existing) {
      existing.hitl_type = hitlType
      existing.prompt = String(pending.prompt || '')
      existing.options = options
      existing.context = String(pending.context || '')
      existing.answered = false
      existing.job_id = job.id
      existing.created_at = existing.created_at || new Date().toISOString()
      return
    }
    pinnedCards.value.push({
      id: cardId,
      type: 'hitl',
      hitl_type: hitlType,
      prompt: String(pending.prompt || ''),
      options,
      context: String(pending.context || ''),
      answered: false,
      answer: '',
      tempInput: '',
      job_id: job.id,
      created_at: new Date().toISOString(),
    })
  }
  
  const markHitlCardAnswered = (jobId: string, answer: string) => {
    const card = pinnedCards.value.find(item => item.type === 'hitl' && item.job_id === jobId && !item.answered)
    if (!card) return
    card.answered = true
    card.answer = answer
  }
  
  const upsertChatJob = (job: ChatAiJob) => {
    if (!job?.id) return
    const nextJobs = { ...activeChatJobs.value }
    if (isJobActive(job.status)) {
      nextJobs[job.id] = job
    } else {
      delete nextJobs[job.id]
    }
    activeChatJobs.value = nextJobs
    if (job.status === 'WAITING_HITL') {
      upsertHitlCardFromJob(job)
    } else {
      const pendingCard = pinnedCards.value.find(item => item.type === 'hitl' && item.job_id === job.id && !item.answered)
      if (pendingCard) {
        pendingCard.answered = true
        if (!pendingCard.answer) {
          pendingCard.answer = t('chat.hitl_answer_submitted')
        }
      }
    }
    if (job.status === 'SUCCESS' || job.status === 'FAILED' || job.status === 'CANCELLED') {
      const card = pinnedCards.value.find(item => item.type === 'hitl' && item.job_id === job.id && !item.answered)
      if (card) {
        card.answered = true
        if (!card.answer) {
          card.answer = job.status === 'FAILED'
            ? t('chat.hitl_answer_failed')
            : (job.status === 'CANCELLED' ? t('chat.hitl_answer_cancelled') : t('chat.hitl_answer_done'))
        }
      }
    }
    syncEngineRunningFromJobs()
  }
  
  const resetChatJobState = () => {
    activeChatJobs.value = {}
    engineRunning.value = false
  }

  const applyTaskSessionPayload = (payload: any) => {
    if (!currentTask.value?.id) return
    if (String(payload?.task_id || '') !== String(currentTask.value.id)) return
    const status = String(payload?.status || '').trim()
    if (status) {
      currentTask.value.status = status
      const targetTask = tasks.value.find((task) => task.id === currentTask.value.id)
      if (targetTask) targetTask.status = status
    }
    if (payload?.session_id !== undefined) {
      currentTask.value.session_id = payload.session_id
    }
    if (payload?.interrupt_reason !== undefined) {
      currentTask.value.interrupt_reason = payload.interrupt_reason
    }
    if (payload?.interrupted_at !== undefined) {
      currentTask.value.interrupted_at = payload.interrupted_at
    }
    const job = payload?.job as ChatAiJob | undefined
    if (job?.id) {
      upsertChatJob(job)
    } else {
      syncEngineRunningFromJobs()
    }
  }
  
  const loadActiveChatJobs = async (taskId: string) => {
    try {
      const res = await api.get(`/workspaces/${route.params.wsId}/tasks/${taskId}/ai-jobs`, {
        params: { active_only: true },
      })
      const items = (res.data?.items || []) as ChatAiJob[]
      activeChatJobs.value = {}
      for (const job of items) {
        upsertChatJob(job)
      }
      if (!items.length) {
        engineRunning.value = false
      }
    } catch (e) {
      console.warn('Failed to load active AI jobs', e)
    }
  }
  
  const loadTaskSpecBootstrap = async (taskId: string, taskSnapshot?: any) => {
    if (!taskId || !hasTaskSpecification(taskSnapshot ?? currentTask.value)) {
      specBootstrap.value = null
      specBootstrapLoading.value = false
      return
    }
    specBootstrapLoading.value = true
    try {
      const res = await api.get(`/workspaces/${route.params.wsId}/tasks/${taskId}/spec-bootstrap`)
      specBootstrap.value = res.data as TaskSpecBootstrap
    } catch (e: any) {
      if (e?.response?.status === 404) {
        specBootstrap.value = null
        return
      }
      console.warn('Failed to load spec bootstrap snapshot', e)
    } finally {
      specBootstrapLoading.value = false
    }
  }
  
  const bootstrapStatusText = (status?: SpecBootstrapStatus) => {
    if (status === 'PENDING') return t('chat.spec_bootstrap_status_pending')
    if (status === 'RUNNING') return t('chat.spec_bootstrap_status_running')
    if (status === 'READY') return t('chat.spec_bootstrap_status_ready')
    if (status === 'FAILED') return t('chat.spec_bootstrap_status_failed')
    if (status === 'STALE') return t('chat.spec_bootstrap_status_stale')
    return ''
  }

  const clearRuntimeUsageRefreshTimer = () => {
    if (runtimeUsageRefreshTimer !== null) {
      window.clearTimeout(runtimeUsageRefreshTimer)
      runtimeUsageRefreshTimer = null
    }
  }

  const clearContextWindowRefreshTimer = () => {
    if (contextWindowRefreshTimer !== null) {
      window.clearTimeout(contextWindowRefreshTimer)
      contextWindowRefreshTimer = null
    }
  }

  const refreshContextWindow = async () => {
    if (!currentTask.value?.id) return
    if (contextWindow.selectedCategory.value) {
      await contextWindow.loadCategory(contextWindow.selectedCategory.value)
      return
    }
    await contextWindow.loadSummary()
  }

  const scheduleContextWindowRefresh = () => {
    if (!contextWindowDrawerOpen.value || !currentTask.value?.id) return
    clearContextWindowRefreshTimer()
    contextWindowRefreshTimer = window.setTimeout(() => {
      contextWindowRefreshTimer = null
      void refreshContextWindow()
    }, 900)
  }

  const openContextWindowDrawer = async () => {
    if (!currentTask.value?.id) return
    contextWindowDrawerOpen.value = true
    await contextWindow.loadSummary()
  }

  const closeContextWindowDrawer = () => {
    contextWindowDrawerOpen.value = false
  }

  const updateContextWindowDrawerLevel = (level: number) => {
    contextWindowDrawerLevel.value = Math.max(1, Math.min(3, Number(level || 1))) as OpenSpecDrawerLevel
  }

  const selectContextWindowCategory = async (category: ContextTokenCategory | string) => {
    if (!currentTask.value?.id) return
    await contextWindow.loadCategory(category)
  }

  const clearReferenceHighlight = () => {
    if (referenceHighlightTimer !== null) {
      window.clearTimeout(referenceHighlightTimer)
      referenceHighlightTimer = null
    }
    highlightedMessageId.value = ''
    highlightedTerminalLogId.value = ''
  }

  const scheduleReferenceHighlightClear = () => {
    if (referenceHighlightTimer !== null) {
      window.clearTimeout(referenceHighlightTimer)
    }
    referenceHighlightTimer = window.setTimeout(() => {
      highlightedMessageId.value = ''
      highlightedTerminalLogId.value = ''
      referenceHighlightTimer = null
    }, 2600)
  }

  const attrSelectorValue = (value: string) => String(value || '').replace(/\\/g, '\\\\').replace(/"/g, '\\"')

  const scrollToElementByAttr = async (attr: string, value: string) => {
    await nextTick()
    window.requestAnimationFrame(() => {
      const selector = `[${attr}="${attrSelectorValue(value)}"]`
      const target = document.querySelector(selector)
      if (target instanceof HTMLElement) {
        target.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    })
  }

  const locateContextWindowReference = async (payload: ContextCompactionLocatePayload) => {
    clearReferenceHighlight()
    const messageId = String(payload.chat_message_id || '').trim()
    const logId = String(payload.log_id || '').trim()
    if (messageId) {
      chatWorkbenchMode.value = 'platform'
      contextWindowDrawerOpen.value = false
      highlightedMessageId.value = messageId
      await scrollToElementByAttr('data-message-id', messageId)
      scheduleReferenceHighlightClear()
      return
    }
    if (logId) {
      chatWorkbenchMode.value = 'cli'
      contextWindowDrawerOpen.value = false
      highlightedTerminalLogId.value = logId
      await scrollToElementByAttr('data-log-id', logId)
      scheduleReferenceHighlightClear()
      return
    }
    if (payload.ai_job_id) {
      chatWorkbenchMode.value = 'cli'
      contextWindowDrawerOpen.value = false
      await nextTick()
      scrollToBottom('terminal')
    }
  }

  const resetRuntimeSkillEditorState = () => {
    taskRuntimeSkills.value = []
    taskRuntimeSkillsUsageScopeStartAt.value = null
    runtimeActiveSkillId.value = ''
    runtimeFileTree.value = []
    runtimeFileTreeLoading.value = false
    runtimeActiveFilePath.value = ''
    runtimeActiveFileLoading.value = false
    runtimeActiveFileSaving.value = false
    runtimeActiveFileContent.value = ''
    runtimeActiveFileOriginalContent.value = ''
    runtimeActiveFileBinary.value = false
    initSelectedSkillIds.value = []
    resetRuntimeTraceEvents()
    clearRuntimeUsageRefreshTimer()
  }

  const collectFirstFilePath = (nodes: RuntimeSkillFileNode[]): string => {
    for (const node of nodes) {
      if (node.node_type === 'file') return node.path
      if (node.node_type === 'directory') {
        const nested = collectFirstFilePath(Array.isArray(node.children) ? node.children : [])
        if (nested) return nested
      }
    }
    return ''
  }

  const treeContainsFilePath = (nodes: RuntimeSkillFileNode[], filePath: string): boolean => {
    if (!filePath) return false
    for (const node of nodes) {
      if (node.node_type === 'file' && node.path === filePath) return true
      if (node.node_type === 'directory') {
        if (treeContainsFilePath(Array.isArray(node.children) ? node.children : [], filePath)) {
          return true
        }
      }
    }
    return false
  }

  const extractTaskSkillIds = (): string[] => {
    const optionIds = activeInitSkillOptionIds.value
    const list = taskRuntimeSkills.value
      .map((item) => String(item.skill_id || '').trim())
      .filter((skillId) => Boolean(skillId) && !skillId.startsWith('runtime:') && optionIds.has(skillId))
    if (list.length) return list
    const fallback = Array.isArray(currentTask.value?.skill_ids) ? currentTask.value.skill_ids : []
    return fallback
      .map((value: string) => String(value || '').trim())
      .filter((skillId: string) => (
        Boolean(skillId)
        && !skillId.startsWith('runtime:')
        && (optionIds.size === 0 || optionIds.has(skillId))
      ))
  }

  const loadInitSkillOptions = async () => {
    const wsId = String(route.params.wsId || '')
    if (!wsId) return
    initSkillOptionsLoading.value = true
    try {
      const res = await api.get('/skills', {
        params: { workspace_id: wsId, scope: 'all', page: 1, page_size: 200 },
      })
      initSkillOptions.value = Array.isArray(res.data?.items) ? res.data.items : []
    } catch (e) {
      console.error('Failed to load initialize skill options', e)
      initSkillOptions.value = []
    } finally {
      initSkillOptionsLoading.value = false
    }
  }

  const loadRuntimeSkillFileContent = async (skillId: string, filePath: string) => {
    if (!currentTask.value?.id || !skillId || !filePath) return
    runtimeActiveFileLoading.value = true
    try {
      const res = await api.get(
        `/workspaces/${route.params.wsId}/tasks/${currentTask.value.id}/skills/${skillId}/files/content`,
        { params: { path: filePath } },
      )
      runtimeActiveFilePath.value = res.data?.path || filePath
      runtimeActiveFileBinary.value = Boolean(res.data?.is_binary)
      const text = runtimeActiveFileBinary.value ? '' : String(res.data?.content ?? '')
      runtimeActiveFileContent.value = text
      runtimeActiveFileOriginalContent.value = text
    } catch (e) {
      console.error('Failed to load runtime skill file content', e)
      runtimeActiveFilePath.value = filePath
      runtimeActiveFileBinary.value = false
      runtimeActiveFileContent.value = ''
      runtimeActiveFileOriginalContent.value = ''
      ElMessage.error(t('chat.task_skills_file_load_failed'))
    } finally {
      runtimeActiveFileLoading.value = false
    }
  }

  const loadRuntimeSkillFileTree = async (
    skillId: string,
    options?: { keepCurrentFile?: boolean },
  ) => {
    if (!currentTask.value?.id || !skillId) return
    runtimeFileTreeLoading.value = true
    try {
      const res = await api.get(
        `/workspaces/${route.params.wsId}/tasks/${currentTask.value.id}/skills/${skillId}/files/tree`,
      )
      const nodes = Array.isArray(res.data?.nodes) ? res.data.nodes : []
      runtimeFileTree.value = nodes
      const keepCurrent = Boolean(options?.keepCurrentFile)
      const currentFileExists = keepCurrent
        && Boolean(runtimeActiveFilePath.value)
        && treeContainsFilePath(nodes, runtimeActiveFilePath.value)
      const nextFilePath = currentFileExists ? runtimeActiveFilePath.value : collectFirstFilePath(nodes)
      if (!nextFilePath) {
        runtimeActiveFilePath.value = ''
        runtimeActiveFileBinary.value = false
        runtimeActiveFileContent.value = ''
        runtimeActiveFileOriginalContent.value = ''
        return
      }
      await loadRuntimeSkillFileContent(skillId, nextFilePath)
    } catch (e) {
      console.error('Failed to load runtime skill file tree', e)
      runtimeFileTree.value = []
      runtimeActiveFilePath.value = ''
      runtimeActiveFileBinary.value = false
      runtimeActiveFileContent.value = ''
      runtimeActiveFileOriginalContent.value = ''
      ElMessage.error(t('chat.task_skills_tree_load_failed'))
    } finally {
      runtimeFileTreeLoading.value = false
    }
  }

  const loadTaskRuntimeSkills = async (options?: { silent?: boolean; hydrateEditor?: boolean }) => {
    if (!currentTask.value?.id) return
    const silent = Boolean(options?.silent)
    const hydrateEditor = Boolean(options?.hydrateEditor)
    if (!silent) {
      taskRuntimeSkillsLoading.value = true
    }
    try {
      const res = await api.get(`/workspaces/${route.params.wsId}/tasks/${currentTask.value.id}/skills/runtime`)
      const items = Array.isArray(res.data?.items) ? res.data.items : []
      taskRuntimeSkills.value = items
      taskRuntimeSkillsUsageScopeStartAt.value = res.data?.usage_scope_start_at || null

      const hasActive = items.some((item: RuntimeSkillItem) => item.skill_id === runtimeActiveSkillId.value)
      if (!hasActive) {
        runtimeActiveSkillId.value = items[0]?.skill_id || ''
      }
      if (!runtimeActiveSkillId.value) {
        runtimeFileTree.value = []
        runtimeActiveFilePath.value = ''
        runtimeActiveFileContent.value = ''
        runtimeActiveFileOriginalContent.value = ''
        runtimeActiveFileBinary.value = false
        return
      }
      if (hydrateEditor || showTaskSkillsDrawer.value) {
        await loadRuntimeSkillFileTree(runtimeActiveSkillId.value, { keepCurrentFile: true })
      }
    } catch (e) {
      console.error('Failed to load task runtime skills', e)
      if (!silent) {
        ElMessage.error(t('chat.task_skills_runtime_load_failed'))
      }
      taskRuntimeSkills.value = []
      taskRuntimeSkillsUsageScopeStartAt.value = null
    } finally {
      if (!silent) {
        taskRuntimeSkillsLoading.value = false
      }
    }
  }

  const loadTaskRuntimeTrace = async (options?: { silent?: boolean }) => {
    if (!currentTask.value?.id) return
    await loadRuntimeTraceEvents(
      String(route.params.wsId || ''),
      currentTask.value.id,
      { limit: 100, silent: options?.silent },
    )
  }

  const openTaskSkillsDrawer = async () => {
    if (!currentTask.value) return
    showTaskSkillsDrawer.value = true
    await Promise.all([
      loadTaskRuntimeSkills({ hydrateEditor: true }),
      loadTaskRuntimeTrace(),
    ])
  }

  const closeTaskSkillsDrawer = () => {
    showTaskSkillsDrawer.value = false
  }

  const selectRuntimeSkill = async (skillId: string) => {
    if (!skillId || runtimeActiveSkillId.value === skillId) return
    runtimeActiveSkillId.value = skillId
    runtimeActiveFilePath.value = ''
    runtimeActiveFileContent.value = ''
    runtimeActiveFileOriginalContent.value = ''
    runtimeActiveFileBinary.value = false
    await loadRuntimeSkillFileTree(skillId)
  }

  const selectRuntimeSkillFile = async (path: string) => {
    const skillId = runtimeActiveSkillId.value
    if (!skillId || !path) return
    await loadRuntimeSkillFileContent(skillId, path)
  }

  const saveRuntimeSkillFileContent = async () => {
    if (!currentTask.value?.id || !runtimeActiveSkillId.value || !runtimeActiveFilePath.value) return
    if (!canEditTaskRuntimeSkills.value) {
      ElMessage.warning(t('chat.errors.no_permission_manage_task_status'))
      return
    }
    if (runtimeActiveFileBinary.value) {
      ElMessage.warning(t('chat.task_skills_binary_readonly'))
      return
    }
    if (!runtimeActiveFileDirty.value) return
    runtimeActiveFileSaving.value = true
    try {
      const res = await api.put(
        `/workspaces/${route.params.wsId}/tasks/${currentTask.value.id}/skills/${runtimeActiveSkillId.value}/files/content`,
        { path: runtimeActiveFilePath.value, content: runtimeActiveFileContent.value },
      )
      const text = String(res.data?.content ?? runtimeActiveFileContent.value)
      runtimeActiveFileContent.value = text
      runtimeActiveFileOriginalContent.value = text
      runtimeActiveFileBinary.value = Boolean(res.data?.is_binary)
      ElMessage.success(t('chat.task_skills_file_saved'))
    } catch (e) {
      console.error('Failed to save runtime skill file', e)
      ElMessage.error(t('chat.task_skills_file_save_failed'))
    } finally {
      runtimeActiveFileSaving.value = false
    }
  }

  const updateRuntimeSkillFileContent = (value: string) => {
    runtimeActiveFileContent.value = value
  }

  const scheduleRuntimeUsageRefresh = () => {
    if (!currentTask.value?.id || taskRuntimeSkills.value.length === 0) return
    clearRuntimeUsageRefreshTimer()
    runtimeUsageRefreshTimer = window.setTimeout(() => {
      runtimeUsageRefreshTimer = null
      void loadTaskRuntimeSkills({ silent: true, hydrateEditor: false })
      void loadTaskRuntimeTrace({ silent: true })
    }, 1200)
  }

  const mergeRuntimeTraceEvent = (event: SkillRuntimeEvent) => {
    const alreadySeen = runtimeTraceEvents.value.some(item => item.id === event.id)
    appendRuntimeTraceEvent(event)
    if (alreadySeen || !event.skill_id || event.event_type === 'TOOL_RESULT') {
      return
    }
    taskRuntimeSkills.value = taskRuntimeSkills.value.map((skill) => {
      if (skill.skill_id !== event.skill_id) return skill
      const usage = skill.usage || { is_used: false, used_count: 0, last_used_at: null }
      return {
        ...skill,
        usage: {
          ...usage,
          is_used: true,
          used_count: Number(usage.used_count || 0) + 1,
          last_used_at: event.created_at || usage.last_used_at || null,
        },
      }
    })
  }
  
  // 鈹€鈹€鈹€ Load Data 鈹€鈹€鈹€
  const resolveTaskStatusQuery = (): 'DONE' | 'FAILED' | undefined => {
    if (taskStatusFilter.value === 'DONE') return 'DONE'
    if (taskStatusFilter.value === 'FAILED') return 'FAILED'
    return undefined
  }

  const loadTasks = async (options?: { reset?: boolean; trySelectRouteTask?: boolean }) => {
    const reset = options?.reset ?? true
    const trySelectRouteTask = options?.trySelectRouteTask ?? reset
    if (reset) {
      if (taskListLoading.value) return
      taskListLoading.value = true
      taskListPage.value = 1
    } else {
      if (taskListLoading.value || taskListLoadingMore.value || !taskListHasMore.value) return
      taskListLoadingMore.value = true
      taskListPage.value += 1
    }

    const wsId = String(route.params.wsId || '')
    const statusQuery = resolveTaskStatusQuery()
    try {
      const params: Record<string, string | number> = {
        page: taskListPage.value,
        page_size: TASK_LIST_PAGE_SIZE,
      }
      if (statusQuery) {
        params.status = statusQuery
      }
      if (taskTypeFilter.value !== 'ALL') {
        params.task_type = taskTypeFilter.value
      }

      const res = await api.get(`/workspaces/${wsId}/tasks`, { params })
      const items = Array.isArray(res.data?.items) ? res.data.items : []
      taskListTotal.value = Number(res.data?.total || 0)
      tasks.value = reset ? items : [...tasks.value, ...items]

      if (currentTask.value?.id) {
        const latest = tasks.value.find((task: any) => task.id === currentTask.value.id)
        if (latest) {
          currentTask.value = { ...currentTask.value, ...latest }
        }
      }

      if (!trySelectRouteTask || !route.params.taskId) return

      const routeTaskId = String(route.params.taskId || '')
      if (!routeTaskId) return
      const matched = tasks.value.find((task: any) => task.id === routeTaskId)
      if (matched) {
        if (currentTask.value?.id !== matched.id) {
          await selectTask(matched)
        }
        return
      }

      if (!reset || statusQuery) return

      try {
        const taskRes = await api.get(`/workspaces/${wsId}/tasks/${routeTaskId}`)
        const routeTask = taskRes.data
        if (!routeTask?.id) return
        tasks.value = [routeTask, ...tasks.value.filter((task: any) => task.id !== routeTask.id)]
        if (currentTask.value?.id !== routeTask.id) {
          await selectTask(routeTask)
        }
      } catch (err) {
        console.warn('Failed to hydrate route task snapshot', err)
      }
    } catch (e) {
      if (!reset) {
        taskListPage.value = Math.max(1, taskListPage.value - 1)
      }
      console.error('Failed to load tasks', e)
    } finally {
      if (reset) {
        taskListLoading.value = false
      } else {
        taskListLoadingMore.value = false
      }
    }
  }

  const loadMoreTasks = async () => {
    if (!taskListHasMore.value) return
    await loadTasks({ reset: false, trySelectRouteTask: false })
  }

  const applyTaskStatusFilter = async () => {
    await loadTasks({ reset: true, trySelectRouteTask: false })
  }

  const handleTaskListScroll = () => {
    const container = taskListContainer.value
    if (!container || taskListLoading.value || taskListLoadingMore.value || !taskListHasMore.value) return
    const nearBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 40
    if (nearBottom) {
      void loadMoreTasks()
    }
  }
  
  const loadWorkspace = async () => {
    const wsId = route.params.wsId
    const [wsRes, permissionRes] = await Promise.all([
      api.get(`/workspaces/${wsId}`),
      api.get(`/workspaces/${wsId}/permissions/me`),
    ])
    currentWorkspace.value = wsRes.data
    workspacePermissions.value = permissionRes.data?.permissions || null
    workspaceCurrentUserIsExpert.value = Boolean(permissionRes.data?.is_expert || wsRes.data?.my_is_expert)
  }
  
  // ─── Task Actions ───
  const openNewTaskModal = () => {
    if (!canCreateTask.value) return
    showTaskModal.value = true
  }
  
  const onTaskCreated = async (payload: string | { taskId: string; assetId?: string | null; jobId?: string; expectSpecUpload?: boolean; expectDiagnosisDocs?: boolean }) => {
    showTaskModal.value = false
    const taskId = typeof payload === 'string' ? payload : payload.taskId
    const wsId = route.params.wsId

    // 如果创建任务时上传了 spec 文件或问题定位文档，跳转到 provisioning 页面等待 job 完成
    if (typeof payload !== 'string' && payload.jobId && (payload.expectSpecUpload || payload.expectDiagnosisDocs)) {
      router.push(`/ops/queue/provision/${payload.jobId}?expectSpec=1`)
      return
    }

    preferredSpecTaskId.value = taskId
    preferredSpecAssetId.value = typeof payload === 'string' ? '' : (payload.assetId || '')
    await loadTasks()
    router.push(`/ws/${wsId}/chat/${taskId}`)

    // 重新获取一下最新的 task 对象
    const latestTaskRes = await api.get(`/workspaces/${wsId}/tasks/${taskId}`)
    selectTask(latestTaskRes.data)
  }
  
  const selectTask = async (task: any) => {
    if (!task) return
    if (task.id !== preferredSpecTaskId.value) {
      preferredSpecAssetId.value = ''
    }
    specDrawerLevel.value = 0
    diagnosisDocsDrawerOpen.value = false
    contextWindowDrawerOpen.value = false
    contextWindowDrawerLevel.value = 1
    contextWindow.reset()
    clearContextWindowRefreshTimer()
    specDrawerTab.value = hasTaskSpecification(task) ? 'spec_doc' : 'superpowers_docs'
    currentTask.value = task
    showTaskSkillsDrawer.value = false
    messages.value = []
    terminalLogs.value = []
    pinnedCards.value = []
    resetChatJobState()
    resetRuntimeSkillEditorState()
    specBootstrap.value = null
    specBootstrapLoading.value = false
    resetThinkingPanel()
    resultsSummary.value = { 
      visible: (task.total_cost_usd || 0) > 0 || (task.total_duration_ms || 0) > 0, 
      totalDurationMs: task.total_duration_ms || 0, 
      totalCostUsd: task.total_cost_usd || 0, 
      history: [], 
      expanded: false 
    }
    engineRunning.value = false
  
    const chatPath = `/ws/${route.params.wsId}/chat/${task.id}`
    if (route.path !== chatPath || String(route.params.taskId || '') !== String(task.id)) {
      router.push(chatPath)
    }
    loadHistory(task.id)
    loadActiveChatJobs(task.id)
    if (isDiagnosisTask.value) {
      void loadDiagnosisResult()
    } else {
      diagnosisResult.value = null
      diagnosisCaseLink.value = ''
    }
    loadTaskRuntimeSkills({ silent: true, hydrateEditor: false })
    if (hasTaskSpecification(task)) {
      loadTaskSpecBootstrap(task.id, task)
    }
    if (route.query.source === 'spec-plan' && isSpecDrawerAvailable.value) {
      specDrawerTab.value = 'spec_doc'
      requestSpecDrawerLevel(lastOpenSpecDrawerLevel.value)
    }
    connectWebSocket(task.id)
  }

  // ─── 问题定位任务（DIAGNOSIS） ───
  const isDiagnosisTask = computed(() => String(currentTask.value?.task_type || '') === 'DIAGNOSIS')
  /** 问题定位不需要 git patch/diff 相关业务，隐藏对应入口 */
  const hidePatchWorkflows = computed(() => isDiagnosisTask.value)

  const diagnosisResult = ref<any>(null)
  const diagnosisResultLoading = ref(false)
  const diagnosisResultSaving = ref(false)
  const diagnosisCaseCreating = ref(false)
  const diagnosisCaseLink = ref('')

  const loadDiagnosisResult = async () => {
    const taskId = currentTask.value?.id
    if (!taskId || !isDiagnosisTask.value) {
      diagnosisResult.value = null
      diagnosisCaseLink.value = ''
      return
    }
    diagnosisResultLoading.value = true
    try {
      const res = await api.get(`/workspaces/${route.params.wsId}/tasks/${taskId}/diagnosis-result`)
      diagnosisResult.value = res.data
    } catch (e: any) {
      if (e?.response?.status === 404) {
        // 尚无结果：等待 AI 会话收敛反填（卡片由会话消息驱动）
        diagnosisResult.value = null
        return
      }
      console.warn('Failed to load diagnosis result', e)
    } finally {
      diagnosisResultLoading.value = false
    }
    try {
      const casesRes = await api.get(`/workspaces/${route.params.wsId}/cases`, {
        params: { source_task_id: taskId, page: 1, page_size: 1 },
      })
      const linked = (casesRes.data?.items || [])[0]
      diagnosisCaseLink.value = linked?.id || ''
    } catch (e) {
      diagnosisCaseLink.value = ''
    }
  }

  const patchMessageMetadata = (messageId: string, payload: DiagnosisResultPayload) => {
    const message = messages.value.find(item => String(item.id || '') === String(messageId || ''))
    if (!message) return
    const normalized = normalizeDiagnosisPayload(payload)
    message.metadata = normalized
    message.content = String(normalized.summary || normalized.root_cause || '')
  }

  const saveDiagnosisResult = async (payload: DiagnosisResultPayload, messageId?: string) => {
    const taskId = currentTask.value?.id
    if (!taskId) return
    diagnosisResultSaving.value = true
    try {
      const res = await api.put(`/workspaces/${route.params.wsId}/tasks/${taskId}/diagnosis-result`, payload)
      diagnosisResult.value = res.data
      if (messageId) {
        patchMessageMetadata(messageId, payload)
      }
      ElMessage.success(t('diagnosis.result_saved'))
    } catch (e) {
      ElMessage.error(formatApiError(e, t('diagnosis.result_save_failed'), t))
      console.error('Failed to save diagnosis result', e)
    } finally {
      diagnosisResultSaving.value = false
    }
  }

  const createDiagnosisCase = async (submitForReview: boolean): Promise<string> => {
    const taskId = currentTask.value?.id
    if (!taskId) return ''
    diagnosisCaseCreating.value = true
    try {
      const res = await api.post(`/workspaces/${route.params.wsId}/tasks/${taskId}/case-draft`, {
        submit_for_review: Boolean(submitForReview),
      })
      const caseId = String(res.data?.id || '')
      diagnosisCaseLink.value = caseId
      ElMessage.success(t(submitForReview ? 'diagnosis.case_created_and_submitted' : 'diagnosis.case_created'))
      router.push(`/ws/${route.params.wsId}/cases?case=${caseId}`)
      return caseId
    } catch (e: any) {
      if (e?.response?.status === 409) {
        const detail = String(e?.response?.data?.detail || '')
        const match = detail.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i)
        const existingId = match ? match[0] : ''
        if (existingId) {
          diagnosisCaseLink.value = existingId
          ElMessage.info(t('diagnosis.case_already_exists'))
          router.push(`/ws/${route.params.wsId}/cases?case=${existingId}`)
          return existingId
        }
      }
      ElMessage.error(formatApiError(e, t('diagnosis.case_create_failed'), t))
      console.error('Failed to create diagnosis case', e)
      return ''
    } finally {
      diagnosisCaseCreating.value = false
    }
  }

  // ─── 任务类型过滤（会话列表） ───
  type TaskTypeFilterValue = 'ALL' | 'DEVELOPMENT' | 'DIAGNOSIS'
  const taskTypeFilter = ref<TaskTypeFilterValue>('ALL')

  const applyTaskTypeFilter = async () => {
    await loadTasks({ reset: true, trySelectRouteTask: false })
  }
  
  const openSpecWorkspace = () => {
    if (!currentTask.value || !currentTaskHasSpec.value) return
    router.push(`/ws/${route.params.wsId}/chat/${currentTask.value.id}/spec`)
  }
  
  const closeSpecDrawer = () => {
    specDrawerLevel.value = 0
  }
  
  
  const handleExpandDrawer = () => {
    if (specDrawerLevel.value === 0) {
      specDrawerLevel.value = 1
      return
    }
    if (specDrawerLevel.value < 3) {
      specDrawerLevel.value++
    }
  }
  
  const handleCollapseDrawer = () => {
    if (specDrawerLevel.value > 1) {
      specDrawerLevel.value--
    } else {
      specDrawerLevel.value = 0
    }
  }
  
  const applySpecDrawerLevel = (level: OpenSpecDrawerLevel) => {
    specDrawerLevel.value = level
    lastOpenSpecDrawerLevel.value = level
  }
  
  const requestSpecDrawerLevel = (level: OpenSpecDrawerLevel) => {
    if (!isSpecDrawerAvailable.value) return
    applySpecDrawerLevel(level)
  }
  
  const handleSpecEntryClick = () => {
    if (!currentTask.value || !showSpecEntryButton.value) return
    if (isTaskPreStart.value) {
      openSpecWorkspace()
      return
    }
    if (!currentTaskHasSpec.value) {
      specDrawerTab.value = 'superpowers_docs'
    }
    if (isSpecPanelOpen.value) {
      closeSpecDrawer()
      return
    }
    requestSpecDrawerLevel(lastOpenSpecDrawerLevel.value)
  }
  
  const loadHistory = async (taskId: string, reset: boolean = true) => {
    try {
      if (reset) {
        currentPage.value = 1
        messages.value = []
        terminalLogs.value = []
      }
  
      const res = await api.get(`/workspaces/${route.params.wsId}/tasks/${taskId}/history`, {
        params: { page: currentPage.value, page_size: 50 }
      })
      const { messages: hMessages, logs: hLogs, has_more } = res.data
      hasMore.value = has_more
  
      const mapped = hMessages.map((m: any) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        created_at: m.created_at,
        message_type: m.type || 'text',
        creator_id: m.creator_id || null,
        creator_display_name: m.creator_display_name || null,
        creator_is_workspace_expert: Boolean(m.creator_is_workspace_expert),
        client_message_id: m.client_message_id || null,
        decision_id: m.decision_id || null,
        metadata: m.metadata || null,
      }))
  
      if (reset) {
        messages.value = dedupeMessages(mapped)
        // 还原终端日志（仅首次加载�?
        terminalLogs.value = hLogs.map((l: any) => {
          const createdAt = l.created_at || new Date().toISOString()
          try {
            const parsed = JSON.parse(l.content)
            if (parsed.tool_name) {
              return {
                id: l.id,
                type: 'tool_use',
                tool_name: parsed.tool_name,
                tool_input: parsed.tool_input,
                tool_use_id: parsed.tool_use_id,
                created_at: createdAt,
                timestamp: new Date(createdAt).toLocaleTimeString(),
              }
            }
            if (parsed.tool_use_id) {
              return {
                id: l.id,
                type: 'tool_result',
                tool_use_id: parsed.tool_use_id,
                output: parsed.output,
                is_error: Boolean(parsed.is_error),
                created_at: createdAt,
                timestamp: new Date(createdAt).toLocaleTimeString(),
              }
            }
          } catch {
            // Non-JSON log entries fall through
          }
          return {
            id: l.id,
            type: 'log',
            content: l.content,
            created_at: createdAt,
            timestamp: new Date(createdAt).toLocaleTimeString(),
          }
        })
  
        await nextTick()
        if (route.query.messageId) {
          await highlightMessageFromRouteQuery()
        } else {
          scrollToBottom('chat')
        }
        scrollToBottom('terminal')
      } else {
        // 向上加载更早消息：prepend 到列表前�?
        messages.value = dedupeMessages([...mapped, ...messages.value])
      }
    } catch (e) {
      console.error('Failed to load history', e)
    }
  }
  
  const loadOlderMessages = async () => {
    if (!hasMore.value || loadingMore.value || !currentTask.value) return
  
    loadingMore.value = true
    const container = chatContainer.value
    const prevScrollHeight = container?.scrollHeight || 0
  
    currentPage.value++
    try {
      await loadHistory(currentTask.value.id, false)
  
      // 保持滚动位置不跳�?
      await nextTick()
      if (container) {
        const newScrollHeight = container.scrollHeight
        container.scrollTop = newScrollHeight - prevScrollHeight
      }
    } finally {
      loadingMore.value = false
    }
  }
  
  const handleChatScroll = () => {
    const container = chatContainer.value
    if (!container) return
    // 滚动到顶部附近时加载更早消息
    if (container.scrollTop < 50 && hasMore.value && !loadingMore.value) {
      loadOlderMessages()
    }
  }
  
  const handleInterruptClick = (): boolean => {
    if (!canManageTaskStatus.value) {
      ElMessage.warning(t('chat.errors.no_permission_manage_task_status'))
      return false
    }
  
    const status = currentTask.value?.status
    const isRunningStatus = status && !['DONE', 'FAILED'].includes(status)
  
    if (!isRunningStatus && !engineRunning.value) {
      ElMessage.warning(t('chat.no_running_engine'))
      return false
    }
    closeoutMode.value = 'fail'
    return true
  }
  
  const handleCompleteClick = (): boolean => {
    if (!canManageTaskStatus.value) {
      ElMessage.warning(t('chat.errors.no_permission_manage_task_status'))
      return false
    }
  
    const status = currentTask.value?.status
    const isRunningStatus = status && !['DONE', 'FAILED'].includes(status)
  
    if (!isRunningStatus && !engineRunning.value) {
      ElMessage.warning(t('chat.no_running_engine'))
      return false
    }
    closeoutMode.value = 'complete'
    return true
  }

  const completeTaskNow = async (): Promise<boolean> => {
    return handleCompleteClick()
  }

  const confirmComplete = async () => {
    await completeTaskNow()
  }

  const interruptCurrentRun = async (): Promise<boolean> => {
    if (!currentTask.value?.id) return false
    if (!canManageTaskStatus.value) {
      ElMessage.warning(t('chat.errors.no_permission_manage_task_status'))
      return false
    }
    if (!engineRunning.value) {
      ElMessage.warning(t('chat.no_running_engine'))
      return false
    }

    try {
      const payload = await taskSessionControls.interruptTask(
        currentTask.value.id,
        t('chat.temporary_interrupt_reason'),
      )
      pinnedCards.value = pinnedCards.value.filter(c => c.type !== 'status')
      engineRunning.value = false
      applyTaskSessionPayload(payload)
      return true
    } catch (e) {
      console.error('Temporary interrupt failed', e)
      ElMessage.error(resolveActionError(e, 'chat.errors.temporary_interrupt_failed', 'chat.errors.no_permission_manage_task_status'))
      return false
    }
  }

  const interruptTaskNow = async (): Promise<boolean> => {
    return handleInterruptClick()
  }

  const closeTaskCloseout = () => {
    closeoutMode.value = null
  }

  const handleTaskCloseoutSuccess = (status: string) => {
    if (!currentTask.value) return
    closeoutMode.value = null
    engineRunning.value = false
    pinnedCards.value = pinnedCards.value.filter(c => c.type !== 'status' && c.type !== 'hitl')
    resetChatJobState()
    currentTask.value.status = status
    const targetTask = tasks.value.find((task) => task.id === currentTask.value.id)
    if (targetTask) targetTask.status = status
    messages.value.push({
      id: Date.now().toString(),
      role: 'system',
      content: status === 'DONE' ? t('chat.closeout.complete_saved') : t('chat.closeout.failure_saved'),
      created_at: new Date().toISOString(),
      message_type: 'text',
    })
    scrollToBottom('chat')
  }

  const canMarkMessageAsDecision = (msg: any): boolean => {
    const id = String(msg?.id || '').trim()
    if (!id || id.startsWith('local-')) return false
    if (!currentTask.value?.id || !canManageTaskStatus.value) return false
    if (msg?.decision_id) return false
    if (msg?.message_type === 'init_reason') return false
    if (String(msg?.role || '').toLowerCase() !== 'user') return false
    return Boolean(String(msg?.content || '').trim())
  }

  const openDecisionModal = (msg: any) => {
    if (!canMarkMessageAsDecision(msg)) return
    decisionSourceMessage.value = msg
    decisionModalOpen.value = true
  }

  const closeDecisionModal = () => {
    if (chatDecision.saving.value) return
    decisionModalOpen.value = false
    decisionSourceMessage.value = null
  }

  const submitMessageDecision = async (payload: ChatDecisionPayload) => {
    if (!currentTask.value?.id || !decisionSourceMessage.value?.id) return
    const result = await chatDecision.markMessageAsDecision(
      String(route.params.wsId || ''),
      String(currentTask.value.id),
      String(decisionSourceMessage.value.id),
      payload,
    )
    if (!result) {
      ElMessage.error(chatDecision.error.value || t('chat.decision.save_failed'))
      return
    }
    const target = messages.value.find((item) => String(item.id) === String(decisionSourceMessage.value?.id))
    if (target) target.decision_id = result.id
    ElMessage.success(t('chat.decision.saved'))
    scheduleContextWindowRefresh()
    closeDecisionModal()
  }

  const confirmInterrupt = async () => {
    await interruptTaskNow()
  }
  
  const handleInitialize = async () => {
    if (!currentTask.value) return
    if (!canManageTaskStatus.value) {
      ElMessage.warning(t('chat.errors.no_permission_manage_task_status'))
      return
    }
    if (!canInitializeAction.value) return
    initReason.value = ''
    const fallbackSkillIds = Array.isArray(currentTask.value?.skill_ids)
      ? currentTask.value.skill_ids.map((value: string) => String(value || '').trim()).filter(Boolean)
      : []
    initSelectedSkillIds.value = Array.from(new Set(fallbackSkillIds))
    showInitReasonModal.value = true
    await Promise.all([
      loadTaskRuntimeSkills({ hydrateEditor: false }),
      loadInitSkillOptions(),
    ])
    initSelectedSkillIds.value = extractTaskSkillIds()
  }
  
  const initializeTaskWithReason = async (
    reason?: string,
    skillIds?: string[],
    options?: { keepDeletedRuntimeSkills?: boolean },
  ): Promise<boolean> => {
    if (!currentTask.value) return false
    if (!canManageTaskStatus.value) {
      ElMessage.warning(t('chat.errors.no_permission_manage_task_status'))
      return false
    }

    const reasonText = String(reason ?? initReason.value).trim()
    const hasSkillSelectionArg = Array.isArray(skillIds)
    const optionIds = activeInitSkillOptionIds.value
    const normalizedSkillIds = hasSkillSelectionArg
      ? Array.from(new Set((skillIds || [])
          .map((value) => String(value || '').trim())
          .filter((skillId) => (
            Boolean(skillId)
            && !skillId.startsWith('runtime:')
            && (optionIds.size === 0 || optionIds.has(skillId))
          ))))
      : []
    messages.value = []
    terminalLogs.value = []
    pinnedCards.value = []
    resetChatJobState()
    resetThinkingPanel()
    resultsSummary.value = { visible: false, totalDurationMs: 0, totalCostUsd: 0, history: [], expanded: false }
  
    engineRunning.value = true
    try {
      const payload: Record<string, unknown> = {
        reason: reasonText || undefined,
      }
      if (hasSkillSelectionArg) {
        payload.skill_ids = normalizedSkillIds
        payload.keep_deleted_runtime_skills = options?.keepDeletedRuntimeSkills !== false
      }
      await api.post(
        `/workspaces/${route.params.wsId}/tasks/${currentTask.value.id}/initialize`,
        payload,
      )
      currentTask.value.status = 'CODING'
      if (hasSkillSelectionArg) {
        currentTask.value.skill_ids = normalizedSkillIds
      }
  
      // 加载初始化时保存的消息（用户初始消息 + 可能�?init_reason 分隔线）
      await loadHistory(currentTask.value.id)
      await loadActiveChatJobs(currentTask.value.id)
      await loadTaskRuntimeSkills({ silent: true, hydrateEditor: showTaskSkillsDrawer.value })
  
      const targetTask = tasks.value.find((task) => task.id === currentTask.value.id)
      if (targetTask) {
        targetTask.status = 'CODING'
        if (hasSkillSelectionArg) {
          targetTask.skill_ids = normalizedSkillIds
        }
      }
      return true
    } catch (e) {
      console.error('Initialize failed', e)
      ElMessage.error(resolveActionError(e, 'chat.errors.initialize_failed', 'chat.errors.no_permission_manage_task_status'))
      engineRunning.value = false
      return false
    }
  }

  const confirmInitialize = async () => {
    if (!currentTask.value) return
    if (initSkillOptionsLoading.value || taskRuntimeSkillsLoading.value) return
    if (deletedRuntimeSkillsForInitialize.value.length > 0) {
      showDeletedRuntimeSkillConfirm.value = true
      return
    }
    showInitReasonModal.value = false
    await initializeTaskWithReason(
      initReason.value,
      initSelectedSkillIds.value,
      { keepDeletedRuntimeSkills: true },
    )
  }

  const cancelDeletedRuntimeSkillConfirm = () => {
    showDeletedRuntimeSkillConfirm.value = false
  }

  const confirmInitializeWithDeletedRuntimeSkillDecision = async (keepDeletedRuntimeSkills: boolean) => {
    if (!currentTask.value) return
    showDeletedRuntimeSkillConfirm.value = false
    showInitReasonModal.value = false
    await initializeTaskWithReason(
      initReason.value,
      initSelectedSkillIds.value,
      { keepDeletedRuntimeSkills },
    )
  }
  
  const handleDeleteTask = (task: any) => {
    if (!canDeleteTask.value) {
      ElMessage.warning(t('chat.errors.no_permission_delete_task'))
      return
    }
  
    taskToDelete.value = task
    showDeleteTaskConfirm.value = true
  }
  
  const closeDeleteTaskConfirm = () => {
    if (deletingTask.value) return
    showDeleteTaskConfirm.value = false
    taskToDelete.value = null
  }
  
  const confirmDeleteTask = async () => {
    if (!taskToDelete.value) return
    if (!canDeleteTask.value) {
      ElMessage.warning(t('chat.errors.no_permission_delete_task'))
      return
    }
  
    deletingTask.value = true
    try {
      await api.delete(`/workspaces/${route.params.wsId}/tasks/${taskToDelete.value.id}`)
      const deletedId = taskToDelete.value.id
      await loadTasks({ reset: true, trySelectRouteTask: false })
      if (currentTask.value?.id === deletedId) {
        currentTask.value = null
        router.push(`/ws/${route.params.wsId}/chat`)
      }
    } catch (e) {
      console.error('Failed to delete task', e)
      ElMessage.error(resolveActionError(e, 'chat.errors.delete_failed', 'chat.errors.no_permission_delete_task'))
    } finally {
      deletingTask.value = false
      showDeleteTaskConfirm.value = false
      taskToDelete.value = null
    }
  }
  
  const handleExport = async () => {
    if (!currentTask.value) return
    if (!canExportTask.value) {
      ElMessage.warning(t('chat.errors.no_permission_export_task'))
      return
    }
  
    try {
      const res = await api.get(`/workspaces/${route.params.wsId}/tasks/${currentTask.value.id}/export`)
      const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `task-session-${currentTask.value.id}.json`
      link.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      console.error('Failed to export session', e)
      ElMessage.error(resolveActionError(e, 'chat.errors.export_failed', 'chat.errors.no_permission_export_task'))
    }
  }

  const clearTaskHistory = async (): Promise<{
    deleted_chat_messages: number
    deleted_execution_logs: number
    deleted_total: number
  } | null> => {
    if (!currentTask.value) return null
    try {
      const res = await api.delete(`/workspaces/${route.params.wsId}/tasks/${currentTask.value.id}/history`)
      messages.value = []
      terminalLogs.value = []
      pinnedCards.value = []
      resetThinkingPanel()
      resultsSummary.value = { visible: false, totalDurationMs: 0, totalCostUsd: 0, history: [], expanded: false }
      currentPage.value = 1
      hasMore.value = false
      await loadHistory(currentTask.value.id, true)
      return res.data
    } catch (e) {
      ElMessage.error(resolveActionError(e, 'chat.errors.clear_history_failed', 'chat.errors.no_permission_manage_task_status'))
      return null
    }
  }
  
  // ─── WebSocket ───
  const clearWsReconnectTimer = () => {
    if (wsReconnectTimer === null) return
    window.clearTimeout(wsReconnectTimer)
    wsReconnectTimer = null
  }
  
  const buildTaskWsUrl = (taskId: string): string => {
    return buildBackendWsUrl(`/ws/task/${taskId}`, {
      token: authStore.token || undefined,
    })
  }
  
  const scheduleWsReconnect = (taskId: string) => {
    if (wsManualClose || wsReconnectTimer !== null) return
    wsReconnectTimer = window.setTimeout(() => {
      wsReconnectTimer = null
      if (currentTask.value?.id !== taskId) return
      connectWebSocket(taskId)
    }, 1200)
  }
  
  const connectWebSocket = (taskId: string) => {
    clearWsReconnectTimer()
    wsManualClose = false
    if (ws) {
      ws.onopen = null
      ws.onmessage = null
      ws.onerror = null
      ws.onclose = null
      ws.close()
      ws = null
    }
    ws = new WebSocket(buildTaskWsUrl(taskId))
    ws.onopen = () => {
      console.log(`WS Connected: task=${taskId}`)
      if (currentTask.value?.id === taskId) {
        void loadActiveChatJobs(taskId)
        if (hasTaskSpecification(currentTask.value)) {
          void loadTaskSpecBootstrap(taskId)
        }
      }
    }
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      handleWsMessage(data)
    }
    ws.onerror = (event) => {
      console.error('WS Error', event)
    }
    ws.onclose = (event) => {
      console.log(`WS Disconnected: task=${taskId}`)
      if (event.code === 1008) {
        ElMessage.error('Task WebSocket authentication failed. Please sign in again.')
        return
      }
      if (currentTask.value?.id !== taskId) return
      scheduleWsReconnect(taskId)
    }
  }
  
  const terminalContainer = ref<HTMLElement | null>(null)
  const chatContainer = ref<HTMLElement | null>(null)
  
  const scrollToBottom = async (target: 'chat' | 'terminal') => {
    await nextTick()
    if (target === 'chat' && chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    } else if (target === 'terminal' && terminalContainer.value) {
      terminalContainer.value.scrollTop = terminalContainer.value.scrollHeight
    }
  }

  const highlightMessageFromRouteQuery = async () => {
    const messageId = String(route.query.messageId || '').trim()
    if (!messageId) return false
    highlightedMessageId.value = messageId
    await nextTick()
    const target = chatContainer.value?.querySelector(`[data-message-id="${CSS.escape(messageId)}"]`) as HTMLElement | null
    if (target) {
      target.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }
    if (referenceHighlightTimer) window.clearTimeout(referenceHighlightTimer)
    referenceHighlightTimer = window.setTimeout(() => {
      if (highlightedMessageId.value === messageId) highlightedMessageId.value = ''
      referenceHighlightTimer = null
    }, 2600)
    return Boolean(target)
  }
  
  // ─── 事件分发：严格按类型分区 ───
  const handleWsMessage = (msg: any) => {
    const { type, payload } = msg
  
    switch (type) {
      case 'chat_message': {
        // 自然语言对话气泡 (user / assistant text) 与定位结果卡片
        upsertChatMessage({
          id: payload.id || Date.now().toString(),
          role: payload.role,
          content: payload.content,
          created_at: payload.created_at || new Date().toISOString(),
          message_type: payload.message_type || 'text',
          creator_id: payload.creator_id || null,
          creator_display_name: payload.creator_display_name || null,
          creator_is_workspace_expert: Boolean(payload.creator_is_workspace_expert),
          client_message_id: payload.client_message_id || null,
          decision_id: payload.decision_id || null,
          metadata: payload.metadata || null,
          delivery_status: 'sent',
        })
        scrollToBottom('chat')
        scheduleContextWindowRefresh()
        break
      }

      case 'chat_message_ack': {
        const status = String(payload.status || '').toLowerCase()
        const clientMessageId = String(payload.client_message_id || '').trim()
        const messagePatch = {
          id: payload.id || payload.chat_message_id || (clientMessageId ? `local-${clientMessageId}` : Date.now().toString()),
          role: payload.role || 'user',
          content: payload.content || '',
          created_at: payload.created_at || new Date().toISOString(),
          message_type: payload.message_type || 'text',
          creator_id: payload.creator_id || null,
          creator_display_name: payload.creator_display_name || null,
          creator_is_workspace_expert: Boolean(payload.creator_is_workspace_expert),
          client_message_id: clientMessageId || null,
          decision_id: payload.decision_id || null,
          metadata: payload.metadata || null,
          delivery_status: status === 'accepted' || status === 'duplicate' ? 'sent' : status,
        }
        if (clientMessageId) {
          const existing = messages.value.find(item => String(item.client_message_id || '') === clientMessageId)
          if (existing) {
            upsertChatMessage({
              ...messagePatch,
              content: messagePatch.content || existing.content,
              created_at: payload.created_at || existing.created_at,
            })
          } else if (messagePatch.content) {
            upsertChatMessage(messagePatch)
          }
        }
        if (status === 'failed' || status === 'conflict') {
          ElMessage.error(payload.message || 'Message was not sent. Please retry.')
        }
        break
      }
  
      case 'thinking': {
        // AI 思考过�?�?思考面�?(不进入对话气�?
        const wasThinkingVisible = showThinking.value
        thinkingContent.value = payload.content
        showThinking.value = true
        if (!wasThinkingVisible) {
          thinkingExpanded.value = false
        }
        scheduleContextWindowRefresh()
        break
      }
  
      case 'tool_use': {
        // 工具调用 �?终端面板 (不进入对话气�?
        const createdAt = new Date().toISOString()
        terminalLogs.value.push({
          id: payload.id || null,
          type: 'tool_use',
          tool_name: payload.tool_name,
          tool_input: payload.tool_input,
          tool_use_id: payload.tool_use_id,
          created_at: createdAt,
          timestamp: new Date(createdAt).toLocaleTimeString(),
        })
        scrollToBottom('terminal')
        scheduleRuntimeUsageRefresh()
        scheduleContextWindowRefresh()
        break
      }
  
      case 'tool_result': {
        // 工具执行结果 �?终端面板
        const createdAt = new Date().toISOString()
        terminalLogs.value.push({
          id: payload.id || null,
          type: 'tool_result',
          tool_use_id: payload.tool_use_id,
          output: payload.output,
          is_error: payload.is_error,
          created_at: createdAt,
          timestamp: new Date(createdAt).toLocaleTimeString(),
        })
        scrollToBottom('terminal')
        scheduleContextWindowRefresh()
        break
      }

      case 'skill_runtime_event': {
        mergeRuntimeTraceEvent(payload as SkillRuntimeEvent)
        scheduleContextWindowRefresh()
        break
      }
  
      case 'log': {
        // 原始日志 �?终端面板
        const createdAt = new Date().toISOString()
        terminalLogs.value.push({
          id: payload.id || null,
          type: 'log',
          content: payload.content,
          created_at: createdAt,
          timestamp: new Date(createdAt).toLocaleTimeString(),
        })
        scrollToBottom('terminal')
        break
      }
  
      case 'hitl_request': {
        // HITL 交互 �?置顶富文本卡�?(不进入对话流)
        const jobId = String(payload.job_id || '')
        if (jobId) {
          upsertHitlCardFromJob({
            id: jobId,
            task_id: payload.task_id,
            status: 'WAITING_HITL',
            progress: 60,
            context_json: {
              pending_hitl: {
                prompt: payload.prompt,
                hitl_type: payload.hitl_type,
                options: payload.options,
                context: payload.context,
              },
            },
          })
        } else {
          pinnedCards.value.push({
            id: Date.now().toString(),
            type: 'hitl',
            hitl_type: payload.hitl_type,
            prompt: payload.prompt,
            options: payload.options,
            context: payload.context,
            answered: false,
            answer: '',
            tempInput: '',
            job_id: '',
            created_at: new Date().toISOString(),
          })
        }
        break
      }
  
      case 'chat_job_update': {
        const job = payload?.job as ChatAiJob | undefined
        if (job?.id) {
          upsertChatJob(job)
        }
        break
      }
  
      case 'chat_job_done':
      case 'chat_job_failed': {
        const job = payload?.job as ChatAiJob | undefined
        if (job?.id) {
          upsertChatJob(job)
          if (job.status === 'FAILED') {
            ElMessage.error(job.error_message || t('chat.ai_job_failed_default'))
          }
        }
        scheduleContextWindowRefresh()
        break
      }

      case 'task_interrupted': {
        applyTaskSessionPayload(payload)
        engineRunning.value = false
        pinnedCards.value = pinnedCards.value.filter(c => c.type !== 'status')
        scheduleContextWindowRefresh()
        break
      }

      case 'task_resumed': {
        applyTaskSessionPayload(payload)
        engineRunning.value = true
        scheduleContextWindowRefresh()
        break
      }
  
      case 'spec_bootstrap_update': {
        if (!currentTask.value?.id) break
        if (String(payload?.task_id || '') !== String(currentTask.value.id)) break
        if (!hasTaskSpecification(currentTask.value)) break
        specBootstrap.value = payload as TaskSpecBootstrap
        break
      }
  
      case 'status': {
        // 阶段状�?�?置顶卡片
        engineRunning.value = payload.status === 'INIT' || payload.status === 'RUNNING'
        pinnedCards.value = pinnedCards.value.filter(c => c.type !== 'status')
        pinnedCards.value.push({
          id: Date.now().toString(),
          type: 'status',
          status: payload.status,
          message: payload.message,
          model: payload.model,
          created_at: new Date().toISOString(),
        })
        if (currentTask.value) {
          currentTask.value.status = 'CODING'
          const targetTask = tasks.value.find((task) => task.id === currentTask.value.id)
          if (targetTask) targetTask.status = 'CODING'
        }
        break
      }
  
      case 'result': {
        // 执行结果 �?汇总卡�?+ 标记引擎停止
        engineRunning.value = false
        pinnedCards.value = pinnedCards.value.filter(c => c.type !== 'status')
        
        resultsSummary.value.visible = true
        resultsSummary.value.totalDurationMs += payload.duration_ms || 0
        resultsSummary.value.totalCostUsd += (payload.cost_usd || 0)
        resultsSummary.value.history.push({
          id: Date.now().toString() + Math.random().toString().slice(2, 6),
          duration_ms: payload.duration_ms,
          cost_usd: payload.cost_usd,
          success: payload.success,
          result: payload.result,
          created_at: new Date().toISOString(),
          timestamp: new Date().toLocaleTimeString()
        })
  
        // 更新任务状�?
        if (currentTask.value) {
          currentTask.value.status = payload.success ? 'IDLE' : 'FAILED'
          const targetTask = tasks.value.find((task) => task.id === currentTask.value.id)
          if (targetTask) targetTask.status = currentTask.value.status
        }
        scheduleContextWindowRefresh()
        
        break
      }
    }
  }
  
  // ─── HITL 回复 ───
  const submitHitl = (cardId: string, response: string) => {
    if (!response) return
    const card = pinnedCards.value.find(c => c.id === cardId)
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      if (currentTask.value?.id) connectWebSocket(currentTask.value.id)
      return
    }
    ws.send(JSON.stringify({
      type: 'hitl_response',
      payload: {
        response,
        job_id: card?.job_id || undefined,
      }
    }))
    if (card) {
      card.answered = true
      card.answer = response
    }
    if (card?.job_id) {
      markHitlCardAnswered(card.job_id, response)
    }
  }
  
  // ─── 用户发送消�?───
  const sendChatContent = async (
    content: string,
    options: { displayContent?: string } = {},
  ): Promise<boolean> => {
    if (isTaskPreStart.value) {
      ElMessage.warning(t('chat.start_before_chat'))
      return false
    }
    if (sendingChat.value) return false
    const normalized = String(content || '').trim()
    if (!normalized) return false
    const displayContent = String(options.displayContent || normalized).trim()
    const clientMessageId = generateClientMessageId()
    sendingChat.value = true
    if (isTaskInterrupted.value && currentTask.value?.id) {
      try {
        const payload = await taskSessionControls.resumeInterruptedTask(currentTask.value.id, {
          prompt: normalized,
        })
        upsertChatMessage({
          id: `local-${clientMessageId}`,
          role: 'user',
          content: displayContent,
          created_at: new Date().toISOString(),
          message_type: 'text',
          client_message_id: clientMessageId,
          delivery_status: 'sent',
          ...localUserMessageMeta(),
        })
        applyTaskSessionPayload(payload)
        engineRunning.value = true
        scrollToBottom('chat')
        return true
      } catch (e) {
        console.error('Resume interrupted task failed', e)
        ElMessage.error(resolveActionError(e, 'chat.errors.resume_interrupted_failed', 'chat.errors.no_permission_start_task'))
        return false
      } finally {
        sendingChat.value = false
      }
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      if (currentTask.value?.id) connectWebSocket(currentTask.value.id)
      sendingChat.value = false
      return false
    }

    // 显示到本地对话气�?
    upsertChatMessage({
      id: `local-${clientMessageId}`,
      role: 'user',
      content: displayContent,
      created_at: new Date().toISOString(),
      message_type: 'text',
      client_message_id: clientMessageId,
      delivery_status: 'sending',
      ...localUserMessageMeta(),
    })
  
    // 通过 WebSocket 发送给后端 �?CLI 引擎
    try {
      ws.send(JSON.stringify({
        type: 'chat_message',
        payload: { role: 'user', content: normalized, client_message_id: clientMessageId }
      }))
      engineRunning.value = true
      scrollToBottom('chat')
      return true
    } finally {
      releaseSendingChatSoon()
    }
  }

  const sendChat = async () => {
    if (!chatInput.value.trim()) return
    const content = chatInput.value
    const sent = await sendChatContent(content)
    if (sent) {
      chatInput.value = ''
    }
  }
  
  // ─── 执行高阶 MCP 验证 ───
  const sendVerification = async (type: 'ui' | 'api' | 'e2e') => {
    let prompt = ''
    if (type === 'ui') {
      prompt = t('chat.verification_prompt_ui')
    } else if (type === 'api') {
      prompt = t('chat.verification_prompt_api')
    } else if (type === 'e2e') {
      prompt = t('chat.verification_prompt_e2e')
    }
    if (isTaskInterrupted.value) {
      await sendChatContent(prompt)
      return
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      if (currentTask.value?.id) connectWebSocket(currentTask.value.id)
      return
    }
    
    await sendChatContent(prompt, {
      displayContent: `[${t('chat.verification_tag')}] ${prompt}`,
    })
  }
  
  // ─── 启动引擎 ───
  const startTask = async (): Promise<boolean> => {
    if (!currentTask.value) return false
    if (!isStartActionVisible.value) return false
    if (!canStartTask.value) {
      ElMessage.warning(t('chat.errors.no_permission_start_task'))
      return false
    }
    if (startingTask.value) return false
    startingTask.value = true
  
    // 使用任务描述作为初始 prompt
    const prompt = currentTask.value.description || t('chat.start_default_prompt', {
      taskName: currentTask.value.name || '',
    })
  
    try {
      await api.post(
        `/workspaces/${route.params.wsId}/tasks/${currentTask.value.id}/start`,
        { prompt }
      )
  
      currentTask.value.status = 'CODING'
      engineRunning.value = true
      showStartConfirm.value = false
      specDrawerLevel.value = 0
  
      messages.value.push({
        id: Date.now().toString(),
        role: 'system',
        content: '🚀 ' + t('dashboard.new_task') + '...',
        created_at: new Date().toISOString(),
        message_type: 'text',
      })
      scrollToBottom('chat')
      return true
    } catch (e) {
      console.error('Start task failed', e)
      ElMessage.error(resolveActionError(e, 'chat.errors.start_failed', 'chat.errors.no_permission_start_task'))
      return false
    } finally {
      startingTask.value = false
    }
  }
  
  const handleStartClick = () => {
    if (!currentTask.value) return
    if (!isStartActionVisible.value) return
    if (!canStartTask.value) {
      ElMessage.warning(t('chat.errors.no_permission_start_task'))
      return
    }
    if (startingTask.value) return
    showStartConfirm.value = true
  }
  
  // ─── Lifecycle ───
  onMounted(() => {
    window.addEventListener('blur', cancelAllInlineOverlayClose)
    restoreChatWorkbenchMode()
    if (authStore.token) void authStore.fetchCurrentUser()
    loadTasks()
    loadWorkspace()
  })
  
  onUnmounted(() => {
    window.removeEventListener('blur', cancelAllInlineOverlayClose)
    wsManualClose = true
    clearWsReconnectTimer()
    clearRuntimeUsageRefreshTimer()
    clearContextWindowRefreshTimer()
    clearReferenceHighlight()
    if (ws) ws.close()
  })

  return {
    activeChatJobs,
    activeHitlCards,
    activeInitialSpecAssetId,
    applySpecDrawerLevel,
    armInlineOverlayClose,
    bootstrapStatusText,
    buildTaskWsUrl,
    cancelAllInlineOverlayClose,
    cancelDeletedRuntimeSkillConfirm,
    cancelInlineOverlayClose,
    canCreateTask,
    canDeleteTask,
    canEditTaskRuntimeSkills,
    canEditSuperpowersDocs,
    canExportTask,
    canManageTaskStatus,
    canStartTask,
    canClickStartAction,
    canInitializeAction,
    canTemporarilyInterrupt,
    chatWorkbenchMode,
    chatContainer,
    chatInput,
    chatInputPlaceholder,
    clearTaskHistory,
    clearWsReconnectTimer,
    closeDeleteTaskConfirm,
    closeContextWindowDrawer,
    closeoutMode,
    decisionModalOpen,
    decisionSourceMessage,
    chatDecisionSaving: chatDecision.saving,
    chatDecisionError: chatDecision.error,
    closeSpecDrawer,
    closeTaskCloseout,
    closeDecisionModal,
    completeOverlayCloseArmed,
    completeTaskNow,
    confirmComplete,
    confirmDeleteTask,
    confirmInitialize,
    confirmInitializeWithDeletedRuntimeSkillDecision,
    confirmInterrupt,
    connectWebSocket,
    currentPage,
    currentTask,
    currentTaskHasSpec,
    currentWorkspace,
    contextWindowData: contextWindow.data,
    contextWindowDrawerLevel,
    contextWindowDrawerOpen,
    contextWindowError: contextWindow.error,
    contextWindowLoading: contextWindow.loading,
    contextWindowSegmentsLoading: contextWindow.segmentsLoading,
    contextWindowSelectedCategory: contextWindow.selectedCategory,
    deletingTask,
    deletedRuntimeSkillsForInitialize,
    deletedRuntimeSkillNamesForInitialize,
    engineRunning,
    finishInlineOverlayClose,
    formatMessageTime,
    formatTime,
    formatToolInput,
    handleChatScroll,
    handleCollapseDrawer,
    handleCompleteClick,
    handleDeleteTask,
    handleExpandDrawer,
    handleExport,
    handleInitialize,
    handleInterruptClick,
    highlightedMessageId,
    highlightedTerminalLogId,
    handleSpecEntryClick,
    handleStartClick,
    handleTaskCloseoutSuccess,
    handleWsMessage,
    hasMore,
    hasTaskSpecDoc,
    hasTaskSpecification,
    initializeTaskWithReason,
    initSelectedSkillIds,
    initSkillOptions,
    initSkillOptionsLoading,
    initReason,
    interruptCurrentRun,
    interruptingTask: taskSessionControls.interruptingTask,
    interruptTaskNow,
    interruptOverlayCloseArmed,
    isChatLocked,
    isForbiddenError,
    isJobActive,
    isJobExecuting,
    isMessageFromCurrentUser,
    isMessageWorkspaceExpert,
    isSpecBootstrapActive,
    isSpecDrawerAvailable,
    isSpecPanelOpen,
    isSuperpowersDocsAvailable,
    isStartActionVisible,
    isTaskInterrupted,
    isTaskPreStart,
    isTerminalStatus,
    lastOpenSpecDrawerLevel,
    loadActiveChatJobs,
    loadHistory,
    loadingMore,
    loadOlderMessages,
    loadTasks,
    loadTaskSpecBootstrap,
    loadWorkspace,
    locateContextWindowReference,
    canMarkMessageAsDecision,
    openDecisionModal,
    markHitlCardAnswered,
    messageAuthorLabel,
    messages,
    closeTaskSkillsDrawer,
    closeDiagnosisDocsDrawer,
    openTaskSkillsDrawer,
    diagnosisDocsDrawerOpen,
    toggleDiagnosisDocsDrawer,
    createDiagnosisCase,
    diagnosisCaseCreating,
    diagnosisCaseLink,
    diagnosisResult,
    diagnosisResultLoading,
    diagnosisResultSaving,
    hidePatchWorkflows,
    isDiagnosisTask,
    loadDiagnosisResult,
    patchMessageMetadata,
    saveDiagnosisResult,
    taskTypeFilter,
    applyTaskTypeFilter,
    openContextWindowDrawer,
    onTaskCreated,
    openNewTaskModal,
    openSpecWorkspace,
    pinnedCards,
    preferredSpecAssetId,
    preferredSpecTaskId,
    requestSpecDrawerLevel,
    resetChatJobState,
    resolveActionError,
    resultsSummary,
    resumingInterruptedTask: taskSessionControls.resumingInterruptedTask,
    route,
    router,
    scheduleWsReconnect,
    scrollToBottom,
    selectTask,
    selectContextWindowCategory,
    selectRuntimeSkill,
    selectRuntimeSkillFile,
    sendChat,
    sendChatContent,
    sendVerification,
    sendingChat,
    setChatWorkbenchMode,
    showCompleteConfirm,
    showDeleteTaskConfirm,
    showDeletedRuntimeSkillConfirm,
    showInitReasonModal,
    showInterruptConfirm,
    showSpecEntryButton,
    showStartConfirm,
    showTaskModal,
    submitMessageDecision,
    showTaskSkillsDrawer,
    showThinking,
    specBootstrap,
    specBootstrapLoading,
    specDrawerLevel,
    specDrawerTab,
    startingTask,
    startTask,
    statusCards,
    submitHitl,
    syncEngineRunningFromJobs,
    t,
    tasks,
    taskToDelete,
    taskListContainer,
    taskListHasMore,
    taskListLoading,
    taskListLoadingMore,
    taskRuntimeSkillCount,
    taskRuntimeSkills,
    taskRuntimeSkillsLoading,
    taskRuntimeSkillsUsageScopeStartAt,
    refreshContextWindow,
    runtimeTraceEvents,
    runtimeTraceLoading,
    taskStatusFilter,
    terminalContainer,
    terminalLogs,
    thinkingContent,
    thinkingExpanded,
    runtimeActiveFileBinary,
    runtimeActiveFileContent,
    runtimeActiveFileDirty,
    runtimeActiveFileLoading,
    runtimeActiveFilePath,
    runtimeActiveFileSaving,
    runtimeActiveSkill,
    runtimeActiveSkillId,
    runtimeFileTree,
    runtimeFileTreeLoading,
    applyTaskStatusFilter,
    handleTaskListScroll,
    loadInitSkillOptions,
    loadMoreTasks,
    loadRuntimeSkillFileTree,
    loadTaskRuntimeSkills,
    loadTaskRuntimeTrace,
    saveRuntimeSkillFileContent,
    updateContextWindowDrawerLevel,
    updateRuntimeSkillFileContent,
    upsertChatJob,
    upsertHitlCardFromJob,
    workspacePermissions,
    wsManualClose,
  }
}

export type ChatViewModel = ReturnType<typeof useChatViewModel>
