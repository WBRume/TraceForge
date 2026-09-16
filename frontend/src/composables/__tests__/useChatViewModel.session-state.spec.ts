import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { useChatViewModel } from '@/composables/useChatViewModel'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
  defaults: { baseURL: 'http://localhost/api' },
}))

const routeMock = vi.hoisted(() => ({
  params: { wsId: 'w', taskId: '' } as Record<string, string>,
  query: {} as Record<string, string>,
  path: '/workspaces/w/chat',
}))

const routerMock = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }))

vi.mock('@/utils/api', () => ({ default: apiMock }))
vi.mock('vue-router', () => ({ useRoute: () => routeMock, useRouter: () => routerMock }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    token: 'test-token',
    user: { id: 'u1', display_name: 'Tester' },
    fetchCurrentUser: vi.fn().mockResolvedValue(undefined),
    logout: vi.fn(),
  }),
}))
vi.mock('@/stores/provisioning', () => ({
  useProvisioningStore: () => ({ taskListRefreshToken: 0, startWatching: vi.fn() }),
}))

class FakeWebSocket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3
  static instances: FakeWebSocket[] = []

  readyState = FakeWebSocket.CONNECTING
  onopen: ((event: any) => void) | null = null
  onmessage: ((event: any) => void) | null = null
  onerror: ((event: any) => void) | null = null
  onclose: ((event: any) => void) | null = null
  send = vi.fn()
  close = vi.fn(() => { this.readyState = FakeWebSocket.CLOSED })
  url: string

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  open() {
    this.readyState = FakeWebSocket.OPEN
    this.onopen?.({})
  }

  receive(frame: Record<string, any>) {
    this.onmessage?.({ data: JSON.stringify(frame) })
  }
}

Object.defineProperty(globalThis, 'WebSocket', {
  writable: true,
  configurable: true,
  value: FakeWebSocket,
})

const task = (id: string, skillIds: string[] = []) => ({
  id,
  name: id,
  status: 'CODING',
  task_type: 'DEVELOPMENT',
  skill_ids: skillIds,
  total_cost_usd: 0,
  total_duration_ms: 0,
  spec_doc_path: '',
})

const resolveByUrl = (target: string) => {
  if (target.endsWith('/tasks')) return Promise.resolve({ data: { items: [], total: 0, page: 1, page_size: 20 } })
  if (target.includes('/permissions/me')) return Promise.resolve({ data: { permissions: {} } })
  if (target.endsWith('/history')) return Promise.resolve({ data: { messages: [], logs: [], has_more: false } })
  if (target.includes('/session-state')) return Promise.resolve({
    data: { task_id: 't1', session_generation: 1, session_revision: 0, receipts: [], jobs: [], messages: [] },
  })
  if (target.includes('/ai-jobs')) return Promise.resolve({ data: { items: [] } })
  if (target.includes('/pre-input/active')) return Promise.resolve({ data: { pre_input: null } })
  if (target.endsWith('/skills/runtime')) return Promise.resolve({ data: { items: [] } })
  if (target.includes('/skills/runtime/events')) return Promise.resolve({ data: { items: [] } })
  return Promise.resolve({ data: {} })
}

const countCalls = (fragment: string) => apiMock.get.mock.calls
  .filter(([url]) => String(url).includes(fragment)).length

const lastSocket = () => FakeWebSocket.instances[FakeWebSocket.instances.length - 1]

let wrapper: VueWrapper | null = null
let vm: ReturnType<typeof useChatViewModel>

const mountViewModel = async () => {
  wrapper = mount(defineComponent({
    setup() {
      vm = useChatViewModel()
      return () => null
    },
  }))
  await flushPromises()
}

const readySocket = async (frame: Record<string, any> = { type: 'resume_ok', epoch: 'e', to_sequence: 0, high_watermark: 0 }) => {
  const socket = lastSocket()
  socket.open()
  socket.receive(frame)
  await flushPromises()
  return socket
}

