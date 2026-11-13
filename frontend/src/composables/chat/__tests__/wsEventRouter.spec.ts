import { describe, expect, it, vi } from 'vitest'

vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))

import { createTaskWsEventRouter } from '../session/wsEventRouter'

const createDeps = () => {
  const calls = {
    scroll: [] as string[],
    contextRefresh: 0,
    upserts: [] as any[],
    removedByIds: [] as Array<Set<string>>,
    statusSyncs: [] as any[],
    statusCardPushes: [] as any[],
    statusCardDrops: 0,
    cardsCleared: 0,
    logClears: 0,
    thinkingResets: 0,
    logAppends: [] as any[],
    ingested: [] as any[],
    summaryAppends: [] as any[],
    generationBumps: 0,
    readingRefreshes: 0,
    generationPatches: [] as number[],
    appliedSessionPayloads: [] as any[],
    preinputEvents: [] as string[],
    specUpdates: [] as any[],
    suggestionNudges: [] as any[],
    traceMerges: [] as any[],
    usageRefreshes: 0,
    engineSyncs: 0,
    activeJobRefreshes: [] as string[],
  }
  const engineRunning = { value: false }
  const deps = {
    task: {
      getTaskId: () => 't1',
      patchSessionGeneration: (generation: number) => calls.generationPatches.push(generation),
      applyTaskStatusSnapshot: (snapshot: any) => { calls.statusSyncs.push(snapshot) },
      getCurrentSessionGeneration: () => 2,
      getCurrentTaskStatus: () => 'RUNNING',
    },
    messages: {
      upsert: (message: any) => calls.upserts.push(message),
      findByIdentity: () => undefined,
      removeByIds: (ids: Set<string>) => calls.removedByIds.push(ids),
    },
    terminalLogs: {
      appendToolUse: (payload: any) => calls.logAppends.push({ kind: 'tool_use', payload }),
      appendToolResult: (payload: any) => calls.logAppends.push({ kind: 'tool_result', payload }),
      appendLog: (payload: any) => calls.logAppends.push({ kind: 'log', payload }),
      clear: () => { calls.logClears += 1 },
    },
    cards: {
      syncConfirmationCards: () => {},
      dropStatusCards: () => { calls.statusCardDrops += 1 },
      pushStatusCard: (card: any) => calls.statusCardPushes.push(card),
      clear: () => { calls.cardsCleared += 1 },
    },
    engine: {
      engineRunning,
      syncFromJobs: () => { calls.engineSyncs += 1 },
      applyThinkingFrame: (payload: any) => { calls.logAppends.push({ kind: 'thinking', payload }) },
      resetThinking: () => { calls.thinkingResets += 1 },
    },
    resultsSummary: {
      appendResult: (payload: any) => calls.summaryAppends.push(payload),
    },
    submissions: {
      busy: () => false,
      put: () => {},
      removeMessages: () => {},
    },
    ingestJob: (job: any) => calls.ingested.push(job),
    refreshActiveJobs: (taskId: string) => { calls.activeJobRefreshes.push(taskId); return Promise.resolve(true) },
    applyTaskSessionPayload: (payload: any) => {
      calls.appliedSessionPayloads.push(payload)
      return true
    },
    specBootstrapApplyUpdate: (payload: any) => calls.specUpdates.push(payload),
    shareSuggestionNudge: (payload: any) => calls.suggestionNudges.push(payload),
    preinputHandleEvent: (type: string) => calls.preinputEvents.push(type),
    skillsMergeTraceEvent: (event: any) => calls.traceMerges.push(event),
    skillsScheduleUsageRefresh: () => { calls.usageRefreshes += 1 },
    onSessionGenerationBump: () => { calls.generationBumps += 1 },
    onMessagesRetracted: () => { calls.readingRefreshes += 1 },
    contextWindowScheduleRefresh: () => { calls.contextRefresh += 1 },
    scrollTo: (target: 'chat' | 'terminal') => calls.scroll.push(target),
    isHistoryAnchored: () => false,
    getRouteMessageId: () => '',
  }
  return { deps, calls, engineRunning }
}

