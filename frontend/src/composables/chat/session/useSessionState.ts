import api from '@/utils/api'
import { isOlderTaskStatusSequence } from '@/utils/taskStatusProjection'
import { wsBackoffDelay } from '@/utils/wsBackoff'
import { mapHistoryMessages } from '../shared/messageIdentity'
import { isCanceledRequest } from '../shared/requestGuards'
import type { useChatJobs } from '../jobs/useChatJobs'
import type { useChatMessages } from '../message/useChatMessages'
import type { ChatAiJob } from '../types'

/**
 * 会话状态协调：初始快照单飞、异常路径恢复（指数退避）、WS 恢复屏障、
 * 会话切换代次管理，以及 task session 载荷（status/generation/job）的应用。
 *
 * 快照顺序与恢复屏障一致：history 先落地，再以一个 session-state 请求补齐
 * 回执/活跃 job/关联消息与预输入。没有 WS 屏障的请求同样使用版本合并。
 */
export function useSessionState(options: {
  getWorkspaceId: () => string
  getCurrentTask: () => any
  submissions: {
    unconfirmedKeys: () => string[]
    current: () => any[]
    put: (receipt: any) => void
    send: (taskId: string, clientMessageId: string, content: string, metadata?: Record<string, any>, newAgentSession?: boolean) => Promise<boolean>
    clear: (taskId: string) => void
  }
  ingestJob: (job: ChatAiJob) => void
  jobs: Pick<ReturnType<typeof useChatJobs>, 'snapshotCursor' | 'mergeSnapshot'>
  onSnapshotJobAccepted: (job: ChatAiJob) => void
  syncEngineFromJobs: () => void
  convergeFromJobs: (taskId: string, items: ChatAiJob[]) => boolean
  syncConfirmationCards: () => void
  messages: Pick<ReturnType<typeof useChatMessages>, 'captureIdentitySnapshot' | 'mergeSessionSnapshot'>
  loadHistory: (taskId: string, reset?: boolean) => Promise<boolean>
  loadActivePreInput: (taskId: string) => Promise<boolean>
  onSessionGenerationBump: () => void
  applyTaskStatusSnapshot: (snapshot: any) => void
  reloadSpecBootstrap: (taskId: string) => void
  hasTaskSpecification: (task: any) => boolean
}) {
  const SESSION_STATE_FALLBACK_MS = 4000
  let sessionStateGeneration = 0
  let sessionStateFlightKey = ''
  let sessionStateFlight: Promise<boolean> | null = null
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

  const matchesCurrentVersion = (payload: any) => {
    const task = options.getCurrentTask()
    if (!task?.id || String(payload?.task_id || '') !== String(task.id)) return false
    if (payload.workspace_id != null && String(payload.workspace_id) !== options.getWorkspaceId()) return false
    if (payload.session_generation != null && Number(payload.session_generation) < Number(task.session_generation || 0)) return false
    if (payload.session_revision != null && Number(payload.session_revision) < Number(task.session_revision || 0)) return false
    return !isOlderTaskStatusSequence(payload.status_seq, task.status_seq)
  }

  const applySessionSnapshot = (snapshot: any, jobCursor: number, messagesAtRequest: Map<string, any>): boolean => {
    if (!matchesCurrentVersion(snapshot)) return false
    const taskId = String(snapshot.task_id)
    const merged = options.jobs.mergeSnapshot(snapshot.jobs || [], jobCursor, snapshot.session_generation)
    if (!merged) return false
    applyTaskSessionFields(snapshot)
    for (const receipt of snapshot.receipts || []) {
      options.submissions.put(receipt)
    }
    for (const job of merged.accepted) options.onSnapshotJobAccepted(job)
    options.convergeFromJobs(taskId, merged.items)
    options.messages.mergeSessionSnapshot(mapHistoryMessages(snapshot.messages || []), messagesAtRequest)
    options.syncConfirmationCards()
    return true
  }

  const recoverSession = (reason: string, recoverOptions?: { silent?: boolean }): Promise<boolean> => {
    const taskId = currentTaskId()
    if (!taskId) return Promise.resolve(false)
    if (recoverSessionFlight) return recoverSessionFlight
    clearRecoverSessionRetryTimer()
    const key = sessionStateKeyFor(taskId)
    const signal = getAbortSignal()
    const stillCurrent = () => !signal?.aborted && currentTaskId() === taskId && sessionStateKeyFor(taskId) === key
    const unconfirmed = options.submissions.unconfirmedKeys()
    const jobCursor = options.jobs.snapshotCursor()
    const messagesAtRequest = options.messages.captureIdentitySnapshot()
    const flight = (async (): Promise<boolean> => {
      try {
        const snapshot = await fetchSessionState(taskId, unconfirmed)
        if (!stillCurrent()) return false
        const applied = applySessionSnapshot(snapshot, jobCursor, messagesAtRequest)
        if (applied && unconfirmed.length) {
          const queried = new Set(unconfirmed)
          const present = new Set((snapshot.receipts || []).map((row: any) => row.client_message_id))
          for (const row of options.submissions.current()) {
            if (!stillCurrent() || !matchesCurrentVersion(snapshot)) break
            if (row.task_id !== taskId || row.status !== 'UNKNOWN'
              || !queried.has(row.client_message_id) || present.has(row.client_message_id)) continue
            // 只有本次确实查询过且服务端缺席的键，才按原幂等键重投。
            if (row.new_agent_session) {
              await options.submissions.send(taskId, row.client_message_id, row.content, row.metadata, true)
            } else {
              await options.submissions.send(taskId, row.client_message_id, row.content, row.metadata)
            }
          }
        }
        if (!stillCurrent()) return false
        if (!applied || options.submissions.current().some(row => row.status === 'UNKNOWN')) {
          recoverSessionAttempt += 1
          scheduleRecoverSessionRetry(reason)
        } else {
          recoverSessionAttempt = 0
        }
        return applied
      } catch (error) {
        if (!stillCurrent() || isCanceledRequest(error)) return false
        if (!recoverOptions?.silent) console.warn('Failed to recover session state', reason, error)
        // 指数退避 + 抖动重试；恢复正常（成功落地）即停止。
        recoverSessionAttempt += 1
        scheduleRecoverSessionRetry(reason)
        return false
      }
    })()
    recoverSessionFlight = flight
    void flight.finally(() => {
      if (recoverSessionFlight === flight) recoverSessionFlight = null
    })
    return flight
  }

  const loadSessionSnapshot = async (taskId: string): Promise<boolean> => {
    const key = sessionStateKeyFor(taskId)
    const historyLoaded = await options.loadHistory(taskId, true)
    if (currentTaskId() !== taskId || sessionStateKeyFor(taskId) !== key) return false
    const [stateLoaded, preInputLoaded] = await Promise.all([
      recoverSession('initial-snapshot', { silent: true }),
      options.loadActivePreInput(taskId),
    ])
    return historyLoaded && stateLoaded && preInputLoaded
  }

  /**
   * 首屏/恢复快照单飞：同一 workspace + task + 页面代次内合并 history/session-state/pre-input；
   * 进行中的请求合并复用，force 用于重连/序列缺口后的恢复刷新。
   */
  const loadSessionStateOnce = (taskId: string, loadOptions?: { force?: boolean }): Promise<boolean> => {
    if (!taskId || currentTaskId() !== taskId) return Promise.resolve(false)
    const key = sessionStateKeyFor(taskId)
    if (sessionStateFlight && sessionStateFlightKey === key) return sessionStateFlight
    if (!loadOptions?.force && sessionStateSettledKey === key) return Promise.resolve(true)
    const flight = loadSessionSnapshot(taskId)
      .then((succeeded) => {
        if (succeeded && sessionStateKeyFor(taskId) === key) sessionStateSettledKey = key
        return succeeded
      })
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
   * 屏障只确认在屏障内读取并成功应用的快照。
   */
  const restoreSessionState = async (taskId: string) => {
    const key = sessionStateKeyFor(taskId)
    const earlierLoad = sessionStateFlightKey === key ? sessionStateFlight : recoverSessionFlight
    if (earlierLoad) await earlierLoad
    if (sessionStateKeyFor(taskId) !== key || currentTaskId() !== taskId) return false
    if (!await loadSessionStateOnce(taskId, { force: true })) return false
    if (options.hasTaskSpecification(options.getCurrentTask())) {
      options.reloadSpecBootstrap(taskId)
    }
    return true
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

  /** 首次订阅就绪（resume_ok/resync_ok）后启动或复用首屏快照。 */
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
  const applyTaskSessionFields = (payload: any) => {
    const task = options.getCurrentTask()
    if (payload.session_revision != null) task.session_revision = Number(payload.session_revision)
    options.applyTaskStatusSnapshot(payload)
    if (payload?.session_id !== undefined) {
      task.session_id = payload.session_id
    }
    if (payload.session_generation != null) {
      if (Number(task.session_generation || 0) !== Number(payload.session_generation)) {
        options.onSessionGenerationBump()
        if (Number(task.session_generation) > 0) options.submissions.clear(String(task.id))
      }
      task.session_generation = Number(payload.session_generation || 0)
    }
    if (payload?.interrupt_reason !== undefined) {
      task.interrupt_reason = payload.interrupt_reason
    }
    if (payload?.interrupted_at !== undefined) {
      task.interrupted_at = payload.interrupted_at
    }
    if (payload?.submission?.task_id === String(task.id)) {
      options.submissions.put(payload.submission)
    }
  }

  const applyTaskSessionVersion = (payload: any) => {
    if (!matchesCurrentVersion(payload)) return false
    applyTaskSessionFields(payload)
    return true
  }

  const applyTaskSessionPayload = (payload: any) => {
    if (!applyTaskSessionVersion(payload)) return false
    const job = payload?.job as ChatAiJob | undefined
    if (job?.id) {
      options.ingestJob(job)
    } else {
      options.syncEngineFromJobs()
    }
    return true
  }

  const dispose = () => {
    sessionStateGeneration += 1
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
    applyTaskSessionVersion,
    applyTaskSessionPayload,
    dispose,
  }
}
