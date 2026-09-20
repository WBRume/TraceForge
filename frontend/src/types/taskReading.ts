/**
 * 团队会话阅读进度与增量阅读 — DTO 类型与序号工具。
 *
 * 后端所有序号（change_seq / revision / epoch / frontier 等）都以十进制字符串
 * 传输，可能超过 Number.MAX_SAFE_INTEGER（2^53）。前端一律以字符串持有，
 * 比较必须走本文件的 BigInt 工具，禁止 Number() 转换后比较。
 */

/** 十进制字符串序号（可能超过 2^53，比较必须用 compareSeq）。 */
export type Seq = string

/** BigInt 比较：a<b → -1，a===b → 0，a>b → 1。非十进制数字串输入会直接抛错。 */
export const compareSeq = (a: Seq, b: Seq): number => {
  const av = BigInt(a)
  const bv = BigInt(b)
  if (av < bv) return -1
  if (av > bv) return 1
  return 0
}

export const seqGreaterThan = (a: Seq, b: Seq): boolean => compareSeq(a, b) > 0

export const seqGreaterOrEqual = (a: Seq, b: Seq): boolean => compareSeq(a, b) >= 0

export const seqLessThan = (a: Seq, b: Seq): boolean => compareSeq(a, b) < 0

export const seqLessOrEqual = (a: Seq, b: Seq): boolean => compareSeq(a, b) <= 0

export const seqEqual = (a: Seq, b: Seq): boolean => compareSeq(a, b) === 0

export const seqMax = (a: Seq, b: Seq): Seq => (seqGreaterThan(a, b) ? a : b)

export type UnreadCountRelation = 'eq' | 'gte'

export type UnreadCount = {
  value: Seq
  relation: UnreadCountRelation
}

/** state.resume 锚点：续读位置（阅读进度 state 内嵌）。 */
export type ReadingResumeAnchor = {
  message_id: string
  order_key?: string
  content_seq: Seq
  offset_ratio?: number | null
  revision?: Seq
  updated_at?: string | null
}

/** 个人阅读进度状态（GET /reading-progress 与各写接口返回的 state）。 */
export type ReadingProgressState = {
  initialized: boolean
  task_id: string
  reading_epoch: Seq
  baseline_seq: Seq
  read_frontier_seq: Seq
  latest_change_seq: Seq
  state_revision: Seq
  has_unread: boolean
  unread_count: UnreadCount
  compact_pending: boolean
  resume?: ReadingResumeAnchor | null
  reading_ready?: boolean
}

/** GET /reading-resume 返回的锚点（含保存时的序号快照）。 */
export type ReadingResumeAnchorStatus = {
  message_id: string
  content_seq: Seq
  saved_content_seq: Seq
  offset_ratio?: number | null
}

export type ReadingAnchorStatus = 'ok' | 'updated' | 'retracted' | 'missing' | 'empty' | 'none'

/** 前端同步通道状态：connected 正常 / offline 网络或服务不可用 / stale 数据过期需重开窗口。 */
export type SyncState = 'connected' | 'offline' | 'stale'

/** 历史消息 DTO（reading-updates / reading-resume 内嵌的消息体，字段保持宽松）。 */
export type ReadingHistoryMessage = {
  message_id: string
  role: string
  content: string
  message_type?: string
  author_name?: string | null
  display_name?: string | null
  created_at?: string | null
  session_generation?: number | string | null
  session_turn_id?: string | null
  [key: string]: unknown
}

export type ReadingItemKind = 'message' | 'messages_retracted' | 'history_cleared'

/** 边界通知（撤销/清空历史）。 */
export type ReadingBoundaryNotice = {
  operation_id: string
  affected_count: number
  boundary_before_id: string | null
  boundary_after_id: string | null
}

/** GET /reading-updates 列表项。 */
export type ReadingUpdateItem = {
  item_key: string
  change_seq: Seq
  kind: ReadingItemKind
  read: boolean
  group_key: string | null
  session_generation?: number | string | null
  session_turn_id?: string | null
  changed_at?: string | null
  message?: ReadingHistoryMessage | null
  notice?: ReadingBoundaryNotice | null
}

export type ReadingUpdatesFilter = 'all' | 'other-members' | 'member'

export type ReadingUpdatesWindow = {
  lower_seq: Seq
  upper_seq: Seq
  reading_epoch: Seq
}

export type ReadingUpdatesResponse = {
  items: ReadingUpdateItem[]
  next_cursor: string | null
  has_more: boolean
  has_newer_updates: boolean
  window: ReadingUpdatesWindow
}

/** 回执条目：item_key + 观察到的 change_seq。 */
export type ReadingReceiptItem = {
  item_key: string
  change_seq: Seq
}

/** CAS 续读提交：expected_revision 不匹配时服务端返回 resume_applied=false。 */
export type ReadingReceiptResume = {
  message_id: string
  content_seq: Seq
  offset_ratio?: number | null
  expected_revision: Seq
}

export type ReadingSkippedItemReason = 'removed' | 'version_changed'

export type ReadingSkippedItem = {
  item_key: string
  reason: ReadingSkippedItemReason
}

export type ReadingReceiptsResponse = {
  state: ReadingProgressState
  accepted_items: string[]
  skipped_items: ReadingSkippedItem[]
  resume_applied: boolean
  compact_pending: boolean
}

/** POST /reading-sessions：首次基线/清空懒迁移 + 打开增量窗口（幂等）。 */
export type ReadingWindowSession = {
  state: ReadingProgressState
  window_token: string
}

export type ReadingCompactResponse = {
  state: ReadingProgressState
  advanced: boolean
  compact_pending: boolean
}

export type ReadingAckResponse = {
  state: ReadingProgressState
  applied_upper_seq: Seq
}

/** GET /reading-items 单项反查结果。 */
export type ReadingItemLookup = {
  message_id: string
  item_key: string
  change_seq: Seq
  kind: ReadingItemKind
  active: boolean
}

export type ReadingItemsResponse = {
  items: ReadingItemLookup[]
}

/** GET /reading-resume：续读锚点 + 上下文消息。 */
export type ReadingResumeResponse = {
  task_id: string
  reading_epoch: Seq
  initialized: boolean
  anchor_status: ReadingAnchorStatus
  anchor?: ReadingResumeAnchorStatus | null
  messages: ReadingHistoryMessage[]
  has_before: boolean
  has_after: boolean
  notice?: ReadingBoundaryNotice | null
}

/** WS 控制帧 reading_progress_changed 的 payload（非 sequence 事件，经 onControlFrame 进入）。 */
export type ReadingProgressChangedPayload = {
  task_id: string
  reading_epoch: Seq
  state_revision: Seq
  resume_revision?: Seq
}

export type ReadingUpdateGroupType = 'turn' | 'flat' | 'notice'

/** 折叠视图分组（groupItems 的输出）：AI 轮次组 / 相邻普通消息 flat 组 / 边界通知组。 */
export type ReadingUpdateGroup = {
  key: string
  type: ReadingUpdateGroupType
  generation?: string | null
  turnId?: string | null
  messageCount: number
  unreadCount: number
  startedBy?: string | null
  startedAt?: string | null
  notice?: ReadingBoundaryNotice | null
  items: ReadingUpdateItem[]
}
