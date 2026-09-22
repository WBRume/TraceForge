import { describe, expect, it, vi } from 'vitest'

vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))

import { createTaskWsEventRouter } from '../session/wsEventRouter'

const createDeps = () => {
  const calls = {
    scroll: [] as string[],
    contextRefresh: 0,
    upserts: [] as any[],
    removedByIds: [] as Array<Set<string>>,
    statusSyncs: [] as string[],
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
      syncTaskStatus: (status: string) => calls.statusSyncs.push(status),
      getCurrentSessionGeneration: () => 2,
      getCurrentTaskStatus: () => 'CODING',
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
    applyTaskSessionPayload: (payload: any) => calls.appliedSessionPayloads.push(payload),
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
    expect(engineRunning.value).toBe(true)
    expect(calls.statusCardPushes[0]).toMatchObject({ type: 'status', status: 'RUNNING' })
    expect(calls.statusSyncs).toEqual(['CODING'])

    handleWsMessage({ type: 'status', payload: { status: 'DONE' } })
    expect(calls.statusSyncs).toEqual(['CODING', 'DONE'])
  })

  it('accumulates result frames and keeps terminal task status untouched', () => {
    const { deps, calls, engineRunning } = createDeps()
    const { handleWsMessage } = createTaskWsEventRouter(deps)
    ;(deps.task.getCurrentTaskStatus as any) = () => 'DONE'

    handleWsMessage({ type: 'result', payload: { duration_ms: 1200, cost_usd: 0.5, success: false } })
    expect(calls.summaryAppends).toHaveLength(1)
    expect(calls.statusCardDrops).toBe(1)
    // DONE 是终态：状态保持原值（显式写回 DONE），不改写为 INTERRUPTED
    expect(calls.statusSyncs).toEqual(['DONE'])

    engineRunning.value = false
    ;(deps.task.getCurrentTaskStatus as any) = () => 'CODING'
    handleWsMessage({ type: 'result', payload: { success: true } })
    expect(calls.statusSyncs).toEqual(['DONE', 'IDLE'])
  })

  it('applies session reverts: drops messages/logs/cards and syncs status', () => {
    const { deps, calls, engineRunning } = createDeps()
    const { handleWsMessage } = createTaskWsEventRouter(deps)
    engineRunning.value = true

    handleWsMessage({ type: 'task_session_reverted', payload: {
      task_id: 't1', removed_message_ids: ['m1', 'm2'], session_generation: 5, task_status: 'PENDING',
    } })

    expect(calls.generationBumps).toBe(1)
    expect(calls.readingRefreshes).toBe(1)
    expect(calls.removedByIds[0]).toEqual(new Set(['m1', 'm2']))
    expect(calls.cardsCleared).toBe(1)
    expect(calls.logClears).toBe(1)
    expect(calls.thinkingResets).toBe(1)
    expect(engineRunning.value).toBe(false)
    expect(calls.generationPatches).toEqual([5])
    expect(calls.statusSyncs).toEqual(['PENDING'])
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