describe('useChatViewModel session state single flight', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    apiMock.put.mockReset()
    apiMock.delete.mockReset()
    apiMock.get.mockImplementation((url: string) => resolveByUrl(String(url)))
    FakeWebSocket.instances = []
    routeMock.params.taskId = ''
    routeMock.query = {}
    wrapper = null
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
  })

  it('loads history, session-state and pre-input once, only after the first subscription is ready', async () => {
    await mountViewModel()
    await vm.selectTask(task('t1', ['s1', 's2']))
    const socket = lastSocket()
    socket.open()
    expect(countCalls('/ai-jobs')).toBe(0)
    expect(countCalls('/pre-input/active')).toBe(0)
    expect(countCalls('/history')).toBe(0)
    expect(countCalls('/session-state')).toBe(0)

    socket.receive({ type: 'resume_ok', epoch: 'e', to_sequence: 0, high_watermark: 0 })
    await flushPromises()
    expect(countCalls('/history')).toBe(1)
    expect(countCalls('/session-state')).toBe(1)
    expect(countCalls('/pre-input/active')).toBe(1)
    // jobs now ride on the session-state snapshot; no separate ai-jobs request
    expect(countCalls('/ai-jobs')).toBe(0)

    // 重复就绪事件（reconnect 后同代次）不再重复请求快照
    socket.receive({ type: 'resume_ok', epoch: 'e', to_sequence: 1, high_watermark: 1 })
    await flushPromises()
    expect(countCalls('/history')).toBe(1)
    expect(countCalls('/session-state')).toBe(1)
    expect(countCalls('/pre-input/active')).toBe(1)
  })

  it('restores the snapshot through the resync barrier without a second history request', async () => {
    await mountViewModel()
    await vm.selectTask(task('t1'))
    const socket = await readySocket({
      type: 'resync_required', epoch: 'e', barrier_sequence: 0, high_watermark: 0, reason: 'initial_sync',
    })
    expect(countCalls('/history')).toBe(1)
    expect(countCalls('/session-state')).toBe(1)
    expect(countCalls('/pre-input/active')).toBe(1)

    socket.receive({ type: 'resync_ok', epoch: 'e', to_sequence: 0, high_watermark: 0 })
    await flushPromises()
    expect(countCalls('/history')).toBe(1)
    expect(countCalls('/session-state')).toBe(1)
    expect(countCalls('/pre-input/active')).toBe(1)
  })

  it('falls back to HTTP when the first subscription is unavailable', async () => {
    await mountViewModel()
    await vm.selectTask(task('t1'))
    const socket = lastSocket()
    socket.open()
    socket.onclose?.({ code: 1006 })
    await flushPromises()
    expect(countCalls('/history')).toBe(1)
    expect(countCalls('/session-state')).toBe(1)
    expect(countCalls('/pre-input/active')).toBe(1)
  })

  it('cancels the previous task snapshot when switching sessions', async () => {
    const pending = new Promise(() => {})
    let t1Signal: AbortSignal | undefined
    apiMock.get.mockImplementation((url: string, config?: { signal?: AbortSignal }) => {
      const target = String(url)
      if (target.includes('/tasks/t1/session-state')) {
        t1Signal = config?.signal
        return pending as unknown as Promise<{ data: unknown }>
      }
      return resolveByUrl(target)
    })

    await mountViewModel()
    await vm.selectTask(task('t1'))
    await readySocket()

    routeMock.params.taskId = 't2'
    await vm.selectTask(task('t2'))
    expect(t1Signal?.aborted).toBe(true)

    await readySocket()
    expect(countCalls('/session-state')).toBe(2)
    expect(apiMock.get.mock.calls.filter(([url]) => String(url).includes('/tasks/t1/session-state'))).toHaveLength(1)
  })

  it('defers runtime skills until the drawer opens and shows the summary count meanwhile', async () => {
    await mountViewModel()
    await vm.selectTask(task('t1', ['s1', 's2']))
    await readySocket()

    expect(countCalls('/skills/runtime')).toBe(0)
    expect(vm.taskRuntimeSkillCount.value).toBe(2)

    await vm.openTaskSkillsDrawer()
    await flushPromises()
    expect(apiMock.get.mock.calls.filter(([url]) => String(url).endsWith('/skills/runtime'))).toHaveLength(1)
    expect(apiMock.get.mock.calls.filter(([url]) => String(url).endsWith('/skills/runtime/events'))).toHaveLength(1)
  })

  it('applies submission events directly without a REST requery', async () => {
    await mountViewModel()
    await vm.selectTask(task('t1'))
    const socket = await readySocket()
    const before = countCalls('/session-state')

    socket.receive({ type: 'event', room: 'task:t1', epoch: 'e', sequence: 1, event_id: 'ev-1',
      event_type: 'chat_submission_update', payload: {
        task_id: 't1', session_generation: 1, session_revision: 1, event_id: 'ev-1',
        receipt: { id: 'r1', task_id: 't1', client_message_id: 'c1', content: 'hello', status: 'PREPARING', version: 1 },
      } })
    await flushPromises()
    expect(vm.messages.value.some(item => String(item.client_message_id || '') === 'c1')).toBe(true)
    expect(vm.engineRunning.value).toBe(true)

    socket.receive({ type: 'event', room: 'task:t1', epoch: 'e', sequence: 2, event_id: 'ev-2',
      event_type: 'chat_submission_update', payload: {
        task_id: 't1', session_generation: 1, session_revision: 1, event_id: 'ev-2',
        receipt: { id: 'r1', task_id: 't1', client_message_id: 'c1', status: 'EXECUTING', version: 2,
          chat_message_id: 'm1', ai_job_id: 'j1' },
        message: { id: 'm1', task_id: 't1', role: 'user', content: 'hello', message_type: 'text',
          client_message_id: 'c1', session_generation: 1, session_turn_id: 'turn1' },
        job: { id: 'j1', task_id: 't1', status: 'PENDING', progress: 0 },
      } })
    await flushPromises()
    expect(vm.messages.value.some(item => String(item.id || '') === 'm1')).toBe(true)
    expect(vm.activeChatJobs.value.j1?.id).toBe('j1')

    // 事件路径零 REST 反查
    expect(countCalls('/session-state')).toBe(before)
    expect(countCalls('/history')).toBe(1)
    expect(countCalls('/ai-jobs')).toBe(0)
  })

  it('does not poll submissions on a timer while a receipt is executing', async () => {
    vi.useFakeTimers()
    try {
      await mountViewModel()
      await vm.selectTask(task('t1'))
      await readySocket()
      const baseline = apiMock.get.mock.calls.length
      await vi.advanceTimersByTimeAsync(10_000)
      expect(apiMock.get.mock.calls.length).toBe(baseline)
    } finally {
      vi.useRealTimers()
    }
  })
})
