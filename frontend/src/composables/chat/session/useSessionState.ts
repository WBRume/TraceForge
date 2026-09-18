import api from '@/utils/api'
import { wsBackoffDelay } from '@/utils/wsBackoff'
import { mapHistoryMessages } from '../shared/messageIdentity'
import { isCanceledRequest } from '../shared/requestGuards'
import type { ChatAiJob } from '../types'

/**
 * 会话状态协调：初始快照单飞、异常路径恢复（指数退避）、WS 恢复屏障、
 * 会话切换代次管理，以及 task session 载荷（status/generation/job）的应用。
 *
 * 快照顺序与恢复屏障一致：history 先落地，再以一个 session-state 请求补齐
 * 回执/活跃 job/关联消息与预输入——屏障期间事件被服务端暂存，快照完成后
 * 才放行，故增量不会被子集覆盖。
 */
export function useSessionState(options: {
  getWorkspaceId: () => string
  getCurrentTask: () => any
  submissions: {
    unconfirmedKeys: () => string[]
    current: () => any[]
    put: (receipt: any) => void
    send: (taskId: string, clientMessageId: string, content: string, metadata?: Record<string, any>) => Promise<boolean>
    clear: (taskId: string) => void
  }
  ingestJob: (job: ChatAiJob) => void
  syncEngineFromJobs: () => void
  convergeFromJobs: (taskId: string, items: ChatAiJob[]) => boolean
  syncConfirmationCards: () => void
  upsertMessage: (message: any) => void
  loadHistory: (taskId: string, reset?: boolean) => Promise<void>
  loadActivePreInput: (taskId: string) => Promise<boolean>
  onSessionGenerationBump: () => void
  syncTaskStatus: (status: string) => void
  reloadSpecBootstrap: (taskId: string) => void
  hasTaskSpecification: (task: any) => boolean
}) {
  const SESSION_STATE_FALLBACK_MS = 4000
  let sessionStateGeneration = 0
  let sessionStateFlightKey = ''
  let sessionStateFlight: Promise<void> | null = null
  let sessionStateSettledKey = ''
  let sessionStateFallbackTimer: number | null = null
  let sessionStateAbort: AbortController | null = null

  // 任务级恢复协调器：仅异常路径（首屏、WS 恢复、发送 UNKNOWN、断线后仍有
  // 待处理回执、回到页面发现连接失效）触发；单请求串行、指数退避，事件驱动
  // 的正常更新不经过这里。未确认回执按幂等键精确查询，网络超时绝不视为未接收。
  let recoverSessionFlight: Promise<boolean> | null = null
  let recoverSessionAttempt = 0
  let recoverSessionRetryTimer: number | null = null

  const currentTaskId = () => String(options.getCurrentTask()?.id || '')

  const sessionStateKeyFor = (taskId: string) => (
    `${options.getWorkspaceId()}:${taskId}:${sessionStateGeneration}`
  )

  const getAbortSignal = () => sessionStateAbort?.signal

  /** 会话切换：递增代次使在途快照全部失效，旧任务请求中止。 */
  const beginTaskSwitch = () => {
    sessionStateGeneration += 1
    sessionStateAbort?.abort()
    sessionStateAbort = new AbortController()
    clearSessionStateFallbackTimer()
    clearRecoverSessionRetryTimer()
    // 会话切换：旧任务的恢复请求已被 abort，新的 session-state 快照不再复用旧 flight
    recoverSessionFlight = null
    recoverSessionAttempt = 0
  }

  const clearRecoverSessionRetryTimer = () => {
    if (recoverSessionRetryTimer !== null) {
      window.clearTimeout(recoverSessionRetryTimer)
      recoverSessionRetryTimer = null
    }
  }

  const clearSessionStateFallbackTimer = () => {
    if (sessionStateFallbackTimer !== null) {
      window.clearTimeout(sessionStateFallbackTimer)
      sessionStateFallbackTimer = null
    }
  }

  const scheduleRecoverSessionRetry = (reason: string) => {
    if (recoverSessionRetryTimer !== null) return
    const delay = wsBackoffDelay(recoverSessionAttempt)
    recoverSessionRetryTimer = window.setTimeout(() => {
      recoverSessionRetryTimer = null
      void recoverSession(reason)
    }, delay)
  }

  const fetchSessionState = async (taskId: string, unconfirmed: string[]) => {
    const params: Record<string, string> = {}
    if (unconfirmed.length) params.client_message_ids = unconfirmed.join(',')
    const res = await api.get(`/workspaces/${options.getWorkspaceId()}/tasks/${taskId}/session-state`, {
      params, signal: sessionStateAbort?.signal,
    })
    return res.data
  }

  const applySessionSnapshot = (snapshot: any): boolean => {
    const taskId = String(snapshot?.task_id || '')
    if (currentTaskId() !== taskId) return false
    if (Number(snapshot?.session_generation || 0) < Number(options.getCurrentTask()?.session_generation || 0)) return false
    let changed = false
    for (const receipt of (snapshot?.receipts || []) as any[]) {
      options.submissions.put(receipt)
      changed = true
    }
    const jobs = (snapshot?.jobs || []) as ChatAiJob[]
    for (const job of jobs) {
      options.ingestJob(job)
      changed = true
    }
    options.convergeFromJobs(taskId, jobs)
    for (const message of (snapshot?.messages || []) as any[]) {
      options.upsertMessage(mapHistoryMessages([message])[0])
      changed = true
    }
    if (jobs.length) options.syncConfirmationCards()
    return changed
  }

  const resolveUnknownReceipts = async (snapshot: any): Promise<void> => {
    const taskId = String(snapshot?.task_id || '')
    if (currentTaskId() !== taskId) return
    const present = new Set((snapshot?.receipts || []).map((row: any) => String(row.client_message_id)))
    for (const row of options.submissions.current?.() || []) {
      if (row.task_id !== taskId || row.status !== 'UNKNOWN' || present.has(row.client_message_id)) continue
      // The server has no record of this key; re-submit with the original
      // idempotency key — a lost response is never treated as "not received".
      await options.submissions.send(taskId, row.client_message_id, row.content, row.metadata)
    }
  }

  const recoverSession = (reason: string, recoverOptions?: { silent?: boolean }): Promise<boolean> => {
    const taskId = currentTaskId()
    if (!taskId) return Promise.resolve(false)
    if (recoverSessionFlight) return recoverSessionFlight
    clearRecoverSessionRetryTimer()
    const workspace = options.getWorkspaceId()
    const unconfirmed = options.submissions.unconfirmedKeys()
    const flight = (async (): Promise<boolean> => {
      try {
        const snapshot = await fetchSessionState(taskId, unconfirmed)
        if (options.getWorkspaceId() !== workspace || currentTaskId() !== taskId) return false
        applySessionSnapshot(snapshot)
        await resolveUnknownReceipts(snapshot)
        recoverSessionAttempt = 0
        return true
      } catch (error) {
        if (isCanceledRequest(error)) return false
        if (!recoverOptions?.silent) console.warn('Failed to recover session state', reason, error)
        // 指数退避 + 抖动重试；恢复正常（成功落地）即停止。
        recoverSessionAttempt += 1
        scheduleRecoverSessionRetry(reason)
        return false
      } finally {
        recoverSessionFlight = null
      }
    })()
    recoverSessionFlight = flight
    return flight
  }

  const loadSessionSnapshot = async (taskId: string): Promise<boolean> => {
    await options.loadHistory(taskId, true)
    const [stateLoaded, preInputLoaded] = await Promise.all([
      recoverSession('initial-snapshot', { silent: true }),
      options.loadActivePreInput(taskId),
    ])
    return stateLoaded && preInputLoaded
  }

  /**
   * 首屏/恢复快照单飞：同一 workspace + task + 连接代次内只发一组 history/ai-jobs/pre-input；
   * 进行中的请求合并复用，force 用于重连/序列缺口后的恢复刷新。
   */
  const loadSessionStateOnce = (taskId: string, loadOptions?: { force?: boolean }): Promise<void> => {
    if (!taskId) return Promise.resolve()
    const key = sessionStateKeyFor(taskId)
    if (sessionStateFlight && sessionStateFlightKey === key) return sessionStateFlight
    if (!loadOptions?.force && sessionStateSettledKey === key) return Promise.resolve()
    const flight = loadSessionSnapshot(taskId)
      .then((succeeded) => {
        if (succeeded && sessionStateKeyFor(taskId) === key) sessionStateSettledKey = key
      })
      .then(() => undefined)
    sessionStateFlight = flight
    sessionStateFlightKey = key
    void flight.finally(() => {
      if (sessionStateFlight === flight) {
        sessionStateFlight = null
        sessionStateFlightKey = ''
      }
    })
    return flight
  }

  /**
   * 重连/序列缺口的既有恢复协议：恢复屏障期间重建统一快照，
   * 完成后才由调用方发送 resync_complete，保证 WS 增量晚于快照落地。
   */
  const restoreSessionState = async (taskId: string) => {
    await loadSessionStateOnce(taskId, { force: true })
    if (options.hasTaskSpecification(options.getCurrentTask())) {
      options.reloadSpecBootstrap(taskId)
    }
  }

  const armSessionStateFallback = (taskId: string) => {
    clearSessionStateFallbackTimer()
    const key = sessionStateKeyFor(taskId)
    sessionStateFallbackTimer = window.setTimeout(() => {
      sessionStateFallbackTimer = null
      if (sessionStateKeyFor(taskId) !== key || currentTaskId() !== taskId) return
      void loadSessionStateOnce(taskId)
    }, SESSION_STATE_FALLBACK_MS)
  }

  /** 首次订阅就绪（resume_ok/resync_ok）：replay/屏障已完成，快照不会覆盖 WS 增量 */
  const onInitialSubscriptionReady = (taskId: string, wasReady: boolean) => {
    clearSessionStateFallbackTimer()
    // 若兜底快照早于首次就绪落地，就绪后再对齐一次，确保快照不早于 replay 增量
    const force = !wasReady && sessionStateSettledKey === sessionStateKeyFor(taskId)
    void loadSessionStateOnce(taskId, { force })
  }

  /** 首次连接不可用（未就绪即断开）：HTTP 兜底，重连后仍走恢复协议刷新 */
  const onInitialConnectionUnavailable = (taskId: string) => {
    clearSessionStateFallbackTimer()
    void loadSessionStateOnce(taskId)
  }

  /**
   * task session 载荷（interrupt/resume/start 等响应与 WS 事件）应用：
   * 状态、会话代次（代次变化时清空回执）、中断信息与携带的 job。
   */
  const applyTaskSessionPayload = (payload: any) => {
    const task = options.getCurrentTask()
    if (!task?.id) return
    if (String(payload?.task_id || '') !== String(task.id)) return
    const status = String(payload?.status || '').trim()
    if (status) {
      options.syncTaskStatus(status)
    }
    if (payload?.session_id !== undefined) {
      task.session_id = payload.session_id
    }
    if (payload?.session_generation !== undefined) {
      if (Number(task.session_generation) !== Number(payload.session_generation)) {
        options.onSessionGenerationBump()
        options.submissions.clear(String(task.id))
      }
      task.session_generation = Number(payload.session_generation || 0)
    }
    if (payload?.interrupt_reason !== undefined) {
      task.interrupt_reason = payload.interrupt_reason
    }
    if (payload?.interrupted_at !== undefined) {
      task.interrupted_at = payload.interrupted_at
    }
    const job = payload?.job as ChatAiJob | undefined
    if (job?.id) {
      options.ingestJob(job)
    } else {
      options.syncEngineFromJobs()
    }
  }

  const dispose = () => {
    clearSessionStateFallbackTimer()
    clearRecoverSessionRetryTimer()
    sessionStateAbort?.abort()
    sessionStateAbort = null
  }

  return {
    getAbortSignal,
    beginTaskSwitch,
    loadSessionStateOnce,
    restoreSessionState,
    armSessionStateFallback,
    onInitialSubscriptionReady,
    onInitialConnectionUnavailable,
    recoverSession,
    applyTaskSessionPayload,
    dispose,
  }
}
