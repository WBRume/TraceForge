/**
 * 团队会话阅读进度与增量阅读 — 轻量 API 封装。
 *
 * 仅做参数拼装与 res.data 解包（每函数直接返回 data），不含业务重试；
 * 错误处理（409 READING_EPOCH_CHANGED / 409 READING_HISTORY_NOT_READY /
 * 410 READING_WINDOW_EXPIRED / 422 / 429 / 503 等）由调用方
 * （composables/chat/reading/*）根据 error.response?.status 与 detail 完成。
 * HTTP 401/403/404 沿用 axios 拦截器行为。
 */
import api from '@/utils/api'
import type {
  ReadingAckResponse,
  ReadingCompactResponse,
  ReadingItemsResponse,
  ReadingProgressState,
  ReadingReceiptItem,
  ReadingReceiptResume,
  ReadingReceiptsResponse,
  ReadingResumeResponse,
  ReadingUpdatesFilter,
  ReadingUpdatesResponse,
  ReadingWindowSession,
  Seq,
} from '@/types/taskReading'

export type ReadingApiRequestOptions = {
  signal?: AbortSignal
}

const taskBase = (workspaceId: string, taskId: string): string =>
  `/workspaces/${workspaceId}/tasks/${taskId}`

/** POST /reading-sessions：首次基线/清空懒迁移 + 打开增量窗口（重复调用幂等）。 */
export const openReadingSession = async (params: {
  workspaceId: string
  taskId: string
} & ReadingApiRequestOptions): Promise<ReadingWindowSession> => {
  const res = await api.post<ReadingWindowSession>(
    `${taskBase(params.workspaceId, params.taskId)}/reading-sessions`,
    {},
    { signal: params.signal },
  )
  return res.data
}

/** GET /reading-progress：只读快照（无记录时 initialized=false）。 */
export const fetchReadingProgress = async (params: {
  workspaceId: string
  taskId: string
} & ReadingApiRequestOptions): Promise<ReadingProgressState> => {
  const res = await api.get<ReadingProgressState>(
    `${taskBase(params.workspaceId, params.taskId)}/reading-progress`,
    { signal: params.signal },
  )
  return res.data
}

/** POST /reading-receipts：批量提交阅读回执（可携带 CAS 续读位置）。 */
export const submitReadingReceipts = async (params: {
  workspaceId: string
  taskId: string
  readingEpoch: Seq
  items: ReadingReceiptItem[]
  resume?: ReadingReceiptResume | null
} & ReadingApiRequestOptions): Promise<ReadingReceiptsResponse> => {
  const body: Record<string, unknown> = {
    reading_epoch: params.readingEpoch,
    items: params.items,
  }
  if (params.resume) {
    body.resume = params.resume
  }
  const res = await api.post<ReadingReceiptsResponse>(
    `${taskBase(params.workspaceId, params.taskId)}/reading-receipts`,
    body,
    { signal: params.signal },
  )
  return res.data
}

/** POST /reading-progress/compact：推进压缩水位（仅 compact_pending 时调用）。 */
export const compactReadingProgress = async (params: {
  workspaceId: string
  taskId: string
  readingEpoch: Seq
} & ReadingApiRequestOptions): Promise<ReadingCompactResponse> => {
  const res = await api.post<ReadingCompactResponse>(
    `${taskBase(params.workspaceId, params.taskId)}/reading-progress/compact`,
    { reading_epoch: params.readingEpoch },
    { signal: params.signal },
  )
  return res.data
}

/** POST /reading-progress/acknowledgements：把截至窗口上沿的全部更新标为已读。 */
export const acknowledgeReadingProgress = async (params: {
  workspaceId: string
  taskId: string
  readingEpoch: Seq
  windowToken: string
  scope?: 'all-through-window'
} & ReadingApiRequestOptions): Promise<ReadingAckResponse> => {
  const res = await api.post<ReadingAckResponse>(
    `${taskBase(params.workspaceId, params.taskId)}/reading-progress/acknowledgements`,
    {
      reading_epoch: params.readingEpoch,
      window_token: params.windowToken,
      scope: params.scope ?? 'all-through-window',
    },
    { signal: params.signal },
  )
  return res.data
}

/** GET /reading-items：按 message_id 反查阅读项（≤50 个，重复键查询串）。 */
export const fetchReadingItems = async (params: {
  workspaceId: string
  taskId: string
  messageIds: string[]
} & ReadingApiRequestOptions): Promise<ReadingItemsResponse> => {
  if (!params.messageIds.length) {
    return { items: [] }
  }
  // axios 默认把数组序列化成 message_id[]=a，后端契约要求重复键形式，手动拼装
  const query = params.messageIds.map((id) => `message_id=${encodeURIComponent(id)}`).join('&')
  const res = await api.get<ReadingItemsResponse>(
    `${taskBase(params.workspaceId, params.taskId)}/reading-items?${query}`,
    { signal: params.signal },
  )
  return res.data
}

/** GET /reading-updates：拉取增量窗口内的更新（filter/cursor/limit）。 */
export const fetchReadingUpdates = async (params: {
  workspaceId: string
  taskId: string
  windowToken: string
  filter?: ReadingUpdatesFilter
  memberId?: string | null
  limit?: number
  cursor?: string | null
} & ReadingApiRequestOptions): Promise<ReadingUpdatesResponse> => {
  const query: string[] = [`window_token=${encodeURIComponent(params.windowToken)}`]
  if (params.filter) {
    query.push(`filter=${encodeURIComponent(params.filter)}`)
  }
  if (params.filter === 'member' && params.memberId) {
    query.push(`member_id=${encodeURIComponent(params.memberId)}`)
  }
  if (params.limit != null) {
    query.push(`limit=${params.limit}`)
  }
  if (params.cursor) {
    query.push(`cursor=${encodeURIComponent(params.cursor)}`)
  }
  const res = await api.get<ReadingUpdatesResponse>(
    `${taskBase(params.workspaceId, params.taskId)}/reading-updates?${query.join('&')}`,
    { signal: params.signal },
  )
  return res.data
}

/** GET /reading-resume：续读锚点状态 + 上下文消息。 */
export const fetchReadingResume = async (params: {
  workspaceId: string
  taskId: string
} & ReadingApiRequestOptions): Promise<ReadingResumeResponse> => {
  const res = await api.get<ReadingResumeResponse>(
    `${taskBase(params.workspaceId, params.taskId)}/reading-resume`,
    { signal: params.signal },
  )
  return res.data
}
