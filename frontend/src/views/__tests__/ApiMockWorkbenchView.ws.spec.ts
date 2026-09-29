import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'
import ApiMockWorkbenchView from '../ApiMockWorkbenchView.vue'
import { clearWsCursorMemory } from '@/utils/wsCursor'

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), message: vi.fn() }))
vi.mock('@/utils/api', () => ({ default: mocks }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { wsId: 'ws' } }) }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('element-plus', () => ({ ElMessage: mocks.message }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ token: 'test', user: { id: 'user' } }) }))
vi.mock('@/utils/ws', () => ({ buildBackendWsUrl: (path: string) => `ws://localhost${path}` }))
vi.mock('@guolao/vue-monaco-editor', () => ({ VueMonacoEditor: { template: '<div />' } }))
vi.mock('monaco-editor', () => ({}))

class Socket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSED = 3
  static instances: Socket[] = []
  readyState = Socket.CONNECTING
  sequence = 0
  onopen?: () => void
  onclose?: () => void
  onmessage?: (event: { data: string }) => void
  send = vi.fn()
  close = vi.fn(() => { this.readyState = Socket.CLOSED; this.onclose?.() })
  url: string
  constructor(url: string) { this.url = url; Socket.instances.push(this) }
  open() { this.readyState = Socket.OPEN; this.onopen?.() }
  receive(frame: unknown) { this.onmessage?.({ data: JSON.stringify(frame) }) }
}

const job = (status = 'RUNNING', job_type = 'SYNC_TASK_SOURCE') => ({
  id: 'job', job_type, status, progress: 50, result_json: { target_endpoint_id: 'endpoint' },
})
let activeJobs: ReturnType<typeof job>[]
let snapshot: ReturnType<typeof job>
let wrapper: VueWrapper | undefined

