import { applyTaskStatusSnapshot } from '@/utils/taskStatusProjection'
import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { usePinnedCards } from '../cards/usePinnedCards'
import { useChatJobs } from '../jobs/useChatJobs'
import { createChatJobIngest } from '../jobs/jobIngest'
import { useSessionState } from '../session/useSessionState'
import { useTaskStartActions } from '../actions/useTaskStartActions'
import { useTaskStatusActions } from '../actions/useTaskStatusActions'
import { messageIdentity } from '../shared/messageIdentity'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/utils/api', () => ({ default: api }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))

const question = (id: string, jobId: string, generation: number) => ({
  id, role: 'assistant', content: 'Questions', session_generation: generation,
  metadata: { confirmation: { interaction_id: `interaction-${id}`, kind: 'form', job_id: jobId,
    fields: [{ key: 'build', title: '构建工具', type: 'string' }] } },
})

const createLifecycle = () => {
  const task = ref({ id: 'task', status: 'RUNNING', status_seq: '1', session_generation: 1, session_revision: 1 })
  const messages = ref<any[]>([question('old', 'old-job', 1)])
  const jobs = useChatJobs({
    getWorkspaceId: () => 'workspace', getTaskId: () => task.value.id,
    getSignal: () => undefined, onLoaded: () => { syncEngine(); return true },
  })
  const cards = usePinnedCards({
    getMessages: () => messages.value, getJobs: jobs.jobList, getCurrentTask: () => task.value,
  })
  const engineRunning = ref(false)
  const preparingSubmission = ref(false)
  const putSubmission = vi.fn(() => { preparingSubmission.value = false })
  const receipts = ref<any[]>([])
  const sendSubmission = vi.fn(async () => true)
  const syncEngine = () => { engineRunning.value = jobs.hasExecutingJob() }
  const { ingest: ingestJob, onAccepted } = createChatJobIngest({ jobs, cards, syncEngineFromJobs: syncEngine, onJobUpdate: () => {} })
  const generationBump = vi.fn()
  const interruptTask = vi.fn(async () => ({ task_id: 'task', status: 'INTERRUPTED', status_seq: String(Number(task.value.status_seq) + 1),
    session_generation: task.value.session_generation,
    job: { ...jobs.jobList().find(job => job.status === 'RUNNING'), status: 'INTERRUPTED' } }))
  const state = useSessionState({
    getWorkspaceId: () => 'workspace', getCurrentTask: () => task.value,
    submissions: { unconfirmedKeys: () => receipts.value.map(row => row.client_message_id), current: () => receipts.value,
      put: putSubmission, send: sendSubmission, clear: () => {} },
    ingestJob, jobs, onSnapshotJobAccepted: onAccepted, syncEngineFromJobs: syncEngine,
    convergeFromJobs: () => { syncEngine(); return true }, syncConfirmationCards: cards.syncConfirmationCards,
    messages: {
      captureIdentitySnapshot: () => new Map(messages.value.map(message => [messageIdentity(message), message])),
      mergeSessionSnapshot: incoming => messages.value.push(...incoming),
    },
    loadHistory: async () => true,
    loadActivePreInput: async () => true, onSessionGenerationBump: generationBump,
    applyTaskStatusSnapshot: snapshot => { applyTaskStatusSnapshot(task.value, snapshot) },
    reloadSpecBootstrap: () => {}, hasTaskSpecification: () => false,
  })
  const persistedHistory = [...messages.value]
  const start = useTaskStartActions({
    getCurrentTask: () => task.value, getWorkspaceId: () => 'workspace',
    isTaskPreStart: ref(false), isTaskProvisioning: ref(false), canStartTask: ref(true),
    canManageTaskStatus: ref(true), engineRunning, submissionsClear: () => {},
    loadHistory: async () => { messages.value = [...persistedHistory]; cards.syncConfirmationCards() },
    refreshActiveJobs: jobs.loadActive,
    resetConversationView: () => { cards.clear(); jobs.reset(); messages.value = []; engineRunning.value = false },
    applyTaskSessionPayload: state.applyTaskSessionPayload,
    patchTask: (_id, patch) => Object.assign(task.value, patch), specDrawerClose: () => {},
    scrollIfNotAnchored: () => {},
    skills: { taskRuntimeSkills: ref([]), taskRuntimeSkillsLoading: ref(false),
      showTaskSkillsDrawer: ref(false), loadTaskRuntimeSkills: async () => true },
    resolveActionError: (_error, key) => key,
  })
  const status = useTaskStatusActions({
    getCurrentTask: () => task.value, getWorkspaceId: () => 'workspace', engineRunning,
    preparingSubmission,
    isTaskProvisioning: ref(false), canManageTaskStatus: ref(true), interruptingTask: ref(false),
    cardsDropStatusCards: cards.dropStatusCards, cardsDropByTypes: cards.dropByTypes, jobsReset: jobs.reset,
    messagesPush: message => messages.value.push(message), isHistoryAnchored: () => false,
    scrollToChatBottom: () => {},
    interruptTask,
    applyTaskSessionPayload: state.applyTaskSessionPayload, refreshActiveJobs: jobs.loadActive,
    loadTasks: async () => {}, patchTask: (_id, patch) => Object.assign(task.value, patch),
    removeTask: () => {}, clearCurrentTask: () => {},
    router: createRouter({ history: createMemoryHistory(), routes: [] }),
    resolveActionError: (_error, key) => key,
  })
  ingestJob({ id: 'old-job', task_id: 'task', status: 'RUNNING', progress: 0, session_generation: 1 })
  cards.syncConfirmationCards()
  return { task, messages, jobs, cards, state, start, status, ingestJob, engineRunning, preparingSubmission,
    putSubmission, interruptTask, generationBump, receipts, sendSubmission }
}

