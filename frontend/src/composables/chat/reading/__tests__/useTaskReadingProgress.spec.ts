import { describe, expect, it, vi } from 'vitest'
import type { ReadingProgressState, ReadingReceiptsResponse, ReadingWindowSession } from '@/types/taskReading'
import { compareSeq, seqGreaterThan } from '@/types/taskReading'

/**
 * useTaskReadingProgress 编排测试：mock taskReadingApi，聚焦
 * ① 回执合并 max/节流/50 上限 ② CAS 失败不重放 ③ WS 帧合并 single-flight
 * ④ epoch 变化清空重 init ⑤ BigInt 序号比较不丢精度。
 */
const apiStub = vi.hoisted(() => ({
  openReadingSession: vi.fn(),
  fetchReadingProgress: vi.fn(),
  submitReadingReceipts: vi.fn(),
  compactReadingProgress: vi.fn(),
  acknowledgeReadingProgress: vi.fn(),
  fetchReadingItems: vi.fn(),
  fetchReadingUpdates: vi.fn(),
  fetchReadingResume: vi.fn(),
}))

vi.mock('@/services/taskReadingApi', () => apiStub)

import { useTaskReadingProgress } from '@/composables/chat/reading/useTaskReadingProgress'

const makeState = (overrides: Partial<ReadingProgressState> = {}): ReadingProgressState => ({
  initialized: true,
  task_id: 'task-1',
  reading_epoch: '2',
  baseline_seq: '100',
  read_frontier_seq: '100',
  latest_change_seq: '110',
  state_revision: '1',
  has_unread: false,
  unread_count: { value: '0', relation: 'eq' },
  compact_pending: false,
  resume: null,
  reading_ready: true,
  ...overrides,
})

const makeSession = (state: ReadingProgressState, token: string): ReadingWindowSession => ({
  state,
  window_token: token,
})

const makeReceiptsResponse = (
  state: ReadingProgressState,
  overrides: Partial<ReadingReceiptsResponse> = {},
): ReadingReceiptsResponse => ({
  state,
  accepted_items: [],
  skipped_items: [],
  resume_applied: true,
  compact_pending: false,
  ...overrides,
})

const createController = () => useTaskReadingProgress({
  getWorkspaceId: () => 'ws-1',
  getTaskId: () => 'task-1',
  isTaskActive: () => true,
})

const flushMicrotasks = async () => {
  for (let i = 0; i < 8; i += 1) {
    await Promise.resolve()
  }
}

