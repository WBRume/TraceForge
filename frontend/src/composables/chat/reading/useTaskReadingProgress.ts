import { ref } from 'vue'
import {
  acknowledgeReadingProgress,
  compactReadingProgress,
  fetchReadingProgress,
  openReadingSession,
  submitReadingReceipts,
} from '@/services/taskReadingApi'
import type {
  ReadingProgressChangedPayload,
  ReadingProgressState,
  ReadingReceiptItem,
  ReadingReceiptResume,
  ReadingReceiptsResponse,
  ReadingWindowSession,
  Seq,
  SyncState,
} from '@/types/taskReading'
import { seqEqual, seqGreaterThan, seqLessOrEqual, seqLessThan, seqMax } from '@/types/taskReading'

/** 回执提交节流：首条进入待提交队列后 2s 合并提交。 */
export const RECEIPT_THROTTLE_MS = 2000
/** 强制 flush 上限：待提交队列最老条目超过 5s 必须尝试提交。 */
export const RECEIPT_FORCE_FLUSH_MS = 5000
/** 单次回执请求条数上限（后端契约 ≤50）。 */
export const RECEIPT_BATCH_LIMIT = 50

/** 契约错误码：HTTP status + detail 字符串。409 有两种含义，靠 detail 区分。 */
export const READING_ERROR_CODES = {
  epochChanged: 'READING_EPOCH_CHANGED',
  historyNotReady: 'READING_HISTORY_NOT_READY',
  windowExpired: 'READING_WINDOW_EXPIRED',
  invalidReceipt: 'READING_INVALID_RECEIPT',
} as const

type AxiosLikeError = {
  response?: { status?: number; data?: { detail?: unknown } }
  code?: string
  name?: string
}

const errorStatus = (error: unknown): number =>
  (error as AxiosLikeError)?.response?.status ?? 0

const errorDetail = (error: unknown): string => {
  const detail = (error as AxiosLikeError)?.response?.data?.detail
  return typeof detail === 'string' ? detail : ''
}

const isCanceledError = (error: unknown): boolean => (
  (error as AxiosLikeError)?.code === 'ERR_CANCELED'
  || (error as AxiosLikeError)?.name === 'CanceledError'
)

const detailHas = (error: unknown, code: string): boolean => errorDetail(error).includes(code)

export interface UseTaskReadingProgressOptions {
  getWorkspaceId: () => string
  getTaskId: () => string
  isTaskActive: () => boolean
}

/**
 * 个人阅读进度状态管理核心：会话初始化、只读快照、回执批量提交（内存队列 +
 * 节流 + 单飞行）、窗口 ack/compact、增量窗口 token、WS 进度帧合并、
 * 断线降级（offline 保留队列，不建轮询定时器）。
 *
 * 序号比较一律走 @/types/taskReading 的 BigInt 工具。
 */
