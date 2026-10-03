import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { reactive } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import App from '@/App.vue'
import api from '@/utils/api'
import { useTaskAwarenessStore } from '../taskAwareness'
import { usePinnedFloatsStore } from '../pinnedFloats'
import { useNotificationStore } from '../notification'
import { clearWsCursorMemory } from '@/utils/wsCursor'
import { useTaskStartActions } from '@/composables/chat/actions/useTaskStartActions'

const mocks = vi.hoisted(() => ({ auth: null as any }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => mocks.auth }))
vi.mock('@/utils/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
vi.mock('@/utils/ws', () => ({ buildBackendWsUrl: () => 'ws://localhost/notifications' }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('@/components/global-search/GlobalSearchHost.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/ProvisionFloatingWidget.vue', () => ({ default: { template: '<div />' } }))
class Socket {
  static OPEN = 1
  static connections: Socket[] = []
  readyState = 1; sequence = 0
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose = null; onerror = null
  close = vi.fn(); send = vi.fn()
  constructor() { Socket.connections.push(this) }
  update(payload: any, durable = true) {
    this.onmessage?.({ data: JSON.stringify(durable ? { type: 'event', epoch: 'awareness', sequence: ++this.sequence,
      event_id: `frame-${this.sequence}`, event_type: 'notification', payload } : { type: 'notification', payload }) })
  }
}
const runtime = (state = 'AI_RUNNING', version = 1) => ({
  event_id: `run-${version}`, event_type: state, workspace: { id: 'w1', name: '工作区' },
  task: { id: 't1', title: 'Task A', url: '/workspaces/w1/chat/t1' }, initiator: { id: 'u1', name: '本人' }, summary: '',
  run: { id: 'j1', version, started_at: new Date(Date.now() - 30000).toISOString(), client_message_id: 'c1' },
})
let wrapper: ReturnType<typeof mount>
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear(); clearWsCursorMemory(); Socket.connections = []
  vi.stubGlobal('WebSocket', Socket); vi.spyOn(document, 'hasFocus').mockReturnValue(true)
  mocks.auth = reactive({ token: 'test', user: { id: 'u1' }, isAuthenticated: true, fetchCurrentUser: vi.fn() })
  vi.mocked(api.get).mockResolvedValue({ data: { items: [], count: 0, runs: [] } })
  vi.mocked(api.post).mockResolvedValue({ data: { items: [] } })
})
afterEach(() => { wrapper?.unmount(); delete window.sddDesktop; vi.unstubAllGlobals() })
async function setup() {
  const pinia = createPinia()
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/workspaces/:wsId/chat/:taskId', name: 'taskChat', component: { render: () => null } },
    { path: '/settings', name: 'settings', component: { render: () => null } },
  ] })
  await router.push('/workspaces/w1/chat/t1'); await router.isReady()
  wrapper = mount(App, { global: { plugins: [pinia, router] } }); await flushPromises()
  Socket.connections[0].onopen?.(); await flushPromises()
  return { router, awareness: useTaskAwarenessStore(pinia), floats: usePinnedFloatsStore(pinia), notifications: useNotificationStore(pinia), socket: Socket.connections[0] }
}
describe('root notification socket integration', () => {
  it('tracks an explicit run across routes on one existing socket and receives bounded live output', async () => {
    const { router, awareness, floats, notifications, socket } = await setup()
    awareness.arm('t1', 'c1'); socket.update({ type: 'task_runtime_event', event: runtime() }); await flushPromises()
    expect(floats.items).toHaveLength(0)
    await router.push('/settings'); await flushPromises()
    expect(floats.items[0].runtimeState).toBe('AI_RUNNING'); expect(Socket.connections).toHaveLength(1)
    socket.update({ type: 'task_runtime_output', task_id: 't1', job_id: 'j1', kind: 'thinking', payload: { delta: 'live context' } }, false)
    await flushPromises(); expect(awareness.outputs.t1.text).toBe('live context'); expect(notifications.unreadCount).toBe(0)
    await router.push('/workspaces/w1/chat/t1'); await flushPromises(); expect(floats.items).toHaveLength(0)
  })
  it('reading historical failures does not seed qualification through the socket', async () => {
    const { router, awareness, floats, socket } = await setup()
    socket.update({ type: 'task_runtime_event', event: runtime('AI_RUN_ERROR', 2) }); await flushPromises()
    await router.push('/settings'); await flushPromises()
    expect(awareness.runs).toEqual({}); expect(floats.items).toHaveLength(0)
  })
  it('desktop delivery nudges drain without a focus gate', async () => {
    const send = vi.fn().mockResolvedValue({ ok: true }); window.sddDesktop = { webhooks: { send } } as any
    const { socket } = await setup()
    const item = { id: 'delivery', lease_token: 'token', url: 'http://127.0.0.1:9000/pet', event_id: 'e1', body: { event_type: 'AI_RUN_FINISHED' } }
    vi.mocked(api.post).mockResolvedValueOnce({ data: { items: [item] } }).mockResolvedValue({ data: { items: [] } })
    socket.update({ type: 'task_webhook_ready' }); await flushPromises()
    expect(send).toHaveBeenCalledWith(item)
    expect(api.post).toHaveBeenCalledWith('/task-awareness/desktop-deliveries/ack', { id: 'delivery', lease_token: 'token', ok: true }, { timeout: 3000 })
  })
  it('leaving during initialization retains the accepted execution intent without updating the next task', async () => {
    const { router, floats } = await setup()
    let currentTask = { id: 't1', name: 'Task A' }
    let accept!: (value: any) => void
    vi.mocked(api.post).mockImplementationOnce(() => new Promise(resolve => { accept = resolve }))
    const apply = vi.fn()
    const actions = useTaskStartActions({
      getCurrentTask: () => currentTask, isTaskPreStart: { value: false }, isTaskProvisioning: { value: false },
      canStartTask: { value: true }, canManageTaskStatus: { value: true }, getWorkspaceId: () => 'w1',
      engineRunning: { value: false }, submissionsClear: vi.fn(), loadHistory: vi.fn(), refreshActiveJobs: vi.fn(),
      resetConversationView: vi.fn(), applyTaskSessionPayload: apply, patchTask: vi.fn(), specDrawerClose: vi.fn(), scrollIfNotAnchored: vi.fn(),
      skills: { taskRuntimeSkills: { value: [] }, taskRuntimeSkillsLoading: { value: false }, showTaskSkillsDrawer: { value: false }, loadTaskRuntimeSkills: vi.fn() },
      resolveActionError: () => 'failed',
    })
    const initializing = actions.initializeTaskWithReason('重新执行', '生成代码')
    await router.push('/settings'); currentTask = { id: 't2', name: 'Task B' }
    vi.mocked(api.get).mockResolvedValue({ data: { runs: [runtime()] } })
    accept({ data: { job: { id: 'j1' } } }); await initializing; await flushPromises()
    expect(floats.items[0].runId).toBe('j1'); expect(apply).not.toHaveBeenCalled()
  })
})