describe('useTaskReadingProgress', () => {
  it('clears retracted unread when only the content version advances and rejects stale snapshots', async () => {
    const unread = makeState({ has_unread: true, unread_count: { value: '1', relation: 'eq' } })
    apiStub.openReadingSession.mockResolvedValue(makeSession(unread, 'wt-1'))
    const ctl = createController()
    await ctl.ensureSession('task-1')
    apiStub.fetchReadingProgress.mockResolvedValue(makeState({ latest_change_seq: '111' }))
    await ctl.refresh('task-1')
    expect(ctl.progress.value?.has_unread).toBe(false)
    expect(ctl.progress.value?.unread_count.value).toBe('0')
    apiStub.fetchReadingProgress.mockResolvedValue(unread)
    await ctl.refresh('task-1')
    expect(ctl.progress.value?.has_unread).toBe(false)
    expect(ctl.progress.value?.latest_change_seq).toBe('111')
    ctl.reset()
  })

  it('merges receipts by max change_seq, throttles to 2s and caps batches at 50', async () => {
    vi.useFakeTimers()
    try {
      apiStub.openReadingSession.mockResolvedValue(makeSession(makeState(), 'wt-1'))
      apiStub.submitReadingReceipts.mockResolvedValue(makeReceiptsResponse(makeState({ state_revision: '2' })))

      const ctl = createController()
      await ctl.ensureSession('task-1')

      const first = ctl.submitReceipts('task-1', [{ item_key: 'message:a', change_seq: '110' }])
      // 更小的 seq 不应覆盖已合并的更大值
      ctl.submitReceipts('task-1', [{ item_key: 'message:a', change_seq: '109' }])
      const second = ctl.submitReceipts('task-1', [{ item_key: 'message:a', change_seq: '120' }])
      expect(ctl.pendingCount.value).toBe(1)

      expect(apiStub.submitReadingReceipts).not.toHaveBeenCalled()
      await vi.advanceTimersByTimeAsync(2000)
      await Promise.all([first, second])

      expect(apiStub.submitReadingReceipts).toHaveBeenCalledTimes(1)
      const firstBody = apiStub.submitReadingReceipts.mock.calls[0][0]
      expect(firstBody.items).toEqual([{ item_key: 'message:a', change_seq: '120' }])
      expect(firstBody.readingEpoch).toBe('2')
      expect(ctl.syncState.value).toBe('connected')

      // 超过 50 条：单次最多 50，剩余排队自动补一发
      const many = Array.from({ length: 75 }, (_, i) => ({
        item_key: `message:m${i}`,
        change_seq: String(200 + i),
      }))
      const third = ctl.submitReceipts('task-1', many)
      expect(ctl.pendingCount.value).toBe(75)
      await vi.advanceTimersByTimeAsync(2000)
      await third

      expect(apiStub.submitReadingReceipts).toHaveBeenCalledTimes(2)
      expect(apiStub.submitReadingReceipts.mock.calls[1][0].items).toHaveLength(50)
      expect(ctl.pendingCount.value).toBe(25)

      await vi.advanceTimersByTimeAsync(2000)
      expect(apiStub.submitReadingReceipts).toHaveBeenCalledTimes(3)
      expect(apiStub.submitReadingReceipts.mock.calls[2][0].items).toHaveLength(25)
      expect(ctl.pendingCount.value).toBe(0)
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not replay a resume position after the server reports resume_applied=false', async () => {
    vi.useFakeTimers()
    try {
      apiStub.openReadingSession.mockResolvedValue(makeSession(makeState(), 'wt-1'))
      apiStub.submitReadingReceipts
        .mockResolvedValueOnce(makeReceiptsResponse(makeState({ state_revision: '2' }), { resume_applied: false }))
        .mockResolvedValue(makeReceiptsResponse(makeState({ state_revision: '3' })))

      const ctl = createController()
      await ctl.ensureSession('task-1')

      const resume = { message_id: 'm1', content_seq: '5', offset_ratio: 0.5, expected_revision: '1' }
      const first = ctl.submitReceipts('task-1', [{ item_key: 'message:a', change_seq: '111' }], resume)
      await vi.advanceTimersByTimeAsync(2000)
      await first

      expect(apiStub.submitReadingReceipts).toHaveBeenCalledTimes(1)
      expect(apiStub.submitReadingReceipts.mock.calls[0][0].resume).toEqual(resume)

      // 后续 flush 不再携带旧 resume（CAS 失败不重放；wire body 由 service 层判空省略）
      const second = ctl.submitReceipts('task-1', [{ item_key: 'message:b', change_seq: '112' }])
      await vi.advanceTimersByTimeAsync(2000)
      await second
      expect(apiStub.submitReadingReceipts).toHaveBeenCalledTimes(2)
      expect(apiStub.submitReadingReceipts.mock.calls[1][0].resume).toBeNull()

      // 相同位置（同 message/content_seq/expected_revision）再次提交也被拒绝
      const third = ctl.submitReceipts('task-1', [{ item_key: 'message:c', change_seq: '113' }], { ...resume })
      await vi.advanceTimersByTimeAsync(2000)
      await third
      expect(apiStub.submitReadingReceipts).toHaveBeenCalledTimes(3)
      expect(apiStub.submitReadingReceipts.mock.calls[2][0].resume).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })

  it('coalesces WS revision frames into a single in-flight refresh and follows up once', async () => {
    apiStub.openReadingSession.mockResolvedValue(makeSession(makeState({ state_revision: '5' }), 'wt-1'))

    let resolveFirst!: (state: ReadingProgressState) => void
    const gate = new Promise<ReadingProgressState>((resolve) => {
      resolveFirst = resolve
    })
    apiStub.fetchReadingProgress
      .mockImplementationOnce(() => gate)
      .mockResolvedValue(makeState({ state_revision: '9' }))

    const ctl = createController()
    await ctl.ensureSession('task-1')

    ctl.handleWsFrame({ task_id: 'task-1', reading_epoch: '2', state_revision: '7' })
    // 在途期间到达的更高目标版本：只排队，不并发第二个请求
    ctl.handleWsFrame({ task_id: 'task-1', reading_epoch: '2', state_revision: '9' })
    await flushMicrotasks()
    expect(apiStub.fetchReadingProgress).toHaveBeenCalledTimes(1)

    resolveFirst(makeState({ state_revision: '7' }))
    await flushMicrotasks()

    // 队列中的 9 > 当前 7 → 自动补一次 refresh
    expect(apiStub.fetchReadingProgress).toHaveBeenCalledTimes(2)
    await flushMicrotasks()
    expect(ctl.progress.value?.state_revision).toBe('9')

    // 重复/回退帧不再触发请求
    ctl.handleWsFrame({ task_id: 'task-1', reading_epoch: '2', state_revision: '7' })
    ctl.handleWsFrame({ task_id: 'task-1', reading_epoch: '2', state_revision: '9' })
    await flushMicrotasks()
    expect(apiStub.fetchReadingProgress).toHaveBeenCalledTimes(2)
  })

  it('clears local state and re-initializes when a WS frame carries a newer epoch', async () => {
    vi.useFakeTimers()
    try {
      apiStub.openReadingSession
        .mockResolvedValueOnce(makeSession(makeState({ reading_epoch: '2' }), 'wt-old'))
        .mockResolvedValueOnce(makeSession(makeState({ reading_epoch: '3', state_revision: '1' }), 'wt-new'))

      const ctl = createController()
      await ctl.ensureSession('task-1')
      void ctl.submitReceipts('task-1', [{ item_key: 'message:a', change_seq: '111' }])
      expect(ctl.pendingCount.value).toBe(1)

      ctl.handleWsFrame({ task_id: 'task-1', reading_epoch: '3', state_revision: '1' })
      await vi.advanceTimersByTimeAsync(0)
      await flushMicrotasks()

      expect(apiStub.openReadingSession).toHaveBeenCalledTimes(2)
      expect(ctl.pendingCount.value).toBe(0)
      expect(ctl.progress.value?.reading_epoch).toBe('3')
      expect(ctl.windowToken.value).toBe('wt-new')

      // 落后 epoch 帧被忽略
      ctl.handleWsFrame({ task_id: 'task-1', reading_epoch: '2', state_revision: '99' })
      await flushMicrotasks()
      expect(ctl.progress.value?.state_revision).toBe('1')
      expect(apiStub.openReadingSession).toHaveBeenCalledTimes(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it('compares decimal seq strings with BigInt precision beyond 2^53', async () => {
    // Number() 之下这两个值已经无法区分
    expect(Number('9007199254740993')).toBe(Number('9007199254740992'))
    expect(compareSeq('9007199254740993', '9007199254740992')).toBe(1)
    expect(seqGreaterThan('9007199254740993', '9007199254740992')).toBe(true)
    expect(compareSeq('10', '9')).toBe(1)
    expect(compareSeq('7', '7')).toBe(0)
    expect(compareSeq('3', '12')).toBe(-1)

    // 回执合并同样走 BigInt：>2^53 的更大值不被较小值覆盖
    vi.useFakeTimers()
    try {
      apiStub.openReadingSession.mockResolvedValue(makeSession(makeState(), 'wt-1'))
      apiStub.submitReadingReceipts.mockResolvedValue(makeReceiptsResponse(makeState({ state_revision: '2' })))

      const ctl = createController()
      await ctl.ensureSession('task-1')
      const pending = ctl.submitReceipts('task-1', [
        { item_key: 'message:big', change_seq: '9007199254740992' },
      ])
      ctl.submitReceipts('task-1', [{ item_key: 'message:big', change_seq: '9007199254740993' }])
      await vi.advanceTimersByTimeAsync(2000)
      await pending

      const body = apiStub.submitReadingReceipts.mock.calls[0]?.[0]
      expect(body?.items).toEqual([{ item_key: 'message:big', change_seq: '9007199254740993' }])
    } finally {
      vi.useRealTimers()
    }
  })

  it('keeps the pending queue offline when a flush fails and drains it on recovery', async () => {
    vi.useFakeTimers()
    try {
      apiStub.openReadingSession.mockResolvedValue(makeSession(makeState(), 'wt-1'))
      apiStub.submitReadingReceipts
        .mockRejectedValueOnce({ response: { status: 503, data: { detail: 'unavailable' } } })
        .mockResolvedValue(makeReceiptsResponse(makeState({ state_revision: '2' })))

      const ctl = createController()
      await ctl.ensureSession('task-1')

      const first = ctl.submitReceipts('task-1', [{ item_key: 'message:a', change_seq: '111' }])
      await vi.advanceTimersByTimeAsync(2000)
      await first

      expect(ctl.syncState.value).toBe('offline')
      expect(ctl.pendingCount.value).toBe(1)

      // 网络恢复：下一次事件/交互触发 flushNow
      await ctl.flushNow('task-1')
      expect(ctl.syncState.value).toBe('connected')
      expect(ctl.pendingCount.value).toBe(0)
      expect(apiStub.submitReadingReceipts).toHaveBeenCalledTimes(2)
    } finally {
      vi.useRealTimers()
    }
  })
})