export function useTaskReadingProgress(options: UseTaskReadingProgressOptions) {
  const progress = ref<ReadingProgressState | null>(null)
  const syncState = ref<SyncState>('connected')
  const epochMismatch = ref(false)
  /** 409 READING_HISTORY_NOT_READY：会话历史尚未初始化完成。 */
  const readingNotReady = ref(false)
  /** 增量窗口 token（POST /reading-sessions 下发，供 reading-updates 使用）。 */
  const windowToken = ref<string | null>(null)
  /** 待提交回执条数（去重后的 item_key 数）。 */
  const pendingCount = ref(0)

  // ── 待提交队列（内存 Map：item_key → max change_seq） ──
  let pendingReceipts = new Map<string, Seq>()
  let pendingResume: ReadingReceiptResume | null = null
  /** CAS 失败过的续读位置：同 message_id+content_seq+expected_revision 不再重放。 */
  const failedResumeKeys = new Set<string>()
  let flushTimer: ReturnType<typeof setTimeout> | null = null
  let flushInFlight = false
  let oldestPendingAt = 0
  let drainWaiters: Array<() => void> = []

  // ── WS 帧合并：single-flight + 保存期间到达的更高目标版本补一次 ──
  let refreshInFlight = false
  let queuedRevision: Seq | null = null
  /** 连接就绪补取快照的并发去重。 */
  let snapshotPromise: Promise<void> | null = null

  const currentTaskId = (): string => options.getTaskId()
  const currentEpoch = (): Seq | null => progress.value?.reading_epoch ?? null

  const markConnected = () => {
    syncState.value = 'connected'
  }

  /**
   * 合并服务端状态：
   * - 同 epoch：个人版本与内容版本均不得回退；任一版本前进即可合并；
   * - epoch 变大：直接替换（旧 epoch 本地数据由上层在重 init 时清空）；
   * - epoch 变小：落后快照，忽略。
   */
  const mergeProgressState = (incoming: ReadingProgressState | null | undefined): boolean => {
    if (!incoming) return false
    const current = progress.value
    if (!current) {
      progress.value = incoming
      return true
    }
    if (incoming.task_id && current.task_id && incoming.task_id !== current.task_id) return false
    if (!seqEqual(incoming.reading_epoch, current.reading_epoch)) {
      if (seqLessThan(incoming.reading_epoch, current.reading_epoch)) return false
      progress.value = incoming
      epochMismatch.value = false
      return true
    }
    if (seqLessThan(incoming.state_revision, current.state_revision)
      || seqLessThan(incoming.latest_change_seq, current.latest_change_seq)) return false
    if (!seqGreaterThan(incoming.state_revision, current.state_revision)
      && !seqGreaterThan(incoming.latest_change_seq, current.latest_change_seq)) return false
    progress.value = incoming
    return true
  }

  const clearPending = () => {
    pendingReceipts = new Map()
    pendingResume = null
    oldestPendingAt = 0
    pendingCount.value = 0
    if (flushTimer) {
      clearTimeout(flushTimer)
      flushTimer = null
    }
  }

  const resolveDrainWaiters = () => {
    const waiters = drainWaiters
    drainWaiters = []
    waiters.forEach((resolve) => resolve())
  }

  /**
   * 请求失败统一分流：
   * - 409 READING_EPOCH_CHANGED → 丢弃旧回执、清本地状态并重新 init；
   * - 409 READING_HISTORY_NOT_READY → readingNotReady=true，队列保留；
   * - 410 → 窗口过期，token 作废（重新 open window 前不再增量读取）；
   * - 401/403/404 → 沿用 axios 拦截器行为，本地清空；
   * - 429/503/网络错误 → offline，保留待提交队列，由下一次事件/交互触发 flush。
   */
  const handleRequestError = (error: unknown, taskId: string) => {
    if (isCanceledError(error)) return
    const status = errorStatus(error)
    if (status === 409 && detailHas(error, READING_ERROR_CODES.epochChanged)) {
      clearPending()
      epochMismatch.value = true
      progress.value = null
      windowToken.value = null
      void ensureSession(taskId)
      return
    }
    if (status === 409 && detailHas(error, READING_ERROR_CODES.historyNotReady)) {
      readingNotReady.value = true
      syncState.value = 'stale'
      return
    }
    if (status === 410) {
      windowToken.value = null
      syncState.value = 'stale'
      return
    }
    if (status === 401 || status === 403 || status === 404) {
      reset()
      return
    }
    syncState.value = 'offline'
  }

  /** POST /reading-sessions（幂等）：初始化/迁移基线，同时拿到增量窗口 token。 */
  const ensureSession = async (taskId: string): Promise<ReadingProgressState | null> => {
    try {
      const session = await openReadingSession({ workspaceId: options.getWorkspaceId(), taskId })
      markConnected()
      readingNotReady.value = false
      epochMismatch.value = false
      windowToken.value = session.window_token
      mergeProgressState(session.state)
      if ((pendingReceipts.size || pendingResume) && options.isTaskActive()) {
        scheduleFlush(taskId)
      }
      return session.state
    } catch (error) {
      if (errorStatus(error) === 409 && detailHas(error, READING_ERROR_CODES.historyNotReady)) {
        readingNotReady.value = true
        syncState.value = 'stale'
        return null
      }
      handleRequestError(error, taskId)
      return null
    }
  }

  /** GET /reading-progress：只读快照（合并去重见 mergeProgressState）。 */
  const refresh = async (taskId: string, signal?: AbortSignal): Promise<ReadingProgressState | null> => {
    try {
      const state = await fetchReadingProgress({ workspaceId: options.getWorkspaceId(), taskId, signal })
      markConnected()
      mergeProgressState(state)
      return state
    } catch (error) {
      if (!isCanceledError(error)) handleRequestError(error, taskId)
      return null
    }
  }

  // ── 回执队列 ──

  const takeBatch = (): ReadingReceiptItem[] => {
    const batch: ReadingReceiptItem[] = []
    for (const [itemKey, changeSeq] of pendingReceipts) {
      if (batch.length >= RECEIPT_BATCH_LIMIT) break
      batch.push({ item_key: itemKey, change_seq: changeSeq })
      pendingReceipts.delete(itemKey)
    }
    return batch
  }

  const restoreBatch = (batch: ReadingReceiptItem[]) => {
    for (const item of batch) {
      const prev = pendingReceipts.get(item.item_key)
      pendingReceipts.set(item.item_key, prev ? seqMax(prev, item.change_seq) : item.change_seq)
    }
    pendingCount.value = pendingReceipts.size
  }

  const scheduleFlush = (taskId: string) => {
    if (flushInFlight || flushTimer) return
    const now = Date.now()
    if (oldestPendingAt && now - oldestPendingAt >= RECEIPT_FORCE_FLUSH_MS) {
      void flushNow(taskId)
      return
    }
    flushTimer = setTimeout(() => {
      flushTimer = null
      void flushNow(taskId)
    }, RECEIPT_THROTTLE_MS)
  }

  /** 立即尝试提交待队列（网络恢复后的下一次事件/交互可调用）。 */
  const flushNow = async (taskId: string): Promise<void> => {
    if (flushTimer) {
      clearTimeout(flushTimer)
      flushTimer = null
    }
    if (flushInFlight) return
    const epoch = currentEpoch()
    if (!epoch || (!pendingReceipts.size && !pendingResume) || !options.isTaskActive()) {
      resolveDrainWaiters()
      return
    }
    flushInFlight = true
    const batch = takeBatch()
    const resume = pendingResume
    // resume 取出后无论成败都不在本次会话重放旧位置：
    // 显式 resume_applied=false → 记入失败表；请求异常（未达服务端）→ 下一轮重试
    pendingResume = null
    oldestPendingAt = 0
    try {
      const res: ReadingReceiptsResponse = await submitReadingReceipts({
        workspaceId: options.getWorkspaceId(),
        taskId,
        readingEpoch: epoch,
        items: batch,
        resume,
      })
      markConnected()
      mergeProgressState(res.state)
      if (resume && !res.resume_applied) {
        // CAS 失败：服务端已前进，绝不重放旧位置
        failedResumeKeys.add(`${resume.message_id}:${resume.content_seq}:${resume.expected_revision}`)
      }
      if (res.compact_pending || res.state?.compact_pending) {
        void compact(taskId)
      }
    } catch (error) {
      restoreBatch(batch)
      if (resume) pendingResume = resume
      handleRequestError(error, taskId)
    } finally {
      flushInFlight = false
      pendingCount.value = pendingReceipts.size
      resolveDrainWaiters()
      if ((pendingReceipts.size || pendingResume) && options.isTaskActive()) {
        scheduleFlush(taskId)
      }
    }
  }

  /**
   * 提交阅读回执：先合并进内存待提交 map（同 item_key 取 max change_seq），
   * 2s 节流 + 最长 5s 强制 flush + 单次 ≤50 条；同一 task 同时最多一条在途请求。
   * 返回 promise：本轮队列尝试（成功/降级）结束后 resolve。
   */
  const submitReceipts = (
    taskId: string,
    items: ReadingReceiptItem[],
    resume?: ReadingReceiptResume | null,
  ): Promise<void> => {
    for (const item of items) {
      const prev = pendingReceipts.get(item.item_key)
      if (!prev || seqGreaterThan(item.change_seq, prev)) {
        pendingReceipts.set(item.item_key, item.change_seq)
      }
    }
    if (resume) {
      const resumeKey = `${resume.message_id}:${resume.content_seq}:${resume.expected_revision}`
      if (!failedResumeKeys.has(resumeKey)) {
        pendingResume = resume
      }
    }
    pendingCount.value = pendingReceipts.size
    if (!pendingReceipts.size && !pendingResume) return Promise.resolve()
    if (!currentEpoch()) {
      // 尚未 init（无 epoch）：入队但不排程，等 ensureSession 成功后补一次 flush
      return Promise.resolve()
    }
    if (!oldestPendingAt) oldestPendingAt = Date.now()
    scheduleFlush(taskId)
    return new Promise<void>((resolve) => {
      drainWaiters.push(resolve)
    })
  }

  /** 把截至窗口上沿的全部更新标为已读（scope=all-through-window）。 */
  const acknowledgeAll = async (taskId: string, token?: string): Promise<ReadingProgressState | null> => {
    const epoch = currentEpoch()
    const tokenToUse = token ?? windowToken.value
    if (!epoch || !tokenToUse) return null
    try {
      const res = await acknowledgeReadingProgress({
        workspaceId: options.getWorkspaceId(),
        taskId,
        readingEpoch: epoch,
        windowToken: tokenToUse,
      })
      markConnected()
      mergeProgressState(res.state)
      return res.state
    } catch (error) {
      handleRequestError(error, taskId)
      return null
    }
  }

  /** 推进压缩水位：仅 compact_pending 时真正发请求。 */
  const compact = async (taskId: string): Promise<ReadingProgressState | null> => {
    const epoch = currentEpoch()
    if (!epoch || !progress.value?.compact_pending) return null
    try {
      const res = await compactReadingProgress({
        workspaceId: options.getWorkspaceId(),
        taskId,
        readingEpoch: epoch,
      })
      markConnected()
      mergeProgressState(res.state)
      return res.state
    } catch (error) {
      handleRequestError(error, taskId)
      return null
    }
  }

  /** 打开/刷新增量窗口：POST reading-sessions，缓存 window_token 供 updates 使用。 */
  const openUpdatesWindow = async (taskId: string): Promise<ReadingWindowSession | null> => {
    try {
      const session = await openReadingSession({ workspaceId: options.getWorkspaceId(), taskId })
      markConnected()
      windowToken.value = session.window_token
      mergeProgressState(session.state)
      return session
    } catch (error) {
      handleRequestError(error, taskId)
      return null
    }
  }

  /** WS revision 帧合并：single-flight；在途期间到达的更高目标版本，响应后补一次。 */
  const scheduleRevisionRefresh = (targetRevision: Seq) => {
    if (refreshInFlight) {
      if (!queuedRevision || seqGreaterThan(targetRevision, queuedRevision)) {
        queuedRevision = targetRevision
      }
      return
    }
    refreshInFlight = true
    void (async () => {
      try {
        await refresh(currentTaskId())
      } finally {
        refreshInFlight = false
        const queued = queuedRevision
        queuedRevision = null
        const current = progress.value
        if (queued && (!current || seqGreaterThan(queued, current.state_revision))) {
          scheduleRevisionRefresh(queued)
        }
      }
    })()
  }

  /**
   * WS 控制帧 reading_progress_changed：
   * - 落后 epoch 帧（< 当前）忽略；
   * - epoch 前进 → 清空本地状态（含待提交回执）重新 ensureSession；
   * - 同 epoch 且 state_revision 更大 → single-flight refresh。
   */
  const handleWsFrame = (payload: ReadingProgressChangedPayload) => {
    if (!payload || typeof payload !== 'object') return
    const taskId = currentTaskId()
    if (payload.task_id && taskId && payload.task_id !== taskId) return
    const current = progress.value
    if (!current) {
      void refresh(taskId || payload.task_id)
      return
    }
    if (!seqEqual(payload.reading_epoch, current.reading_epoch)) {
      if (seqLessOrEqual(payload.reading_epoch, current.reading_epoch)) return
      clearPending()
      windowToken.value = null
      progress.value = null
      void ensureSession(taskId)
      return
    }
    if (!seqGreaterThan(payload.state_revision, current.state_revision)) return
    scheduleRevisionRefresh(payload.state_revision)
  }

  /** resume_ok / resync_ok 后补取一次快照（并发去重：在途快照直接复用）。 */
  const onConnectionReady = (taskId: string): Promise<void> => {
    if (snapshotPromise) return snapshotPromise
    const run = async () => {
      await refresh(taskId)
    }
    const promise = run().finally(() => {
      snapshotPromise = null
    })
    snapshotPromise = promise
    return promise
  }

  /** 切任务清理：清空全部本地状态与待提交队列（不 resolve 在途请求）。 */
  const reset = () => {
    clearPending()
    failedResumeKeys.clear()
    progress.value = null
    windowToken.value = null
    epochMismatch.value = false
    readingNotReady.value = false
    syncState.value = 'connected'
    refreshInFlight = false
    queuedRevision = null
    snapshotPromise = null
    resolveDrainWaiters()
  }

  return {
    progress,
    syncState,
    epochMismatch,
    readingNotReady,
    windowToken,
    pendingCount,
    ensureSession,
    refresh,
    submitReceipts,
    flushNow,
    acknowledgeAll,
    compact,
    openUpdatesWindow,
    handleWsFrame,
    onConnectionReady,
    reset,
  }
}

export type UseTaskReadingProgressReturn = ReturnType<typeof useTaskReadingProgress>
