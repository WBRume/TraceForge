import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { ShallowUnwrapRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import api from '@/utils/api'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useProvisioningStore } from '@/stores/provisioning'
import { useChatMessageContext } from '@/composables/useChatMessageContext'
import { useChatSubmissions } from '@/composables/useChatSubmissions'
import { useTaskSessionControls } from '@/composables/useTaskSessionControls'
import { useChatWorkbenchScroll, type ChatWorkbenchMode } from '@/composables/useChatWorkbenchScroll'
import { useChatDecision } from '@/composables/useChatDecision'
import { buildBackendWsUrl } from '@/utils/ws'
import { buildWsCursorQuery, sendResyncComplete } from '@/utils/wsCursor'
import { formatTime, formatToolInput } from '@/utils/chatFormatters'
import { createResolveActionError } from './shared/requestGuards'
import { createMessagePresenters, formatMessageTime } from './message/presenters'
import { messageAuthorColor, memberColorFor, memberColorRgba } from './message/memberColor'
import { useCurrentTask } from './session/useCurrentTask'
import { useTaskWebSocket } from './session/useTaskWebSocket'
import { useSessionState } from './session/useSessionState'
import { createTaskWsEventRouter } from './session/wsEventRouter'
import { useChatSend } from './session/useChatSend'
import { useWorkspaceContext } from './tasklist/useWorkspaceContext'
import { useTaskList } from './tasklist/useTaskList'
import { useChatMessages } from './message/useChatMessages'
import { useTerminalLogs } from './message/useTerminalLogs'
import { useChatHistory } from './message/useChatHistory'
import { usePinnedCards } from './cards/usePinnedCards'
import { useChatJobs } from './jobs/useChatJobs'
import { createChatJobIngest } from './jobs/jobIngest'
import { useEngineState } from './runtime/useEngineState'
import { useResultsSummary } from './runtime/useResultsSummary'
import { useTaskRuntimeSkills } from './runtime/useTaskRuntimeSkills'
import { useSpecDrawer } from './spec/useSpecDrawer'
import { useSpecBootstrap } from './spec/useSpecBootstrap'
import { useReferenceHighlight } from './context/useReferenceHighlight'
import { useContextWindowPanel } from './context/useContextWindowPanel'
import { useDiagnosis } from './diagnosis/useDiagnosis'
import { usePreInput } from './preinput/usePreInput'
import { useTaskStartActions } from './actions/useTaskStartActions'
import { useTaskStatusActions } from './actions/useTaskStatusActions'
import { useTaskAdminActions } from './actions/useTaskAdminActions'
import { useMessageActions } from './actions/useMessageActions'
import { useTaskReadingProgress } from './reading/useTaskReadingProgress'
import { fetchReadingResume } from '@/services/taskReadingApi'

/**
 * Chat 视图模型组合根：把各领域模块（任务列表、消息、历史、卡片、jobs、
 * 运行时技能、spec、上下文窗口、诊断、预输入、传输与会话恢复、任务动作）
 * 按依赖方向装配起来，并承担跨域编排（会话切换、生命周期、路由联动）。
 *
 * 领域模块之间互不 import——全部依赖经由本根以窄接口（getter / 回调）注入。
 */