const start = async () => {
  wrapper = shallowMount(ApiMockWorkbenchView, { global: { mocks: { $t: (key: string) => key } } })
  await flushPromises()
  wrapper.findComponent({ name: 'ApiMockTaskPickerPanel' }).vm.$emit('update:model-value', 'task')
  await flushPromises()
  const socket = Socket.instances[0]!
  socket.open()
  return socket
}
const resync = async (socket: Socket) => {
  socket.receive({ type: 'resync_required', reason: 'initial_sync', epoch: 'epoch', barrier_sequence: 0 })
  await flushPromises()
}
const emitJob = async (socket: Socket, value: ReturnType<typeof job>) => {
  socket.receive({ type: 'event', epoch: 'epoch', sequence: ++socket.sequence,
    event_id: `event-${socket.sequence}`, payload: { type: 'job_done', job: value } })
  await flushPromises()
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('WebSocket', Socket)
  Socket.instances = []
  sessionStorage.clear()
  clearWsCursorMemory()
  activeJobs = []
  snapshot = job()
  mocks.post.mockResolvedValue({ data: { job_id: 'job' } })
  mocks.get.mockImplementation(async (path: string) => {
    if (path.endsWith('/permissions/me')) return { data: { permissions: { view_api_mock: true, manage_api_mock: true } } }
    if (path.endsWith('/tasks')) return { data: { items: [{ id: 'task', name: 'Task' }, { id: 'other', name: 'Other' }] } }
    if (path.endsWith('/jobs/job')) return { data: snapshot }
    if (path.endsWith('/jobs')) return { data: { items: activeJobs } }
    if (path.endsWith('/endpoints')) return { data: { items: [{ id: 'endpoint', method: 'GET', path: '/test' }] } }
    if (/\/projects\/[^/]+$/.test(path)) return { data: { id: path.endsWith('/other') ? 'other-project' : 'project' } }
    return { data: { items: [] } }
  })
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('API Mock websocket lifecycle', () => {
  it('acknowledges initial resync on the same socket and stays idle without polling', async () => {
    const socket = await start()
    await resync(socket)
    expect(Socket.instances).toHaveLength(1)
    expect(socket.close).not.toHaveBeenCalled()
    expect(socket.send).toHaveBeenCalledWith(JSON.stringify({ type: 'resync_complete', epoch: 'epoch', barrier_sequence: 0 }))
    const requests = mocks.get.mock.calls.length
    await vi.advanceTimersByTimeAsync(30_000)
    expect(mocks.get).toHaveBeenCalledTimes(requests)
  })

  it.each(['sync', 'import-swagger'])('finishes %s from WS without job polling or reconnecting', async (event) => {
    const socket = await start()
    await resync(socket)
    wrapper!.findComponent({ name: 'ApiMockConfigDrawer' }).vm.$emit(event, { raw_content: '{}' })
    await flushPromises()
    const requests = mocks.get.mock.calls.length
    await vi.advanceTimersByTimeAsync(10_000)
    expect(mocks.get).toHaveBeenCalledTimes(requests)
    await emitJob(socket, job('SUCCESS'))
    expect(wrapper!.findComponent({ name: 'ApiMockConfigDrawer' }).props(event === 'sync' ? 'syncBusy' : 'importBusy')).toBe(false)
    expect(mocks.message).toHaveBeenCalledWith(expect.objectContaining({ message: 'api_mock.job_success' }))
    expect(Socket.instances).toHaveLength(1)
    expect(socket.close).not.toHaveBeenCalled()
  })

  it('keeps completion received before the submit response', async () => {
    const socket = await start()
    let resolvePost!: (value: unknown) => void
    mocks.post.mockImplementationOnce(() => new Promise((resolve) => { resolvePost = resolve }))
    wrapper!.findComponent({ name: 'ApiMockConfigDrawer' }).vm.$emit('sync')
    await emitJob(socket, job('SUCCESS'))
    resolvePost({ data: { job_id: 'job' } })
    await flushPromises()
    expect(wrapper!.findComponent({ name: 'ApiMockConfigDrawer' }).props('syncBusy')).toBe(false)
    expect(mocks.message).toHaveBeenCalledWith(expect.objectContaining({ message: 'api_mock.job_success' }))
    expect(mocks.get.mock.calls.filter(([path]) => path.endsWith('/jobs/job'))).toHaveLength(0)
  })

  it('recovers completion omitted by the active-only list after reconnect', async () => {
    const socket = await start()
    wrapper!.findComponent({ name: 'ApiMockConfigDrawer' }).vm.$emit('sync')
    await flushPromises()
    socket.close()
    snapshot = job('SUCCESS')
    await vi.advanceTimersByTimeAsync(5_000)
    const reconnected = Socket.instances[1]!
    reconnected.open()
    await resync(reconnected)
    expect(wrapper!.findComponent({ name: 'ApiMockConfigDrawer' }).props('syncBusy')).toBe(false)
    expect(reconnected.send).toHaveBeenCalled()
    expect(Socket.instances).toHaveLength(2)
  })

  it('updates auto Mock completion and cases via WS without timers', async () => {
    activeJobs = [job('RUNNING', 'AUTO_GENERATE_MOCK_CASES')]
    const socket = await start()
    wrapper!.findComponent({ name: 'ApiMockEndpointCatalog' }).vm.$emit('select', 'endpoint')
    await flushPromises()
    const requests = mocks.get.mock.calls.length
    await vi.advanceTimersByTimeAsync(10_000)
    expect(mocks.get).toHaveBeenCalledTimes(requests)
    await emitJob(socket, job('SUCCESS', 'AUTO_GENERATE_MOCK_CASES'))
    expect(wrapper!.findComponent({ name: 'ApiMockEndpointWorkspace' }).props('autoMockJob')).toBeNull()
    expect(mocks.get).toHaveBeenLastCalledWith('/workspaces/ws/api-mock/endpoints/endpoint/mock-cases')
    const completedRequests = mocks.get.mock.calls.length
    await emitJob(socket, job('SUCCESS', 'AUTO_GENERATE_MOCK_CASES'))
    expect(mocks.get).toHaveBeenCalledTimes(completedRequests)
  })

  it('cleans up a pending wait when leaving the page', async () => {
    const socket = await start()
    wrapper!.findComponent({ name: 'ApiMockConfigDrawer' }).vm.$emit('sync')
    await flushPromises()
    wrapper!.unmount()
    wrapper = undefined
    const requests = mocks.get.mock.calls.length
    await vi.advanceTimersByTimeAsync(7 * 60_000)
    expect(mocks.get).toHaveBeenCalledTimes(requests)
    expect(Socket.instances).toHaveLength(1)
    expect(socket.close).toHaveBeenCalledOnce()
    expect(mocks.message).not.toHaveBeenCalledWith(expect.objectContaining({ message: 'api_mock.job_timeout' }))
  })

  it('settles a failed job from WS', async () => {
    const socket = await start()
    wrapper!.findComponent({ name: 'ApiMockConfigDrawer' }).vm.$emit('sync')
    await flushPromises()
    await emitJob(socket, job('FAILED'))
    expect(wrapper!.findComponent({ name: 'ApiMockConfigDrawer' }).props('syncBusy')).toBe(false)
    expect(mocks.message).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' }))
    const requests = mocks.get.mock.calls.length
    await vi.advanceTimersByTimeAsync(10_000)
    expect(mocks.get).toHaveBeenCalledTimes(requests)
  })

  it('ignores the old task submit response after switching tasks', async () => {
    const socket = await start()
    let resolvePost!: (value: unknown) => void
    mocks.post.mockImplementationOnce(() => new Promise((resolve) => { resolvePost = resolve }))
    wrapper!.findComponent({ name: 'ApiMockConfigDrawer' }).vm.$emit('sync')
    await wrapper!.find('.task-side-toggle').trigger('click')
    wrapper!.findComponent({ name: 'ApiMockTaskPickerPanel' }).vm.$emit('update:model-value', 'other')
    await flushPromises()
    const requests = mocks.get.mock.calls.length
    resolvePost({ data: { job_id: 'job' } })
    await flushPromises()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(mocks.get).toHaveBeenCalledTimes(requests)
    expect(socket.close).toHaveBeenCalledOnce()
    expect(Socket.instances).toHaveLength(2)
    expect(Socket.instances[1]!.url).toContain('other-project')
    expect(wrapper!.findComponent({ name: 'ApiMockConfigDrawer' }).props('activeJob')).toBeNull()
  })

  it('does not regress a completed auto Mock job when its initial snapshot arrives late', async () => {
    const socket = await start()
    wrapper!.findComponent({ name: 'ApiMockEndpointCatalog' }).vm.$emit('select', 'endpoint')
    await flushPromises()
    let resolveSnapshot!: (value: unknown) => void
    const originalGet = mocks.get.getMockImplementation()!
    mocks.get.mockImplementation((path: string) => path.endsWith('/jobs/job')
      ? new Promise((resolve) => { resolveSnapshot = resolve }) : originalGet(path))
    wrapper!.findComponent({ name: 'ApiMockEndpointWorkspace' }).vm.$emit('start-auto-mock')
    await flushPromises()
    await emitJob(socket, job('SUCCESS', 'AUTO_GENERATE_MOCK_CASES'))
    resolveSnapshot({ data: job('RUNNING', 'AUTO_GENERATE_MOCK_CASES') })
    await flushPromises()
    expect(wrapper!.findComponent({ name: 'ApiMockEndpointWorkspace' }).props('autoMockJob')).toBeNull()
    const requests = mocks.get.mock.calls.length
    await vi.advanceTimersByTimeAsync(10_000)
    expect(mocks.get).toHaveBeenCalledTimes(requests)
  })
})
