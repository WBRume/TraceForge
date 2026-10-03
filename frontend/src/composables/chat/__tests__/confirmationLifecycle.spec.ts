import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { usePinnedCards } from '../cards/usePinnedCards'
import { useChatJobs } from '../jobs/useChatJobs'
import { createChatJobIngest } from '../jobs/jobIngest'
import { useSessionState } from '../session/useSessionState'
import { useTaskStartActions } from '../actions/useTaskStartActions'
import { useTaskStatusActions } from '../actions/useTaskStatusActions'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/utils/api', () => ({ default: api }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))

const question = (id: string, jobId: string, generation: number) => ({
  id, role: 'assistant', content: 'Questions', session_generation: generation,
  metadata: { confirmation: { interaction_id: `interaction-${id}`, kind: 'form', job_id: jobId,
    fields: [{ key: 'build', title: '构建工具', type: 'string' }] } },
})

const createLifecycle = () => {
  const task = ref({ id: 'task', status: 'CODING', session_generation: 1 })
  const messages = ref<any[]>([question('old', 'old-job', 1)])
  const jobs = useChatJobs({
    getWorkspaceId: () => 'workspace', getTaskId: () => task.value.id,
    getSignal: () => undefined, onLoaded: () => { syncEngine(); return true },
  })
  const cards = usePinnedCards({
    getMessages: () => messages.value, getJobs: jobs.jobList, getCurrentTask: () => task.value,
  })
  const engineRunning = ref(false)
  const syncEngine = () => { engineRunning.value = jobs.hasExecutingJob() }
  const ingestJob = createChatJobIngest({ jobs, cards, syncEngineFromJobs: syncEngine, onJobUpdate: () => {} })
  const generationBump = vi.fn()
  const state = useSessionState({
    getWorkspaceId: () => 'workspace', getCurrentTask: () => task.value,
    submissions: { unconfirmedKeys: () => [], current: () => [], put: () => {},
      send: async () => true, clear: () => {} },
    ingestJob, resetJobs: jobs.reset, syncEngineFromJobs: syncEngine,
    convergeFromJobs: () => { syncEngine(); return true }, syncConfirmationCards: cards.syncConfirmationCards,
    upsertMessage: message => messages.value.push(message), loadHistory: async () => {},
    loadActivePreInput: async () => true, onSessionGenerationBump: generationBump,
    syncTaskStatus: status => { task.value.status = status },
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
    isTaskProvisioning: ref(false), canManageTaskStatus: ref(true), interruptingTask: ref(false),
    cardsDropStatusCards: cards.dropStatusCards, cardsDropByTypes: cards.dropByTypes, jobsReset: jobs.reset,
    messagesPush: message => messages.value.push(message), isHistoryAnchored: () => false,
    scrollToChatBottom: () => {},
    interruptTask: async () => ({ task_id: 'task', status: 'INTERRUPTED',
      session_generation: task.value.session_generation,
      job: { ...jobs.jobList().find(job => job.status === 'RUNNING'), status: 'INTERRUPTED' } }),
    applyTaskSessionPayload: state.applyTaskSessionPayload, refreshActiveJobs: jobs.loadActive,
    loadTasks: async () => {}, patchTask: (_id, patch) => Object.assign(task.value, patch),
    removeTask: () => {}, clearCurrentTask: () => {},
    router: createRouter({ history: createMemoryHistory(), routes: [] }),
    resolveActionError: (_error, key) => key,
  })
  ingestJob({ id: 'old-job', task_id: 'task', status: 'RUNNING', progress: 0, session_generation: 1 })
  cards.syncConfirmationCards()
  return { task, messages, jobs, cards, state, start, status, ingestJob, engineRunning, generationBump }
}

describe('confirmation lifecycle', () => {
  it('handles stop → initialize → new question → stop with the real action and state composables', async () => {
    const runtime = createLifecycle()
    expect(runtime.cards.activeHitlCards.value).toHaveLength(1)
    expect(await runtime.status.interruptCurrentRun()).toBe(true)
    runtime.cards.syncConfirmationCards()
    expect(runtime.cards.activeHitlCards.value).toHaveLength(0)
    const newJob = { id: 'new-job', task_id: 'task', status: 'RUNNING', progress: 0, session_generation: 2 }
    api.post.mockResolvedValue({ data: { msg: 'Task initialized', job: newJob } })
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
      jobs: [{ id: 'new-job', status: 'RUNNING', progress: 0, session_generation: 2 }],
      receipts: [], messages: [] } })
    await runtime.state.recoverSession('reconnect')
    expect(runtime.task.value.session_generation).toBe(2)
    expect(runtime.cards.activeHitlCards.value.map(card => card.message_id)).toEqual(['new'])
    runtime.state.applyTaskSessionPayload({ task_id: 'task', status: 'INTERRUPTED', session_generation: 1 })
    expect(runtime.task.value.status).toBe('CODING')
    expect(runtime.cards.activeHitlCards.value).toHaveLength(1)
    runtime.state.dispose()
  })

  it('ignores an old active-job response that arrives after initialization reset', async () => {
    const runtime = createLifecycle()
    let resolve!: (response: any) => void
    api.get.mockReturnValue(new Promise(response => { resolve = response }))
    const pending = runtime.jobs.loadActive('task')
    runtime.jobs.reset()
    resolve({ data: { items: [{ id: 'old-job', status: 'RUNNING', progress: 0, session_generation: 1 }] } })
    expect(await pending).toBe(false)
    expect(runtime.jobs.jobList()).toEqual([])
    expect(runtime.cards.activeHitlCards.value).toHaveLength(0)
    runtime.state.dispose()
  })
})