export function useChatViewModel() {
  const { t } = useI18n()
  const route = useRoute()
  const router = useRouter()
  const authStore = useAuthStore()

  const getWorkspaceId = () => String(route.params.wsId || '')
  const resolveActionError = createResolveActionError(t)

  // ─── 会话实体与协作对象 ───
  const taskState = useCurrentTask()
  const workspaceContext = useWorkspaceContext({ getWorkspaceId })
  const historyContext = useChatMessageContext()
  const submissions = useChatSubmissions({
    workspaceId: getWorkspaceId,
    taskId: () => String(taskState.currentTask.value?.id || ''),
    userId: () => String(authStore.user?.id || ''),
  })
  const taskSessionControls = useTaskSessionControls({ getWorkspaceId })
  const chatDecision = useChatDecision()

  // ─── 工作台模式与滚动 ───
  const CHAT_WORKBENCH_MODE_KEY = 'sdd.chat.workbench.mode'
  const chatWorkbenchMode = ref<ChatWorkbenchMode>('platform')
  const workbenchScroll = useChatWorkbenchScroll({
    activeMode: chatWorkbenchMode,
    getTaskId: taskState.getTaskId,
  })
  const { chatContainer, terminalContainer, scrollToBottom, setTerminalContainer } = workbenchScroll
  const setChatWorkbenchMode = async (mode: ChatWorkbenchMode) => {
    localStorage.setItem(CHAT_WORKBENCH_MODE_KEY, mode)
    await workbenchScroll.switchMode(mode)
  }
  const restoreChatWorkbenchMode = () => {
    const cached = String(localStorage.getItem(CHAT_WORKBENCH_MODE_KEY) || '').toLowerCase()
    chatWorkbenchMode.value = cached === 'cli' ? 'cli' : 'platform'
  }

  // ─── 消息 / 终端日志 / 卡片 / 高亮 ───
  const messages = useChatMessages({
    submissions,
    historyContext,
    getWorkspaceId,
    getCreatorMeta: () => ({
      creator_id: authStore.user?.id || null,
      creator_display_name: authStore.user?.display_name || 'You',
      creator_is_workspace_expert: workspaceContext.isWorkspaceExpert(),
      creator_avatar_url: authStore.user?.avatar_url || null,
      creator_avatar_svg: authStore.user?.avatar_svg || null,
    }),
  })
  const terminalLogs = useTerminalLogs()
  const cards = usePinnedCards({ getMessages: () => messages.messages.value })
  const highlight = useReferenceHighlight()

  // 撤销状态被「发送」与「消息动作」两个模块共同依赖，归组合根持有
  const undoingMessageId = ref('')

  const resultsSummary = useResultsSummary()
  const engine = useEngineState({
    getStatusCards: () => cards.statusCards.value,
    onStatusCardPush: (card) => cards.pushStatusCard(card),
    onStatusCardsDrop: () => cards.dropStatusCards(),
    hasExecutingJob: () => jobs.hasExecutingJob(),
  })
  const isUndoing = computed(() => Boolean(undoingMessageId.value))
  const isChatLocked = computed(() => (
    taskState.isTerminalStatus.value
    || taskState.isTaskPreStart.value
    || taskState.isTaskProvisioning.value
    || isUndoing.value
  ))

  // ─── 任务列表（selectRouteTask 由会话编排晚绑定，规避创建顺序环） ───
  const taskList = useTaskList({
    getWorkspaceId,
    selectRouteTask: (loadOptions) => selectRouteTask(loadOptions),
    canCreateTask: () => workspaceContext.canCreateTask.value,
  })

  const jobs = useChatJobs({
    getWorkspaceId,
    getTaskId: taskState.getTaskId,
    getSignal: () => sessionState.getAbortSignal(),
    onLoaded: (taskId, items) => engine.convergeFromJobs(taskId, items),
  })

  const skills = useTaskRuntimeSkills({
    getWorkspaceId,
    getTaskId: taskState.getTaskId,
    getCurrentTask: () => taskState.currentTask.value,
    getSignal: () => sessionState.getAbortSignal(),
    canEdit: () => canEditTaskRuntimeSkills.value,
  })

  const openSpecWorkspace = () => {
    const task = taskState.currentTask.value
    if (!task || !specDrawer.currentTaskHasSpec.value) return
    router.push(`/workspaces/${getWorkspaceId()}/chat/${task.id}/spec`)
  }

  const specDrawer = useSpecDrawer({
    currentTask: taskState.currentTask,
    isTaskPreStart: taskState.isTaskPreStart,
    isDiagnosisTask: taskState.isDiagnosisTask,
    openSpecWorkspace: () => openSpecWorkspace(),
  })

  const specBootstrap = useSpecBootstrap({
    getWorkspaceId,
    currentTask: taskState.currentTask,
    hasTaskSpecification: specDrawer.hasTaskSpecification,
  })

  const contextPanel = useContextWindowPanel({
    getWorkspaceId,
    getTaskId: taskState.getTaskId,
    getActiveJobId: () => {
      const activeJob = Object.values(jobs.activeChatJobs.value).find((job) => (
        job.status === 'PENDING'
        || job.status === 'RUNNING'
        || job.status === 'WAITING_HITL'
        || job.status === 'INTERRUPTED'
      ))
      return activeJob?.id || null
    },
    setWorkbenchMode: setChatWorkbenchMode,
    scrollToTerminalBottom: () => scrollToBottom('terminal'),
    highlight,
  })

  // job 摄取管线：诊断的终态刷新晚绑定（diagnosis 创建在 ingest 之后，调用发生在运行期）
  let ingestRef: ((job: any) => void) | null = null
  const ingestJob = (job: any) => ingestRef?.(job)

  const diagnosis = useDiagnosis({
    getWorkspaceId,
    currentTask: taskState.currentTask,
    currentWorkspace: workspaceContext.currentWorkspace,
    activeChatJobs: jobs.activeChatJobs,
    ingestJob,
    findMessage: (messageId) => messages.findById(messageId),
    router,
  })

  ingestRef = createChatJobIngest({
    jobs,
    cards,
    syncEngineFromJobs: engine.syncFromJobs,
    onJobUpdate: (job) => diagnosis.onJobUpdate(job),
  })

  const preinput = usePreInput({
    getWorkspaceId,
    getCurrentTask: () => taskState.currentTask.value,
    isEngineRunning: () => engine.engineRunning.value,
    isChatLocked: () => isChatLocked.value,
    isWorkspaceExpert: () => workspaceContext.isWorkspaceExpert(),
    sendAction: (action, payload) => sendPreInputAction(action, payload),
    getSignal: () => sessionState.getAbortSignal(),
  })

  const history = useChatHistory({
    getWorkspaceId,
    getCurrentTask: () => taskState.currentTask.value,
    route,
    router,
    historyContext,
    messages,
    terminalLogs: {
      clear: terminalLogs.clear,
      restoreFromHistory: terminalLogs.restoreFromHistory,
    },
    cards: {
      syncConfirmationCards: cards.syncConfirmationCards,
    },
    highlight: {
      highlightedMessageId: highlight.highlightedMessageId,
      scheduleClear: highlight.scheduleClear,
      clear: highlight.clear,
    },
    getChatContainer: () => chatContainer.value,
    restoreWorkbenchScroll: (taskId) => workbenchScroll.restoreScrollPosition(chatWorkbenchMode.value, taskId),
    scrollToChatBottom: () => scrollToBottom('chat'),
  })

  // ─── 阅读进度与续读（产品裁剪版） ───

  const readingProgress = useTaskReadingProgress({
    getWorkspaceId,
    getTaskId: taskState.getTaskId,
    isTaskActive: () => Boolean(authStore.token) && taskState.getTaskId() === String(route.params.taskId || taskState.getTaskId()),
  })

  // ─── 续读提示条：进入任务时有未读才出现，点击继续/关闭后消失 ───

  /**
   * 未读快照：仅在进入任务后第一次看到“有未读”状态时冻结计数（entry-only）。
   * - 首次进入的会话：基线刚建立、无未读 → 不显示；
   * - 会话期间新到的消息不弹（用户正在现场看）；
   * - 关闭/继续后本次访问不再出现，重新进入任务时按最新未读重建。
   */
  const readingUnreadSnapshot = ref<{ value: string; relation: 'eq' | 'gte'; atSeq: string } | null>(null)
  watch(readingProgress.progress, (state) => {
    if (readingUnreadSnapshot.value) return
    if (!state?.initialized || !state.has_unread) return
    readingUnreadSnapshot.value = {
      value: String(state.unread_count.value),
      relation: state.unread_count.relation,
      atSeq: String(state.latest_change_seq),
    }
  })

  /**
   * 提示条展示条件：存在未读快照 且 未被本次点击消除。
   * 点击「从上次阅读处继续」即记录当时的内容水位，提示条消失；
   * 之后有更新的内容（latest_change_seq 前进）时重新出现。
   */
  const resumeDismissedAtSeq = ref<string | null>(null)
  /** 用户点击关闭：仅收起提示条，不确认未读；重新进入任务仍会提示。 */
  const readingBannerClosed = ref(false)
  const closeResumeBanner = () => {
    readingBannerClosed.value = true
  }

  const showResumeBanner = computed(() => {
    const state = readingProgress.progress.value
    if (!state?.initialized || !readingUnreadSnapshot.value || readingBannerClosed.value) return false
    if (resumeDismissedAtSeq.value) {
      try {
        if (BigInt(state.latest_change_seq) <= BigInt(resumeDismissedAtSeq.value)) return false
      } catch {
        return false
      }
    }
    return true
  })

  /** 在当前（最新）视图中定位锚点消息：高亮并滚动到其附近（近似恢复 offset_ratio）。 */
  const scrollToMessageInLatestView = async (anchorId: string, ratio: number | null): Promise<boolean> => {
    await nextTick()
    if (!messages.findById(anchorId)) return false
    const container = chatContainer.value
    const target = container?.querySelector(`[data-message-id="${CSS.escape(anchorId)}"]`) as HTMLElement | null
    if (!target) return false
    highlight.highlightedMessageId.value = anchorId
    if (container && typeof ratio === 'number' && target.offsetHeight > container.clientHeight * 0.5) {
      // 超长消息：按保存的消息内相对位置近似恢复
      container.scrollTop = Math.max(0, target.offsetTop - container.clientHeight * 0.2 + target.offsetHeight * ratio)
    } else {
      target.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }
    highlight.scheduleClear()
    return true
  }

  /**
   * “从上次阅读处继续”：在当前最新视图中直接定位到未读起点（上次阅读边界），
   * 并确认当前整批未读（提示条不再对这批内容重复出现）。
   * 不进入「正在查看历史消息」锚定模式；锚点早于已加载页面时逐页向前加载
   * （有界），仍不可达才退回锚定上下文视图兜底。
   */
  const resumeFromLastRead = async () => {
    const taskId = taskState.getTaskId()
    if (!taskId) return
    resumeDismissedAtSeq.value = String(readingProgress.progress.value?.latest_change_seq ?? '0')
    try {
      const result = await fetchReadingResume({ workspaceId: getWorkspaceId(), taskId })
      if (!result || result.anchor_status === 'none' || !result.initialized) {
        ElMessage.info(t('reading.resume_none'))
        return
      }
      if (result.anchor_status === 'empty') {
        ElMessage.info(t('reading.resume_empty'))
        return
      }
      const anchorId = String(result.anchor?.message_id || '')
      if (!anchorId) {
        ElMessage.info(t('reading.resume_none'))
        return
      }
      // 确认当前整批未读（§8.4 显式确认：仅覆盖签名窗口上界）
      await readingProgress.acknowledgeAll(taskId)
      // 若正处于锚定定位（搜索/引用跳转），先回到最新视图
      if (historyContext.anchored.value || String(route.query.messageId || '')) {
        await history.returnToLatest()
      }
      // 最新页尚未加载完成时先加载一次
      if (!messages.visibleMessages.value.length) {
        await history.loadHistory(taskId, true)
      }
      // 锚点在已加载范围内 → 直接滚动；否则逐页向前加载（有界 6 页）
      let found = await scrollToMessageInLatestView(anchorId, result.anchor?.offset_ratio ?? null)
      let pages = 0
      while (!found && history.hasMore.value && pages < 6) {
        await history.loadOlderMessages()
        found = await scrollToMessageInLatestView(anchorId, result.anchor?.offset_ratio ?? null)
        pages += 1
      }
      if (!found) {
        // 兜底：锚点非常早（超过有界加载），退回锚定上下文视图
        await history.loadAnchorContext(anchorId)
      }
      if (result.anchor_status === 'updated') ElMessage.info(t('reading.anchor_updated'))
      else if (result.anchor_status === 'retracted') ElMessage.info(t('reading.anchor_retracted'))
      else if (result.anchor_status === 'missing') ElMessage.info(t('reading.anchor_missing'))
    } catch {
      ElMessage.warning(t('reading.resume_unavailable'))
    }
  }

  const sessionState = useSessionState({
    getWorkspaceId,
    getCurrentTask: () => taskState.currentTask.value,
    submissions: {
      unconfirmedKeys: submissions.unconfirmedKeys,
      current: () => submissions.current.value,
      put: submissions.put,
      send: (taskId, clientId, content, metadata) => submissions.send(taskId, clientId, content, metadata),
      clear: submissions.clear,
    },
    ingestJob,
    syncEngineFromJobs: engine.syncFromJobs,
    convergeFromJobs: engine.convergeFromJobs,
    syncConfirmationCards: cards.syncConfirmationCards,
    upsertMessage: messages.upsert,
    loadHistory: (taskId, reset) => history.loadHistory(taskId, reset),
    loadActivePreInput: (taskId) => preinput.loadActive(taskId),
    onSessionGenerationBump: () => history.bumpGeneration(),
    syncTaskStatus,
    reloadSpecBootstrap: (taskId) => void specBootstrap.load(taskId, taskState.currentTask.value),
    hasTaskSpecification: specDrawer.hasTaskSpecification,
  })

  const ws = useTaskWebSocket({
    buildUrl: (taskId) => buildBackendWsUrl(`/ws/task/${taskId}`, {
      token: authStore.token || undefined,
      ...buildWsCursorQuery(`task:${taskId}`),
    }),
    isCurrentTask: (taskId) => taskState.getTaskId() === String(taskId),
    handlers: {
      onEvent: (event) => handleWsMessage({ type: event.event_type, payload: event.payload }),
      onControlFrame: (frame, taskId) => {
        const frameType = String(frame?.type || '')
        if (frameType === 'resume_ok' || frameType === 'resync_ok') {
          // 首次订阅就绪：replay/屏障已完成，此时 HTTP 快照不会被旧的 WS 增量覆盖
          const wasReady = ws.isSubscriptionReady(taskId)
          ws.markSubscriptionReady(taskId)
          sessionState.onInitialSubscriptionReady(taskId, wasReady)
          // 就绪后补取一次个人阅读快照（覆盖断线期间的私有变更）
          void readingProgress.onConnectionReady(taskId)
          return
        }
        if (frameType === 'reading_progress_changed') {
          // 私有失效通知：无公共序号的业务事件，不进入公共回放分支
          readingProgress.handleWsFrame(frame.payload)
          return
        }
        handleWsMessage(frame)
      },
      onResync: async (taskId, frame, _reason, context, signal) => {
        await sessionState.restoreSessionState(taskId)
        if (!signal.aborted && context.socket === ws.getSocket() && context.socket.readyState === WebSocket.OPEN) {
          sendResyncComplete(context.socket, frame, `task:${taskId}`)
        }
      },
      onSocketOpen: (taskId) => {
        if (taskState.getTaskId() === taskId && specDrawer.hasTaskSpecification(taskState.currentTask.value)) {
          void specBootstrap.load(taskId)
        }
      },
      onSocketClose: (taskId, code) => {
        if (code === 1008) {
          ws.showAuthExpiredToast()
          return
        }
        if (taskState.getTaskId() !== taskId) return
        // 断线期间仍有待处理回执：连接恢复前先以数据库快照收敛一次。
        if (submissions.busy.value) void sessionState.recoverSession('ws-closed-pending-receipts')
        if (!ws.isSubscriptionReady(taskId)) {
          // 首次订阅未就绪即断开：HTTP 兜底，重连后仍走恢复协议刷新
          sessionState.onInitialConnectionUnavailable(taskId)
        }
        ws.scheduleReconnect(taskId)
      },
      onConnectionReuse: (taskId, subscriptionReady) => {
        if (subscriptionReady) {
          void sessionState.loadSessionStateOnce(taskId)
        } else {
          sessionState.armSessionStateFallback(taskId)
        }
      },
      onConnectionError: (taskId) => sessionState.onInitialConnectionUnavailable(taskId),
    },
  })

  // ─── WS 事件路由（传输 → 领域） ───
  // 分享建议域由 ChatView 的 useShareFlows 持有（与分享弹窗同生命周期），
  // nudge 经此回调槽转发，避免 vm ↔ shareFlows 循环依赖。
  let shareSuggestionNudgeHandler: ((payload: any) => void) | null = null
  const registerShareSuggestionNudge = (handler: (payload: any) => void) => {
    shareSuggestionNudgeHandler = handler
  }
  const wsRouter = createTaskWsEventRouter({
    task: {
      getTaskId: taskState.getTaskId,
      patchSessionGeneration: (generation) => {
        if (taskState.currentTask.value) taskState.currentTask.value.session_generation = generation
      },
      syncTaskStatus,
      getCurrentSessionGeneration: () => Number(taskState.currentTask.value?.session_generation || 0),
      getCurrentTaskStatus: () => String(taskState.currentTask.value?.status || ''),
    },
    messages: {
      upsert: messages.upsert,
      findByIdentity: messages.findByIdentity,
      removeByIds: messages.removeByIds,
    },
    terminalLogs: {
      appendToolUse: terminalLogs.appendToolUse,
      appendToolResult: terminalLogs.appendToolResult,
      appendLog: terminalLogs.appendLog,
      clear: terminalLogs.clear,
    },
    cards: {
      syncConfirmationCards: cards.syncConfirmationCards,
      dropStatusCards: cards.dropStatusCards,
      pushStatusCard: cards.pushStatusCard,
      clear: cards.clear,
    },
    engine: {
      engineRunning: engine.engineRunning,
      syncFromJobs: engine.syncFromJobs,
      applyThinkingFrame: engine.applyThinkingFrame,
      resetThinking: engine.resetThinking,
    },
    resultsSummary: {
      appendResult: resultsSummary.appendResult,
    },
    submissions: {
      busy: () => submissions.busy.value,
      put: submissions.put,
      removeMessages: submissions.removeMessages,
    },
    ingestJob,
    refreshActiveJobs: (taskId) => jobs.loadActive(taskId),
    applyTaskSessionPayload: sessionState.applyTaskSessionPayload,
    specBootstrapApplyUpdate: specBootstrap.applyUpdate,
    shareSuggestionNudge: (payload) => shareSuggestionNudgeHandler?.(payload),
    preinputHandleEvent: preinput.handleEvent,
    skillsMergeTraceEvent: skills.mergeRuntimeTraceEvent,
    skillsScheduleUsageRefresh: skills.scheduleRuntimeUsageRefresh,
    onSessionGenerationBump: () => history.bumpGeneration(),
    contextWindowScheduleRefresh: contextPanel.scheduleRefresh,
    scrollTo: scrollToBottom,
    isHistoryAnchored: () => historyContext.anchored.value,
    getRouteMessageId: () => String(route.query.messageId || ''),
  })
  const handleWsMessage = wsRouter.handleWsMessage

  // ─── 发送 / 消息动作 / 任务动作 ───
  const send = useChatSend({
    getWorkspaceId,
    getTaskId: taskState.getTaskId,
    task: {
      getCurrentTask: () => taskState.currentTask.value,
      isTaskPreStart: taskState.isTaskPreStart,
      isTaskProvisioning: taskState.isTaskProvisioning,
      isTaskInterrupted: taskState.isTaskInterrupted,
      isTerminalStatus: taskState.isTerminalStatus,
    },
    submissions: {
      busy: submissions.busy,
      send: submissions.send,
      current: submissions.current,
    },
    messages: {
      upsert: messages.upsert,
    },
    noteSentTime: messages.noteSentTime,
    findHitlCard: (cardId) => cards.findHitlByCardId(cardId),
    engine: {
      engineRunning: engine.engineRunning,
    },
    ws: {
      isOpen: ws.isOpen,
      sendFrame: ws.sendFrame,
      connect: (taskId) => ws.connect(taskId),
    },
    recoverSession: (reason) => sessionState.recoverSession(reason),
    resumeInterruptedTask: (taskId, resumeOptions) => taskSessionControls.resumeInterruptedTask(taskId, resumeOptions),
    applyTaskSessionPayload: sessionState.applyTaskSessionPayload,
    isUndoing: () => isUndoing.value,
    isHistoryAnchored: () => historyContext.anchored.value,
    returnToLatest: () => history.returnToLatest(),
    getCreatorMeta: () => ({
      creator_id: authStore.user?.id || null,
      creator_display_name: authStore.user?.display_name || 'You',
      creator_is_workspace_expert: workspaceContext.isWorkspaceExpert(),
      creator_avatar_url: authStore.user?.avatar_url || null,
      creator_avatar_svg: authStore.user?.avatar_svg || null,
    }),
    scrollTo: (target) => scrollToBottom(target),
    resolveActionError,
  })

  const messageActions = useMessageActions({
    getCurrentTask: () => taskState.currentTask.value,
    canManageTaskStatus: workspaceContext.canManageTaskStatus,
    getWorkspaceId,
    undoingMessageId,
    sendingChat: () => send.sendingChat.value,
    submissions: {
      current: () => submissions.current.value,
      removeMessages: submissions.removeMessages,
    },
    messages: {
      removeByIds: messages.removeByIds,
      findById: (messageId) => messages.findById(messageId),
    },
    terminalLogsClear: terminalLogs.clear,
    cardsClear: cards.clear,
    engineRunning: engine.engineRunning,
    engineResetThinking: engine.resetThinking,
    jobsReset: jobs.reset,
    bumpHistoryGeneration: history.bumpGeneration,
    loadHistory: (taskId, reset) => history.loadHistory(taskId, reset),
    undoTaskMessage: (taskId, messageId, undoOptions) => taskSessionControls.undoTaskMessage(taskId, messageId, undoOptions),
    restoreComposer: (content) => {
      send.chatInput.value = content
    },
    scheduleContextWindowRefresh: contextPanel.scheduleRefresh,
    resolveActionError,
    markMessageAsDecision: chatDecision.markMessageAsDecision,
    decisionError: chatDecision.error,
  })

  // ─── 跨模块视图复位 ───
  const clearConversationView = () => {
    messages.reset()
    terminalLogs.clear()
    cards.clear()
    engine.resetThinking()
    resultsSummary.reset()
  }
  const resetConversationView = () => {
    clearConversationView()
    jobs.reset()
    engine.engineRunning.value = false
  }

  const canEditTaskRuntimeSkills = computed(() => (
    Boolean(taskState.currentTask.value) && workspaceContext.canManageTaskStatus.value
  ))
  const canShareTaskSession = computed(() => Boolean(
    taskState.currentTask.value && workspaceContext.workspacePermissions.value?.share_task_session
  ))

  const startActions = useTaskStartActions({
    getCurrentTask: () => taskState.currentTask.value,
    isTaskPreStart: taskState.isTaskPreStart,
    isTaskProvisioning: taskState.isTaskProvisioning,
    canStartTask: workspaceContext.canStartTask,
    canManageTaskStatus: workspaceContext.canManageTaskStatus,
    getWorkspaceId,
    engineRunning: engine.engineRunning,
    submissionsClear: submissions.clear,
    loadHistory: (taskId, reset) => history.loadHistory(taskId, reset),
    refreshActiveJobs: (taskId) => jobs.loadActive(taskId),
    resetConversationView,
    patchTask: taskList.patchTask,
    specDrawerClose: specDrawer.closeSpecDrawer,
    scrollIfNotAnchored: () => {
      if (!historyContext.anchored.value) scrollToBottom('chat')
    },
    skills: {
      taskRuntimeSkills: skills.taskRuntimeSkills,
      taskRuntimeSkillsLoading: skills.taskRuntimeSkillsLoading,
      showTaskSkillsDrawer: skills.showTaskSkillsDrawer,
      loadTaskRuntimeSkills: skills.loadTaskRuntimeSkills,
    },
    resolveActionError,
  })

  const statusActions = useTaskStatusActions({
    getCurrentTask: () => taskState.currentTask.value,
    isTaskProvisioning: taskState.isTaskProvisioning,
    canManageTaskStatus: workspaceContext.canManageTaskStatus,
    getWorkspaceId,
    engineRunning: engine.engineRunning,
    interruptingTask: taskSessionControls.interruptingTask,
    cardsDropStatusCards: cards.dropStatusCards,
    cardsDropByTypes: cards.dropByTypes,
    jobsReset: jobs.reset,
    messagesPush: (message) => messages.messages.value.push(message),
    isHistoryAnchored: () => historyContext.anchored.value,
    scrollToChatBottom: () => scrollToBottom('chat'),
    interruptTask: (taskId, reason) => taskSessionControls.interruptTask(taskId, reason),
    applyTaskSessionPayload: sessionState.applyTaskSessionPayload,
    refreshActiveJobs: (taskId) => jobs.loadActive(taskId),
    loadTasks: (loadOptions) => loadTasks(loadOptions),
    patchTask: taskList.patchTask,
    removeTask: taskList.removeTask,
    clearCurrentTask: taskState.clearCurrent,
    router,
    resolveActionError,
  })

  const adminActions = useTaskAdminActions({
    getCurrentTask: () => taskState.currentTask.value,
    clearCurrentTask: taskState.clearCurrent,
    canDeleteTask: workspaceContext.canDeleteTask,
    canExportTask: workspaceContext.canExportTask,
    getWorkspaceId,
    loadTasks: (loadOptions) => loadTasks(loadOptions),
    submissionsClear: submissions.clear,
    clearConversationView,
    resetHistoryPaging: history.resetPaging,
    bumpHistoryGeneration: history.bumpGeneration,
    loadHistory: (taskId, reset) => history.loadHistory(taskId, reset),
    router,
    resolveActionError,
  })

  // ─── 会话编排：任务状态同步 / 切换 / 路由联动 ───

  /** 任务状态变更同时落到当前会话对象与列表条目。 */
  function syncTaskStatus(status: string) {
    const task = taskState.currentTask.value
    if (task) task.status = status
    const taskId = taskState.getTaskId()
    if (taskId) taskList.patchTask(taskId, { status })
  }

  function loadTasks(loadOptions?: { reset?: boolean; trySelectRouteTask?: boolean }) {
    return taskList.loadTasks({
      ...loadOptions,
      onLoaded: () => taskList.syncCurrentTaskFromList(taskState.currentTask.value, taskState.getTaskId()),
    })
  }

  /**
   * 选中路由参数指向的任务会话。ChatView 在 `/workspaces/:wsId/chat` 与
   * `/workspaces/:wsId/chat/:taskId` 之间导航时组件被复用不重挂载，浮窗
   * 「进入任务会话」、浏览器前进后退等仅变更 URL 的场景由路由监听调用这里。
   */
  async function selectRouteTask(selectOptions?: { allowFetch?: boolean }) {
    const routeTaskId = String(route.params.taskId || '')
    if (!routeTaskId) return
    if (taskState.getTaskId() === routeTaskId) return

    const matched = taskList.findTask(routeTaskId)
    if (matched) {
      await selectTask(matched)
      return
    }

    // 任务列表中暂无该任务时按需拉取（受 filters/loadTasks 场景约束）
    if (!selectOptions?.allowFetch) return
    try {
      const taskRes = await api.get(`/workspaces/${getWorkspaceId()}/tasks/${routeTaskId}`)
      const routeTask = taskRes.data
      if (!routeTask?.id) return
      // 准备中的任务不出现在任务列表（进度由全局浮窗跟踪），也不自动选中
      if (String(routeTask.status || '') === 'PROVISIONING') return
      taskList.unshiftTask(routeTask)
      if (taskState.getTaskId() !== String(routeTask.id)) {
        await selectTask(routeTask)
      }
    } catch (err) {
      console.warn('Failed to hydrate route task snapshot', err)
    }
  }

  async function selectTask(task: any) {
    if (!task) return
    // 切换会话即开启新的初始化代次：取消旧请求，旧快照不再写回新会话
    sessionState.beginTaskSwitch()
    engine.persistForTask(taskState.getTaskId())
    workbenchScroll.rememberScrollPosition()
    specDrawer.resetForTask(task)
    contextPanel.resetForTask()
    taskState.setCurrent(task)
    messages.reset()
    terminalLogs.clear()
    cards.clear()
    preinput.reset()
    resetConversationView()
    skills.resetForTask()
    startActions.resetInitializeState()
    specBootstrap.reset()
    engine.resetThinking()
    const restoredStatusCards = engine.restoreForTask(String(task.id))
    cards.setStatusCards(restoredStatusCards)
    resultsSummary.resetFromTask(task)

    const chatPath = `/workspaces/${getWorkspaceId()}/chat/${task.id}`
    if (route.path !== chatPath || String(route.params.taskId || '') !== String(task.id)) {
      router.push(chatPath)
    }
    // history / ai-jobs / pre-input 由统一入口在「首次订阅就绪」或「连接不可用兜底」
    // 时加载（单飞），避免 selectTask 与 WS onopen / resync 恢复各自重复拉取。
    if (taskState.isDiagnosisTask.value) {
      void diagnosis.loadDiagnosisResult()
    } else {
      diagnosis.resetForTask()
    }
    if (specDrawer.hasTaskSpecification(task)) {
      void specBootstrap.load(task.id, task)
    }
    if (route.query.source === 'spec-plan' && specDrawer.isSpecDrawerAvailable.value) {
      specDrawer.setTab('spec_doc')
      specDrawer.requestSpecDrawerLevel(specDrawer.lastOpenSpecDrawerLevel.value)
    }
    // 阅读进度：切任务先清空本地状态与待提交队列，再建立个人基线
    readingProgress.reset()
    resumeDismissedAtSeq.value = null
    readingUnreadSnapshot.value = null
    readingBannerClosed.value = false
    ws.connect(task.id)
    if (!route.query.messageId) void readingProgress.ensureSession(String(task.id))
  }

  async function openTaskSession(taskId: string) {
    const wsId = getWorkspaceId()
    router.push(`/workspaces/${wsId}/chat/${taskId}`)
    // 重新获取一下最新的 task 对象，并同步到任务列表，避免后续 loadTasks 用旧 PROVISIONING 覆盖当前状态
    try {
      const latestTaskRes = await api.get(`/workspaces/${wsId}/tasks/${taskId}`)
      const latestTask = latestTaskRes.data
      taskList.upsertTask(latestTask)
      await selectTask(latestTask)
    } catch (e) {
      console.warn('Failed to refresh task after provisioning', e)
    }
  }

  async function onTaskCreated(payload: string | { taskId: string; assetId?: string | null; jobId?: string; workspaceId?: string | null; expectSpecUpload?: boolean; expectDiagnosisDocs?: boolean }) {
    taskList.showTaskModal.value = false
    const taskId = typeof payload === 'string' ? payload : payload.taskId
    const jobId = typeof payload === 'string' ? '' : String(payload.jobId || '').trim()
    const workspaceId = typeof payload === 'string' ? '' : String(payload.workspaceId || '').trim()

    specDrawer.preferredSpecTaskId.value = taskId
    specDrawer.preferredSpecAssetId.value = typeof payload === 'string' ? '' : (payload.assetId || '')
    await loadTasks({ reset: true, trySelectRouteTask: false })

    if (jobId) {
      // 准备中的任务不进入会话也不出现在任务列表：进度由全局浮窗跟踪，
      // 就绪（PENDING）后任务才会出现在列表中，由用户主动进入。
      provisioningStore.startWatching({ jobId, taskId, workspaceId })
      return
    }
    void openTaskSession(taskId)
  }

  const provisioningStore = useProvisioningStore()

  // 准备浮窗终态变化（成功就绪/取消/失败）后刷新任务列表：任务此时才会出现（或已被回滚删除）
  watch(() => provisioningStore.taskListRefreshToken, () => {
    void loadTasks({ reset: true, trySelectRouteTask: false })
  })

  // ChatView 复用不重挂载：仅 URL 变化的任务会话切换（浮窗「进入任务会话」/浏览器前进后退）走这里
  watch(() => String(route.params.taskId || ''), (nextTaskId, prevTaskId) => {
    if (!nextTaskId || nextTaskId === prevTaskId) return
    void selectRouteTask({ allowFetch: true })
  })

  // ─── 预输入的 WS 发送通道（undoing 守卫 + 连接可用性提示） ───
  function sendPreInputAction(action: string, payload: Record<string, any> = {}): boolean {
    if (isUndoing.value) return false
    if (!ws.isOpen()) {
      ElMessage.error(t('preInput.errors.ws_unavailable'))
      return false
    }
    return ws.sendFrame(action, payload)
  }

  const presenters = createMessagePresenters({
    isCurrentUser: isMessageFromCurrentUser,
  })

  function isMessageFromCurrentUser(msg: any): boolean {
    const creatorId = String(msg?.creator_id || '').trim()
    const currentUserId = String(authStore.user?.id || '').trim()
    return Boolean(creatorId && currentUserId && creatorId === currentUserId)
  }

  const toggleTaskFollow = async (task: any) => {
    const nextFollowing = await taskList.toggleTaskFollow(task)
    if (nextFollowing !== undefined && taskState.getTaskId() === String(task?.id)) {
      taskState.patchCurrent({ is_following: nextFollowing })
    }
    return nextFollowing
  }

  // ─── Lifecycle ───
  const handleVisibilityRecovery = () => {
    if (document.visibilityState !== 'visible') return
    const taskId = taskState.getTaskId()
    if (!taskId) return
    // 回到页面时发现连接或恢复状态失效：仅异常路径（断开 + 仍有待处理回执）触发
    if (!ws.isHealthy(taskId) && submissions.busy.value) {
      void sessionState.recoverSession('visibility-unavailable')
    }
    // 前台恢复：一次校验快照（生命周期触发，非周期任务），并尽力 flush 待提交回执
    void readingProgress.refresh(taskId)
    void readingProgress.flushNow(taskId)
  }

  onMounted(() => {
    document.addEventListener('visibilitychange', handleVisibilityRecovery)
    restoreChatWorkbenchMode()
    if (authStore.token) void authStore.fetchCurrentUser()
    void loadTasks()
    void workspaceContext.loadWorkspace()
  })

  onUnmounted(() => {
    document.removeEventListener('visibilitychange', handleVisibilityRecovery)
    history.bumpGeneration()
    historyContext.reset()
    ws.closeForDispose()
    sessionState.dispose()
    skills.resetForTask()
    contextPanel.clearRefreshTimer()
    highlight.clear()
    diagnosis.clearTimer()
    readingProgress.reset()
  })

  return {
    // 路由与展示工具
    route,
    router,
    t,
    formatTime,
    formatToolInput,
    formatMessageTime,
    isMessageFromCurrentUser,
    isMessageWorkspaceExpert: presenters.isMessageWorkspaceExpert,
    messageAuthorLabel: presenters.messageAuthorLabel,
    messageAuthorColor,
    memberColorFor,
    memberColorRgba,

    // 任务列表与会话选择
    tasks: taskList.tasks,
    taskListContainer: taskList.taskListContainer,
    taskStatusFilter: taskList.taskStatusFilter,
    taskTypeFilter: taskList.taskTypeFilter,
    taskRelationFilter: taskList.taskRelationFilter,
    taskListHasMore: taskList.taskListHasMore,
    taskListLoading: taskList.taskListLoading,
    taskListLoadingMore: taskList.taskListLoadingMore,
    applyTaskStatusFilter: taskList.applyTaskStatusFilter,
    applyTaskTypeFilter: taskList.applyTaskTypeFilter,
    applyTaskRelationFilter: taskList.applyTaskRelationFilter,
    resetTaskRelationFilter: taskList.resetTaskRelationFilter,
    handleTaskListScroll: taskList.handleTaskListScroll,
    toggleTaskFollow,
    showTaskModal: taskList.showTaskModal,
    openNewTaskModal: taskList.openNewTaskModal,
    onTaskCreated,
    selectTask,

    // 工作区权限
    currentWorkspace: workspaceContext.currentWorkspace,
    canCreateTask: workspaceContext.canCreateTask,
    canManageTaskStatus: workspaceContext.canManageTaskStatus,
    canDeleteTask: workspaceContext.canDeleteTask,
    canExportTask: workspaceContext.canExportTask,
    canEditSuperpowersDocs: workspaceContext.canEditSuperpowersDocs,
    canShareTaskSession,

    // 当前会话
    currentTask: taskState.currentTask,
    isTaskPreStart: taskState.isTaskPreStart,
    isTaskProvisioning: taskState.isTaskProvisioning,
    isTerminalStatus: taskState.isTerminalStatus,
    isDiagnosisTask: taskState.isDiagnosisTask,
    hidePatchWorkflows: taskState.hidePatchWorkflows,
    isChatLocked,

    // 消息与历史
    messages: messages.visibleMessages,
    hasMore: history.hasMore,
    loadingMore: history.loadingMore,
    loadOlderMessages: history.loadOlderMessages,
    handleChatScroll: history.handleChatScroll,
    historyAnchored: historyContext.anchored,
    historyHasNew: historyContext.hasNew,
    historyContextLoading: historyContext.loading,
    historyHasAfter: computed(() => Boolean(historyContext.context.value?.has_after)),
    loadContextDirection: history.loadContextDirection,
    returnToLatest: history.returnToLatest,

    // 终端日志
    terminalLogs: terminalLogs.logs,

    // 置顶卡片
    activeHitlCards: cards.activeHitlCards,
    statusCards: cards.statusCards,
    submitHitl: send.submitHitl,

    // 引擎与运行面板
    engineRunning: computed(() => engine.engineRunning.value || submissions.busy.value),
    thinkingContent: engine.thinkingContent,
    showThinking: engine.showThinking,
    thinkingExpanded: engine.thinkingExpanded,
    resultsSummary: resultsSummary.state,
    activeChatJobs: jobs.activeChatJobs,

    // 发送
    chatInput: send.chatInput,
    sendingChat: send.sendingChat,
    chatInputPlaceholder: send.chatInputPlaceholder,
    sendChat: send.sendChat,
    sendChatContent: send.sendChatContent,
    sendVerification: send.sendVerification,

    // 撤销与决策
    undoingMessageId,
    isUndoing,
    canUndoMessage: messageActions.canUndoMessage,
    undoMessage: messageActions.undoMessage,
    canMarkMessageAsDecision: messageActions.canMarkMessageAsDecision,
    submitMessageDecision: messageActions.submitMessageDecision,
    chatDecisionSaving: chatDecision.saving,

    // 启动 / 初始化
    startPrompt: startActions.startPrompt,
    showStartConfirm: startActions.showStartConfirm,
    startingTask: startActions.startingTask,
    isStartActionVisible: startActions.isStartActionVisible,
    canClickStartAction: startActions.canClickStartAction,
    handleStartClick: startActions.handleStartClick,
    startTask: startActions.startTask,
    showInitReasonModal: startActions.showInitReasonModal,
    initPrompt: startActions.initPrompt,
    initReason: startActions.initReason,
    initSkillOptions: startActions.initSkillOptions,
    initSkillOptionsLoading: startActions.initSkillOptionsLoading,
    initSelectedSkillIds: startActions.initSelectedSkillIds,
    canInitializeAction: startActions.canInitializeAction,
    deletedRuntimeSkillNamesForInitialize: startActions.deletedRuntimeSkillNamesForInitialize,
    handleInitialize: startActions.handleInitialize,
    initializeTaskWithReason: startActions.initializeTaskWithReason,
    confirmInitialize: startActions.confirmInitialize,
    showDeletedRuntimeSkillConfirm: startActions.showDeletedRuntimeSkillConfirm,
    cancelDeletedRuntimeSkillConfirm: startActions.cancelDeletedRuntimeSkillConfirm,
    confirmInitializeWithDeletedRuntimeSkillDecision: startActions.confirmInitializeWithDeletedRuntimeSkillDecision,

    // 状态动作
    closeoutMode: statusActions.closeoutMode,
    canTemporarilyInterrupt: statusActions.canTemporarilyInterrupt,
    handleInterruptClick: statusActions.handleInterruptClick,
    handleCompleteClick: statusActions.handleCompleteClick,
    interruptCurrentRun: statusActions.interruptCurrentRun,
    // CLI 终端的 /complete 命令入口：打开 closeout 面板（保持异步契约）
    completeTaskNow: async () => statusActions.handleCompleteClick(),
    closeTaskCloseout: statusActions.closeTaskCloseout,
    handleTaskCloseoutSuccess: statusActions.handleTaskCloseoutSuccess,
    interruptingTask: taskSessionControls.interruptingTask,

    // 管理动作
    taskToDelete: adminActions.taskToDelete,
    showDeleteTaskConfirm: adminActions.showDeleteTaskConfirm,
    deletingTask: adminActions.deletingTask,
    handleDeleteTask: adminActions.handleDeleteTask,
    closeDeleteTaskConfirm: adminActions.closeDeleteTaskConfirm,
    confirmDeleteTask: adminActions.confirmDeleteTask,
    handleExport: adminActions.handleExport,
    clearTaskHistory: adminActions.clearTaskHistory,

    // 运行时技能
    showTaskSkillsDrawer: skills.showTaskSkillsDrawer,
    openTaskSkillsDrawer: skills.openTaskSkillsDrawer,
    closeTaskSkillsDrawer: skills.closeTaskSkillsDrawer,
    taskRuntimeSkillCount: skills.taskRuntimeSkillCount,
    taskRuntimeSkills: skills.taskRuntimeSkills,
    taskRuntimeSkillsLoading: skills.taskRuntimeSkillsLoading,
    runtimeActiveSkillId: skills.runtimeActiveSkillId,
    runtimeFileTree: skills.runtimeFileTree,
    runtimeFileTreeLoading: skills.runtimeFileTreeLoading,
    runtimeActiveFilePath: skills.runtimeActiveFilePath,
    runtimeActiveFileLoading: skills.runtimeActiveFileLoading,
    runtimeActiveFileSaving: skills.runtimeActiveFileSaving,
    runtimeActiveFileContent: skills.runtimeActiveFileContent,
    runtimeActiveFileBinary: skills.runtimeActiveFileBinary,
    runtimeActiveFileDirty: skills.runtimeActiveFileDirty,
    runtimeTraceEvents: skills.runtimeTraceEvents,
    runtimeTraceLoading: skills.runtimeTraceLoading,
    selectRuntimeSkill: skills.selectRuntimeSkill,
    selectRuntimeSkillFile: skills.selectRuntimeSkillFile,
    saveRuntimeSkillFileContent: skills.saveRuntimeSkillFileContent,
    updateRuntimeSkillFileContent: skills.updateRuntimeSkillFileContent,
    loadTaskRuntimeSkills: skills.loadTaskRuntimeSkills,
    loadTaskRuntimeTrace: skills.loadTaskRuntimeTrace,
    loadRuntimeSkillFileTree: skills.loadRuntimeSkillFileTree,
    canEditTaskRuntimeSkills,

    // Spec 抽屉与引导
    specDrawerLevel: specDrawer.specDrawerLevel,
    specDrawerTab: specDrawer.specDrawerTab,
    currentTaskHasSpec: specDrawer.currentTaskHasSpec,
    isPdfSpec: specDrawer.isPdfSpec,
    showSpecEntryButton: specDrawer.showSpecEntryButton,
    isSpecDrawerAvailable: specDrawer.isSpecDrawerAvailable,
    isSpecPanelOpen: specDrawer.isSpecPanelOpen,
    activeInitialSpecAssetId: specDrawer.activeInitialSpecAssetId,
    openSpecWorkspace,
    handleExpandDrawer: specDrawer.handleExpandDrawer,
    handleCollapseDrawer: specDrawer.handleCollapseDrawer,
    handleSpecEntryClick: specDrawer.handleSpecEntryClick,
    toggleDiagnosisDocsDrawer: specDrawer.toggleDiagnosisDocsDrawer,
    specBootstrap: specBootstrap.specBootstrap,
    specBootstrapLoading: specBootstrap.specBootstrapLoading,
    specBootstrapTriggering: specBootstrap.specBootstrapTriggering,
    isSpecBootstrapActive: specBootstrap.isSpecBootstrapActive,
    canTriggerSpecBootstrap: specBootstrap.canTriggerSpecBootstrap,
    bootstrapStatusText: specBootstrap.statusText,
    triggerSpecBootstrap: specBootstrap.trigger,
    registerShareSuggestionNudge,

    // 上下文窗口
    contextWindowDrawerOpen: contextPanel.drawerOpen,
    contextWindowDrawerLevel: contextPanel.drawerLevel,
    contextWindowData: contextPanel.contextWindow.data,
    contextWindowLoading: contextPanel.contextWindow.loading,
    contextWindowSegmentsLoading: contextPanel.contextWindow.segmentsLoading,
    contextWindowError: contextPanel.contextWindow.error,
    contextWindowSelectedCategory: contextPanel.contextWindow.selectedCategory,
    openContextWindowDrawer: contextPanel.openDrawer,
    closeContextWindowDrawer: contextPanel.closeDrawer,
    updateContextWindowDrawerLevel: contextPanel.updateDrawerLevel,
    selectContextWindowCategory: contextPanel.selectCategory,
    refreshContextWindow: contextPanel.refresh,
    locateContextWindowReference: contextPanel.locateReference,
    highlightedMessageId: highlight.highlightedMessageId,
    highlightedTerminalLogId: highlight.highlightedTerminalLogId,

    // 诊断
    diagnosisResult: diagnosis.diagnosisResult,
    diagnosisResultSaving: diagnosis.diagnosisResultSaving,
    diagnosisCaseCreating: diagnosis.diagnosisCaseCreating,
    diagnosisCaseLink: diagnosis.diagnosisCaseLink,
    diagnosisSummarizing: diagnosis.diagnosisSummarizing,
    diagnosisChatBusy: diagnosis.diagnosisChatBusy,
    diagnosisSummarizingLabel: diagnosis.diagnosisSummarizingLabel,
    isDiagnosisAdopted: diagnosis.isDiagnosisAdopted,
    saveDiagnosisResult: diagnosis.saveDiagnosisResult,
    createDiagnosisCase: diagnosis.createDiagnosisCase,
    generateDiagnosisSummary: diagnosis.generateDiagnosisSummary,
    exportDiagnosisResult: diagnosis.exportDiagnosisResult,

    // 协作预输入
    activePreInput: preinput.activePreInput,
    preInputIsCollecting: preinput.preInputIsCollecting,
    isPreInputCreator: preinput.isPreInputCreator,
    myPreInputParticipation: preinput.myPreInputParticipation,
    canEditPreInputShared: preinput.canEditPreInputShared,
    startPreInput: preinput.startPreInput,
    editPreInputDocument: preinput.editPreInputDocument,
    replacePreInputSpan: preinput.replacePreInputSpan,
    markPreInputDone: preinput.markPreInputDone,
    submitPreInputManually: preinput.submitPreInputManually,
    cancelPreInput: preinput.cancelPreInput,
    searchPreInputMembers: preinput.searchPreInputMembers,

    // 工作台
    chatWorkbenchMode,
    setChatWorkbenchMode,
    chatContainer,
    terminalContainer,
    setTerminalContainer,

    // 阅读进度与续读
    readingState: readingProgress.progress,
    readingSyncState: readingProgress.syncState,
    readingNotReady: readingProgress.readingNotReady,
    readingPendingCount: readingProgress.pendingCount,
    showResumeBanner,
    closeResumeBanner,
    readingUnreadSnapshot,
    resumeFromLastRead,
  }
}

export type ChatViewModel = ReturnType<typeof useChatViewModel>

/**
 * 经 proxyRefs 解包后的视图模型形态，是区块组件（components/chat/sections/*）
 * 的 `vm` prop 契约：模板内可直接读写 `vm.xxx`（ref 自动解包）。
 */
export type ChatViewVm = ShallowUnwrapRef<ChatViewModel>