describe('confirmation lifecycle', () => {
  it.each([false, true])('allows interrupting RUNNING preparation regardless of the engine flag (%s)', async engineRunning => {
    const runtime = createLifecycle()
    runtime.jobs.reset()
    runtime.engineRunning.value = engineRunning
    runtime.preparingSubmission.value = true
    expect(runtime.status.canTemporarilyInterrupt.value).toBe(true)
    expect(await runtime.status.interruptCurrentRun()).toBe(true)
    expect(runtime.interruptTask).toHaveBeenCalledOnce()
    expect(runtime.task.value.status).toBe('INTERRUPTED')
    expect(runtime.status.canTemporarilyInterrupt.value).toBe(false)
    runtime.state.dispose()
  })

  it('keeps initialization busy while clearing the old run and restores history if the request fails', async () => {
    const runtime = createLifecycle()
    api.get.mockResolvedValue({ data: { items: [
      { id: 'old-job', task_id: 'task', status: 'RUNNING', status_seq: '1', progress: 0, session_generation: 1 },
    ] } })
    let reject!: (reason: Error) => void
    api.post.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail }))
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      const pending = runtime.start.initializeTaskWithReason('重新开始', '新的提示词')
      expect(runtime.start.initializingTask.value).toBe(true)
      expect(runtime.messages.value).toEqual([])
      expect(runtime.cards.activeHitlCards.value).toHaveLength(0)
      expect(await runtime.start.initializeTaskWithReason()).toBe(false)
      reject(new Error('request failed'))
      expect(await pending).toBe(false)
      expect(runtime.start.initializingTask.value).toBe(false)
      expect(runtime.messages.value[0].id).toBe('old')
      expect(runtime.cards.activeHitlCards.value).toHaveLength(1)
    } finally {
      consoleError.mockRestore()
      runtime.state.dispose()
    }
  })

  it('handles stop → initialize → new question → stop with the real action and state composables', async () => {
    const runtime = createLifecycle()
    expect(runtime.cards.activeHitlCards.value).toHaveLength(1)
    expect(await runtime.status.interruptCurrentRun()).toBe(true)
    runtime.cards.syncConfirmationCards()
    expect(runtime.cards.activeHitlCards.value).toHaveLength(0)
    const newJob = { id: 'new-job', task_id: 'task', status: 'RUNNING', status_seq: '1', progress: 0, session_generation: 2 }
    api.post.mockResolvedValue({ data: { msg: 'Task initialized', status: 'RUNNING', status_seq: '3', task_id: 'task', job: newJob } })
    api.get.mockResolvedValue({ data: { items: [newJob] } })
    expect(await runtime.start.initializeTaskWithReason('重新开始', '请询问 Java 项目需求')).toBe(true)
    expect(runtime.task.value.session_generation).toBe(2)
    expect(runtime.generationBump).toHaveBeenCalledOnce()
    expect(runtime.cards.activeHitlCards.value).toHaveLength(0)
    expect(runtime.messages.value[0].id).toBe('old')
    runtime.messages.value.push(question('new', 'new-job', 2))
    runtime.cards.syncConfirmationCards()
    expect(runtime.cards.activeHitlCards.value.map(card => card.message_id)).toEqual(['new'])
    expect(await runtime.status.interruptCurrentRun()).toBe(true)
    runtime.cards.syncConfirmationCards()
    expect(runtime.cards.activeHitlCards.value).toHaveLength(0)
    runtime.state.dispose()
  })

  it('removes stale running jobs when a reconnect snapshot has no active jobs', async () => {
    const runtime = createLifecycle()
    api.get.mockResolvedValue({ data: { task_id: 'task', session_generation: 1,
      jobs: [], receipts: [], messages: [] } })
    await runtime.state.recoverSession('reconnect')
    expect(runtime.jobs.jobList()).toEqual([])
    expect(runtime.cards.activeHitlCards.value).toHaveLength(0)
    expect(runtime.engineRunning.value).toBe(false)
    runtime.state.dispose()
  })

  it('restores the generation from a snapshot before deciding which historical question can be answered', async () => {
    const runtime = createLifecycle()
    runtime.messages.value.push(question('new', 'new-job', 2))
    api.get.mockResolvedValue({ data: { task_id: 'task', session_generation: 2,
      jobs: [{ id: 'new-job', status: 'RUNNING', status_seq: '1', progress: 0, session_generation: 2 }],
      receipts: [], messages: [] } })
    await runtime.state.recoverSession('reconnect')
    expect(runtime.task.value.session_generation).toBe(2)
    expect(runtime.cards.activeHitlCards.value.map(card => card.message_id)).toEqual(['new'])
    runtime.state.applyTaskSessionPayload({ task_id: 'task', status: 'INTERRUPTED', status_seq: '2', session_generation: 1 })
    expect(runtime.task.value.status).toBe('RUNNING')
    expect(runtime.cards.activeHitlCards.value).toHaveLength(1)
    runtime.state.dispose()
  })

  it('ignores an old active-job response that arrives after initialization reset', async () => {
    const runtime = createLifecycle()
    let resolve!: (response: any) => void
    api.get.mockReturnValue(new Promise(response => { resolve = response }))
    const pending = runtime.jobs.loadActive('task')
    runtime.jobs.reset()
    resolve({ data: { items: [{ id: 'old-job', status: 'RUNNING', status_seq: '1', progress: 0, session_generation: 1 }] } })
    expect(await pending).toBe(false)
    expect(runtime.jobs.jobList()).toEqual([])
    expect(runtime.cards.activeHitlCards.value).toHaveLength(0)
    runtime.state.dispose()
  })

  it('keeps a newer WS terminal version and a newly observed job while pruning older absent jobs', async () => {
    const runtime = createLifecycle()
    const job = { id: 'finishing', status: 'RUNNING' as const, progress: 0, version: 1, session_generation: 1 }
    runtime.ingestJob(job)
    let resolve!: (response: any) => void
    api.get.mockReturnValueOnce(new Promise(response => { resolve = response }))
    const pending = runtime.state.recoverSession('send-unknown')
    runtime.ingestJob({ ...job, status: 'SUCCESS', progress: 100, version: 2 })
    runtime.ingestJob({ ...job, id: 'live' })
    resolve({ data: { task_id: 'task', session_generation: 1, session_revision: 1, jobs: [job] } })
    expect(await pending).toBe(true)
    expect(runtime.jobs.jobList().map(item => item.id)).toEqual(['live'])
    expect(runtime.engineRunning.value).toBe(true)
    runtime.ingestJob(job)
    expect(runtime.jobs.jobList().map(item => item.id)).toEqual(['live'])
    runtime.state.dispose()
  })

  it('rejects a same-generation pre-revert snapshot before writing messages or retrying a send', async () => {
    const runtime = createLifecycle()
    runtime.receipts.value = [{ task_id: 'task', client_message_id: 'unknown', status: 'UNKNOWN', content: 'prompt' }]
    let resolve!: (response: any) => void
    api.get.mockReturnValueOnce(new Promise(response => { resolve = response }))
    const pending = runtime.state.recoverSession('send-unknown')
    runtime.state.applyTaskSessionVersion({ task_id: 'task', session_generation: 1, session_revision: 2 })
    resolve({ data: { task_id: 'task', session_generation: 1, session_revision: 1, messages: [question('removed', 'old-job', 1)] } })
    expect(await pending).toBe(false)
    expect(runtime.messages.value.map(message => message.id)).toEqual(['old'])
    expect(runtime.sendSubmission).not.toHaveBeenCalled()
    runtime.state.dispose()
  })

  it('coalesces recovery but only resubmits a key included in that request', async () => {
    const runtime = createLifecycle()
    const row = { task_id: 'task', client_message_id: 'queried', status: 'UNKNOWN', content: 'prompt' }
    runtime.receipts.value = [row]
    let resolve!: (response: any) => void
    api.get.mockReturnValueOnce(new Promise(response => { resolve = response }))
    const pending = runtime.state.recoverSession('send-unknown')
    runtime.receipts.value.push({ ...row, client_message_id: 'newer' })
    expect(runtime.state.recoverSession('send-unknown')).toBe(pending)
    resolve({ data: { task_id: 'task', session_generation: 1, session_revision: 1 } })
    expect(await pending).toBe(true)
    expect(runtime.sendSubmission.mock.calls).toEqual([['task', 'queried', 'prompt', undefined]])
    runtime.state.dispose()
  })

  it('keeps a newer same-task request in flight after switching away and back', async () => {
    const runtime = createLifecycle()
    let resolveOld!: (response: any) => void
    let resolveCurrent!: (response: any) => void
    api.get.mockReturnValueOnce(new Promise(response => { resolveOld = response }))
      .mockReturnValueOnce(new Promise(response => { resolveCurrent = response }))
    const old = runtime.state.recoverSession('first-entry')
    runtime.state.beginTaskSwitch()
    const current = runtime.state.recoverSession('returned-to-same-task')
    const snapshot = { data: { task_id: 'task', session_generation: 1, session_revision: 1 } }
    resolveOld(snapshot)
    expect(await old).toBe(false)
    expect(runtime.state.recoverSession('parallel-caller')).toBe(current)
    resolveCurrent(snapshot)
    expect(await current).toBe(true)
    runtime.state.dispose()
  })
})