describe('createTaskWsEventRouter', () => {
  it('applies only the explicit versioned task status event', () => {
    const { deps, calls } = createDeps()
    const router = createTaskWsEventRouter(deps)
    const snapshot = { task_id: 't1', status: 'AWAITING_INPUT', status_seq: '42' }
    router.handleWsMessage({ type: 'task_status_changed', payload: snapshot })
    expect(calls.statusSyncs).toEqual([snapshot])
  })

  it.each(['ask_question', 'request_approval', 'confirmation'])('maps %s to awaiting input', type => {
    const { deps, calls } = createDeps()
    createTaskWsEventRouter(deps).handleWsMessage({ type, payload: { task_id: 't1', session_generation: 2 } })
    expect(calls.statusSyncs).toEqual([])
  })

  it('ignores stale results and running signals after interruption', () => {
    const { deps, calls } = createDeps()
    deps.task.getCurrentTaskStatus = () => 'INTERRUPTED'
    const router = createTaskWsEventRouter(deps)
    router.handleWsMessage({ type: 'result', payload: { success: true, session_generation: 1 } })
    router.handleWsMessage({ type: 'status', payload: { status: 'RUNNING', session_generation: 2 } })
    router.handleWsMessage({ type: 'result', payload: { success: true, session_generation: 2 } })
    expect(calls.statusSyncs).toEqual([])
  })

  it('keeps an unresolved question awaiting input after a successful provider result', () => {
    const { deps, calls } = createDeps()
    deps.task.getCurrentTaskStatus = () => 'AWAITING_INPUT'
    createTaskWsEventRouter(deps).handleWsMessage({ type: 'result', payload: { success: true } })
    expect(calls.statusSyncs).toEqual([])
  })

  it('discards an older round result within the same session generation', () => {
    const { deps, calls } = createDeps()
    const router = createTaskWsEventRouter({ ...deps, task: { ...deps.task, getCurrentSessionRevision: () => 4 } })
    router.handleWsMessage({ type: 'result', payload: { success: true, session_generation: 2, session_revision: 3 } })
    expect(calls.statusSyncs).toEqual([])
    expect(calls.summaryAppends).toEqual([])
  })
  it('keeps the task conversation on repository apply and invalidates only older undo actions', () => {
    const { deps, calls } = createDeps()
    const invalidateUndoBeforeRevision = vi.fn()
    const { handleWsMessage } = createTaskWsEventRouter({ ...deps, messages: { ...deps.messages, invalidateUndoBeforeRevision } })
    const payload = { task_id:'t1', state:'APPLIED', session_id:'original-session', session_generation:2, undo_before_revision:8 }
    handleWsMessage({ type:'task_repository_update', payload })
    expect(calls.appliedSessionPayloads).toEqual([payload])
    expect(invalidateUndoBeforeRevision).toHaveBeenCalledWith(8)
    expect(calls.generationBumps).toBe(0)
    expect(calls.removedByIds).toHaveLength(0)
    expect(calls.cardsCleared).toBe(0)
  })
  it('forwards collaboration notifications from the task socket without touching the conversation', () => {
    const { deps, calls } = createDeps()
    const collaborationUpdate = vi.fn()
    const { handleWsMessage } = createTaskWsEventRouter({ ...deps, collaborationUpdate })
    const payload = { task_id: 't1', state_version: 4, session_generation: 2, sync_phase: 'DELIVERY_PENDING' }
    handleWsMessage({ type: 'workspace_collaboration_update', payload })
    expect(collaborationUpdate).toHaveBeenCalledWith(payload)
    expect(calls.upserts).toHaveLength(0)
    expect(calls.scroll).toHaveLength(0)
  })
  it('retains historical messages without rolling the current generation backward', () => {
    const { deps, calls } = createDeps()
    const { handleWsMessage } = createTaskWsEventRouter(deps)
    handleWsMessage({ type: 'chat_message', payload: {
      id: 'old', task_id: 't1', role: 'assistant', content: '旧问题', session_generation: 1,
    } })
    expect(calls.upserts[0]).toMatchObject({ id: 'old', session_generation: 1 })
    expect(calls.generationPatches).toEqual([])
  })
  it('routes chat_message to message store + confirmation sync + chat scroll', () => {
    const { deps, calls } = createDeps()
    const { handleWsMessage } = createTaskWsEventRouter(deps)

    handleWsMessage({ type: 'chat_message', payload: {
      id: 'm1', role: 'user', content: 'hi', message_type: 'text', session_generation: 3, task_id: 't1',
    } })

    expect(calls.upserts[0]).toMatchObject({ id: 'm1', content: 'hi', delivery_status: 'sent' })
    expect(calls.generationPatches).toEqual([3])
    expect(calls.scroll).toEqual(['chat'])
    expect(calls.contextRefresh).toBe(1)
  })

  it('maps status frames to status cards and task status transition', () => {
    const { deps, calls, engineRunning } = createDeps()
    const { handleWsMessage } = createTaskWsEventRouter(deps)

    handleWsMessage({ type: 'status', payload: { status: 'RUNNING', message: 'working', model: 'm' } })
    expect(engineRunning.value).toBe(false)
    expect(calls.statusCardPushes[0]).toMatchObject({ type: 'status', status: 'RUNNING' })
    expect(calls.statusSyncs).toEqual([])

    handleWsMessage({ type: 'status', payload: { status: 'COMPLETED' } })
    expect(calls.statusSyncs).toEqual([])
  })

  it('accumulates result frames and keeps terminal task status untouched', () => {
    const { deps, calls, engineRunning } = createDeps()
    const { handleWsMessage } = createTaskWsEventRouter(deps)
    ;(deps.task.getCurrentTaskStatus as any) = () => 'COMPLETED'

    handleWsMessage({ type: 'result', payload: { duration_ms: 1200, cost_usd: 0.5, success: false } })
    expect(calls.summaryAppends).toHaveLength(1)
    expect(calls.statusCardDrops).toBe(1)
    // 终态忽略迟到的结果，保持已结算状态。
    expect(calls.statusSyncs).toEqual([])

    engineRunning.value = false
    ;(deps.task.getCurrentTaskStatus as any) = () => 'RUNNING'
    handleWsMessage({ type: 'result', payload: { success: true } })
    expect(calls.statusSyncs).toEqual([])
  })

  it('applies session reverts: drops messages/logs/cards and syncs status', () => {
    const { deps, calls, engineRunning } = createDeps()
    const { handleWsMessage } = createTaskWsEventRouter(deps)
    engineRunning.value = true

    handleWsMessage({ type: 'task_session_reverted', payload: {
      task_id: 't1', removed_message_ids: ['m1', 'm2'], session_generation: 5, task_snapshot: { task_id: 't1', status: 'INITIALIZED', status_seq: '4' },
    } })

    expect(calls.generationBumps).toBe(1)
    expect(calls.readingRefreshes).toBe(1)
    expect(calls.removedByIds[0]).toEqual(new Set(['m1', 'm2']))
    expect(calls.cardsCleared).toBe(1)
    expect(calls.logClears).toBe(1)
    expect(calls.thinkingResets).toBe(1)
    expect(engineRunning.value).toBe(false)
    expect(calls.generationPatches).toEqual([5])
    expect(calls.statusSyncs).toEqual([{ task_id: 't1', status: 'INITIALIZED', status_seq: '4' }])
  })

  it('routes transport-only frames to their domains without touching the chat flow', () => {
    const { deps, calls } = createDeps()
    const { handleWsMessage } = createTaskWsEventRouter(deps)

    handleWsMessage({ type: 'tool_use', payload: { tool_name: 'bash' } })
    handleWsMessage({ type: 'skill_runtime_event', payload: { id: 'e1' } })
    handleWsMessage({ type: 'spec_bootstrap_update', payload: { task_id: 't1' } })
    handleWsMessage({ type: 'share_suggestion_update', payload: { task_id: 't1', recipient_user_id: 'u1' } })
    handleWsMessage({ type: 'pre_input_update', payload: {} })
    handleWsMessage({ type: 'chat_job_done', payload: { job: { id: 'j1', status: 'SUCCESS' } } })

    expect(calls.logAppends[0]?.kind).toBe('tool_use')
    expect(calls.usageRefreshes).toBe(1)
    expect(calls.traceMerges).toHaveLength(1)
    expect(calls.specUpdates).toHaveLength(1)
    expect(calls.suggestionNudges).toEqual([{ task_id: 't1', recipient_user_id: 'u1' }])
    expect(calls.preinputEvents).toEqual(['pre_input_update'])
    expect(calls.ingested[0]).toMatchObject({ id: 'j1' })
  })

  it('gates stale submission events by session generation', () => {
    const { deps, calls } = createDeps()
    const { handleWsMessage } = createTaskWsEventRouter(deps)

    handleWsMessage({ type: 'chat_submission_update', payload: {
      task_id: 't1', session_generation: 1, receipt: { client_message_id: 'c1' },
    } })
    expect(calls.ingested).toEqual([])

    handleWsMessage({ type: 'chat_submission_update', payload: {
      task_id: 't1', session_generation: 3, receipt: { client_message_id: 'c1' },
      job: { id: 'j9', status: 'PENDING' },
    } })
    expect(calls.ingested[0]).toMatchObject({ id: 'j9' })
  })
})
