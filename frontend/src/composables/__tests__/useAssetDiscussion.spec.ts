import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { useAssetDiscussion, type AssetAiJob, type AssetThread, type AssetVersion } from '@/composables/useAssetDiscussion'
import { clearWsCursorMemory } from '@/utils/wsCursor'

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/utils/api', () => ({ default: apiMock }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ token: 'token' }) }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('@/utils/ws', () => ({ buildBackendWsUrl: (path: string) => `ws://test${path}` }))

class TestSocket {
  static OPEN = 1
  static instances: TestSocket[] = []
  readyState = 1
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  send = vi.fn()
  close = vi.fn(() => { this.readyState = 3 })
  readonly url: string
  constructor(url: string) { this.url = url; TestSocket.instances.push(this) }
  receive(data: unknown) { this.onmessage?.({ data: JSON.stringify(data) }) }
  serverClose() { this.readyState = 3; this.onclose?.() }
}

function deferred<T = any>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

const version = (assetId = 'A', id = `${assetId}-v1`): AssetVersion => ({
  id, asset_id: assetId, version_no: 1, created_by: 'user', created_at: '2026-11-10T00:00:00Z',
})
const thread = (assetId = 'A', wsId = 'ws-1', id = `${assetId}-thread`): AssetThread => ({
  id, asset_id: assetId, workspace_id: wsId, task_id: 'task', version_id: `${assetId}-v1`,
  block_id: 'block', status: 'open', creator_id: 'user', created_at: '2026-11-10T00:00:00Z',
  messages: [], proposals: [],
})
const job = (assetId = 'A', status: AssetAiJob['status'] = 'RUNNING', wsId = 'ws-1'): AssetAiJob => ({
  id: `${assetId}-job`, workspace_id: wsId, asset_id: assetId, thread_id: `${assetId}-thread`,
  channel: 'ASSET_THREAD', queue_key: 'queue', status, progress: 50, creator_id: 'user',
  created_at: '2026-11-10T00:00:00Z',
})
const document = (assetId = 'A', wsId = 'ws-1', versionId?: string) => ({
  asset: { id: assetId, workspace_id: wsId, task_id: 'task', asset_type: 'DOC', name: assetId, created_at: '' },
  active_version: version(assetId, versionId), blocks: [], thread_markers: [],
  capabilities: {
    can_view: true, can_comment: true, can_ai_reply: true, can_apply_resolution: true,
    can_manual_edit: true, inline_review_enabled: true, ai_available: true,
  },
})

type RequestConfig = { signal?: AbortSignal; params?: Record<string, unknown> }
function defaultGet(url: string, config?: RequestConfig) {
  const [, wsId, assetId] = url.match(/\/workspaces\/([^/]+)\/assets\/([^/]+)/) || []
  if (url.endsWith('/document')) return Promise.resolve({ data: document(assetId, wsId, config?.params?.version_id as string) })
  if (url.endsWith('/versions')) return Promise.resolve({ data: { items: [version(assetId)] } })
  if (url.endsWith('/threads') || url.endsWith('/ai-jobs')) return Promise.resolve({ data: { items: [] } })
  if (url.includes('/threads/')) return Promise.resolve({ data: thread(assetId, wsId) })
  throw new Error(`Unexpected GET ${url}`)
}

const wrappers: VueWrapper[] = []
function setup() {
  const wsId = ref('ws-1')
  const assetId = ref<string | null>('A')
  let model!: ReturnType<typeof useAssetDiscussion>
  const wrapper = mount(defineComponent({
    setup() { model = useAssetDiscussion({ wsId, assetId }); return () => null },
  }))
  wrappers.push(wrapper)
  return { model, wsId, assetId, wrapper }
}

describe('useAssetDiscussion resource ownership', () => {
  beforeEach(() => {
    vi.stubGlobal('WebSocket', TestSocket)
    TestSocket.instances = []
    window.sessionStorage.clear()
    window.sessionStorage.setItem('traceforge.ws.client_id', 'test-client')
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    clearWsCursorMemory()
    apiMock.get.mockImplementation(defaultGet)
  })

  afterEach(() => {
    for (const wrapper of wrappers.splice(0)) wrapper.unmount()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('loads the document, versions and discussions before opening one subscription', async () => {
    apiMock.get.mockImplementation((url, config) => url.endsWith('/threads')
      ? Promise.resolve({ data: { items: [thread()] } }) : defaultGet(url, config))
    const { model } = setup()
    await flushPromises()
    expect(model.documentData.value?.asset.id).toBe('A')
    expect(model.versions.value[0]?.id).toBe('A-v1')
    expect(model.threads.value[0]?.id).toBe('A-thread')
    expect(model.loadingDocument.value || model.loadingVersions.value || model.loadingThreads.value).toBe(false)
    expect(TestSocket.instances).toHaveLength(1)
    expect(vi.getTimerCount()).toBe(0)
    for (const [, config] of apiMock.get.mock.calls) expect(config.signal).toBeInstanceOf(AbortSignal)
  })

  it('aborts A and ignores its late document and initialization after switching to B', async () => {
    const old = deferred()
    apiMock.get.mockImplementation((url, config) => url.includes('/A/document') ? old.promise : defaultGet(url, config))
    const { model, assetId } = setup()
    const signal = apiMock.get.mock.calls[0]![1].signal as AbortSignal
    assetId.value = 'B'
    expect(signal.aborted).toBe(true)
    await flushPromises()
    const calls = apiMock.get.mock.calls.length
    old.resolve({ data: document('A') })
    await flushPromises()
    expect(model.documentData.value?.asset.id).toBe('B')
    expect(model.versions.value[0]?.asset_id).toBe('B')
    expect(apiMock.get).toHaveBeenCalledTimes(calls)
    expect(TestSocket.instances.map(item => item.url)).toEqual(['ws://test/ws/assets/B/discussion'])
  })

  it('does not let an old error or finally clear the current loading and error state', async () => {
    const old = deferred(), current = deferred()
    apiMock.get.mockImplementation((url) => url.includes('/A/') ? old.promise : current.promise)
    const { model, assetId } = setup()
    assetId.value = 'B'
    old.reject({ response: { data: { detail: 'A failed' } } })
    await flushPromises()
    expect(model.loadingDocument.value).toBe(true)
    expect(model.error.value).toBe('')
    expect(model.documentData.value).toBeNull()
    current.reject({ response: { data: { detail: 'B failed' } } })
    await flushPromises()
    expect(model.loadingDocument.value).toBe(false)
    expect(model.error.value).toBe('B failed')
  })

  it('distinguishes generations when the user switches A to B to A in one tick', async () => {
    const old = deferred()
    apiMock.get.mockImplementationOnce(() => old.promise)
    const { model, assetId } = setup()
    assetId.value = 'B'
    assetId.value = 'A'
    await flushPromises()
    old.resolve({ data: document('A', 'ws-1', 'obsolete') })
    await flushPromises()
    expect(model.activeVersionId.value).toBe('A-v1')
    expect(TestSocket.instances).toHaveLength(1)
  })

  it('invalidates all query types on a workspace change even if the asset ID is unchanged', async () => {
    const { model, wsId } = setup()
    await flushPromises()
    const versions = deferred(), threads = deferred(), detail = deferred(), jobs = deferred()
    apiMock.get.mockImplementation((url, config) => {
      if (url.includes('/ws-1/')) {
        if (url.endsWith('/versions')) return versions.promise
        if (url.endsWith('/threads')) return threads.promise
        if (url.endsWith('/ai-jobs')) return jobs.promise
        return detail.promise
      }
      return defaultGet(url, config)
    })
    const pending = [model.loadVersions(), model.loadThreads(), model.fetchThread('old'), model.loadThreadJobs('A-thread')]
    model.selectedThreadId.value = 'old'
    wsId.value = 'ws-2'
    await flushPromises()
    versions.resolve({ data: { items: [version('A', 'obsolete')] } })
    threads.resolve({ data: { items: [thread()] } })
    detail.resolve({ data: thread() })
    jobs.resolve({ data: { items: [job()] } })
    await Promise.all(pending)
    expect(model.documentData.value?.asset.workspace_id).toBe('ws-2')
    expect(model.versions.value[0]?.id).toBe('A-v1')
    expect(model.threads.value).toEqual([])
    expect(model.selectedThreadId.value).toBe('')
    expect(model.assistantJobMap.value).toEqual({})
    expect(vi.getTimerCount()).toBe(0)
    expect(TestSocket.instances[0]!.close).toHaveBeenCalledOnce()
  })

  it('keeps the latest version query and its loading state when document responses arrive out of order', async () => {
    const { model } = setup()
    await flushPromises()
    const old = deferred(), current = deferred()
    apiMock.get.mockImplementationOnce(() => old.promise).mockImplementationOnce(() => current.promise)
    const first = model.loadDocument('v2'), second = model.loadDocument('v3')
    old.resolve({ data: document('A', 'ws-1', 'v2') })
    expect(await first).toBeNull()
    expect(model.loadingDocument.value).toBe(true)
    current.resolve({ data: document('A', 'ws-1', 'v3') })
    await second
    expect(model.activeVersionId.value).toBe('v3')
    expect(model.loadingDocument.value).toBe(false)
  })

  it.each(['versions', 'threads', 'thread'] as const)('uses the newest %s response within one asset', async (kind) => {
    const { model } = setup()
    await flushPromises()
    const old = deferred(), current = deferred()
    apiMock.get.mockImplementationOnce(() => old.promise).mockImplementationOnce(() => current.promise)
    const load = () => kind === 'versions' ? model.loadVersions() : kind === 'threads' ? model.loadThreads() : model.fetchThread('same')
    const first = load(), second = load()
    const data = (label: string) => kind === 'versions' ? { items: [version('A', label)] }
      : kind === 'threads' ? { items: [thread('A', 'ws-1', label)] } : thread('A', 'ws-1', label)
    current.resolve({ data: data('new') })
    await second
    old.resolve({ data: data('old') })
    await first
    expect(kind === 'versions' ? model.versions.value[0]?.id : model.threads.value[0]?.id).toBe('new')
  })

  it('resets visible data immediately when the asset is cleared and blocks late initialization', async () => {
    const old = deferred()
    apiMock.get.mockImplementationOnce(() => old.promise)
    const { model, assetId } = setup()
    assetId.value = null
    expect(model.loadingDocument.value).toBe(false)
    expect(model.documentData.value).toBeNull()
    old.resolve({ data: document() })
    await flushPromises()
    expect(model.documentData.value).toBeNull()
    expect(TestSocket.instances).toHaveLength(0)
  })

  it('does not open a socket when the initial request finishes after unmount', async () => {
    const old = deferred()
    apiMock.get.mockImplementationOnce(() => old.promise)
    const { wrapper } = setup()
    const signal = apiMock.get.mock.calls[0]![1].signal as AbortSignal
    wrapper.unmount()
    expect(signal.aborted).toBe(true)
    old.resolve({ data: document() })
    await flushPromises()
    expect(TestSocket.instances).toHaveLength(0)
  })

  const mutations = [
    ['createThread', (m: ReturnType<typeof useAssetDiscussion>) => m.createThread({ block_id: 'block', body: 'hello' }), () => thread()],
    ['sendThreadMessage', (m: ReturnType<typeof useAssetDiscussion>) => m.sendThreadMessage('A-thread', 'hello'), () => ({ id: 'message', thread_id: 'A-thread' })],
    ['askAi', (m: ReturnType<typeof useAssetDiscussion>) => m.askAi('A-thread'), () => job()],
    ['createResolutionProposal', (m: ReturnType<typeof useAssetDiscussion>) => m.createResolutionProposal('A-thread'), () => job()],
    ['rewriteResolutionProposal', (m: ReturnType<typeof useAssetDiscussion>) => m.rewriteResolutionProposal('A-thread', 'proposal', 'new'), () => job()],
    ['applyResolutionProposal', (m: ReturnType<typeof useAssetDiscussion>) => m.applyResolutionProposal('A-thread', 'proposal', { finalBlockAst: {} }), () => version()],
    ['manualEditBlock', (m: ReturnType<typeof useAssetDiscussion>) => m.manualEditBlock('block', 'new'), () => version()],
    ['cancelAiJob', (m: ReturnType<typeof useAssetDiscussion>) => m.cancelAiJob('job'), () => job('A', 'CANCELLED')],
    ['updateThreadCloseHint', (m: ReturnType<typeof useAssetDiscussion>) => m.updateThreadCloseHint('A-thread', 'reset_pending'), () => thread()],
    ['updateThreadState', (m: ReturnType<typeof useAssetDiscussion>) => m.updateThreadState('A-thread', 'closed'), () => thread()],
  ] as const

  it.each(mutations)('ignores a late %s result and its follow-up reads', async (_name, invoke, response) => {
    const { model, assetId } = setup()
    await flushPromises()
    const old = deferred()
    apiMock.post.mockReturnValueOnce(old.promise)
    const pending = invoke(model)
    const signal = apiMock.post.mock.calls[0]![2].signal as AbortSignal
    assetId.value = 'B'
    await flushPromises()
    const calls = apiMock.get.mock.calls.length
    expect(signal.aborted).toBe(true)
    old.resolve({ data: response() })
    expect(await pending).toBeNull()
    expect(model.documentData.value?.asset.id).toBe('B')
    expect(model.threads.value).toEqual([])
    expect(model.assistantJobMap.value).toEqual({})
    expect(model.proposalJobMap.value).toEqual({})
    expect(apiMock.get).toHaveBeenCalledTimes(calls)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('suppresses stale mutation failures while preserving errors from current operations', async () => {
    const { model, assetId } = setup()
    await flushPromises()
    const old = deferred()
    apiMock.post.mockReturnValueOnce(old.promise)
    const pending = model.askAi('A-thread')
    assetId.value = 'B'
    old.reject(new Error('old failure'))
    expect(await pending).toBeNull()
    apiMock.post.mockRejectedValueOnce(new Error('current failure'))
    await expect(model.askAi('B-thread')).rejects.toThrow('current failure')
  })

  it('keeps a single poll alive across repeated active job responses and refreshes the finished thread', async () => {
    const { model } = setup()
    await flushPromises()
    let active = true
    apiMock.get.mockImplementation((url, config) => url.endsWith('/ai-jobs')
      ? Promise.resolve({ data: { items: active ? [job()] : [] } }) : defaultGet(url, config))
    await model.loadThreadJobs('A-thread')
    expect(vi.getTimerCount()).toBe(1)
    await vi.advanceTimersByTimeAsync(1800)
    expect(vi.getTimerCount()).toBe(1)
    await vi.advanceTimersByTimeAsync(1800)
    expect(vi.getTimerCount()).toBe(1)
    active = false
    await vi.advanceTimersByTimeAsync(1800)
    expect(model.assistantJobMap.value).toEqual({})
    expect(model.threads.value[0]?.id).toBe('A-thread')
    expect(vi.getTimerCount()).toBe(0)
  })

  it.each(['switch', 'unmount', 'terminal'] as const)('does not rearm an in-flight poll after %s', async (action) => {
    const { model, assetId, wrapper } = setup()
    await flushPromises()
    apiMock.get.mockResolvedValueOnce({ data: { items: [job()] } })
    await model.loadThreadJobs('A-thread')
    const old = deferred()
    apiMock.get.mockReturnValueOnce(old.promise)
    await vi.advanceTimersByTimeAsync(1800)
    const signal = apiMock.get.mock.calls.at(-1)![1].signal as AbortSignal
    if (action === 'switch') assetId.value = 'B'
    if (action === 'unmount') wrapper.unmount()
    if (action === 'terminal') TestSocket.instances[0]!.receive({ type: 'ai_job_done', job: job('A', 'SUCCESS') })
    await flushPromises()
    expect(signal.aborted).toBe(true)
    old.resolve({ data: { items: [job()] } })
    await flushPromises()
    expect(vi.getTimerCount()).toBe(0)
    expect(model.assistantJobMap.value['A-thread']?.status).toBe(action === 'terminal' ? 'SUCCESS' : undefined)
  })

  it('retries transient polling errors but stops after cleanup while the retry is in flight', async () => {
    const { model, wrapper } = setup()
    await flushPromises()
    apiMock.get.mockResolvedValueOnce({ data: { items: [job()] } })
    await model.loadThreadJobs('A-thread')
    apiMock.get.mockRejectedValueOnce(new Error('temporary'))
    await vi.advanceTimersByTimeAsync(1800)
    expect(vi.getTimerCount()).toBe(1)
    const old = deferred()
    apiMock.get.mockReturnValueOnce(old.promise)
    await vi.advanceTimersByTimeAsync(1800)
    wrapper.unmount()
    old.reject(new Error('late failure'))
    await flushPromises()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('rejects callbacks and queued frames from the old socket after switching assets', async () => {
    const { model, assetId } = setup()
    await flushPromises()
    const old = TestSocket.instances[0]!
    const lateOpen = old.onopen!, lateClose = old.onclose!, lateMessage = old.onmessage!
    old.receive({ type: 'presence', online_users: ['old'] })
    expect(model.onlineUsers.value).toEqual(['old'])
    assetId.value = 'B'
    await flushPromises()
    lateOpen()
    lateMessage({ data: JSON.stringify({ type: 'presence', online_users: ['obsolete'] }) })
    lateClose()
    expect(model.wsConnected.value).toBe(false)
    expect(model.onlineUsers.value).toEqual([])
    expect(vi.getTimerCount()).toBe(0)
    TestSocket.instances[1]!.onopen!()
    TestSocket.instances[1]!.receive({ type: 'presence', online_users: ['current'] })
    expect(model.wsConnected.value).toBe(true)
    expect(model.onlineUsers.value).toEqual(['current'])
  })

  it('aborts HTTP started by an old WebSocket event and discards its queued events', async () => {
    const { model, assetId } = setup()
    await flushPromises()
    const old = deferred()
    apiMock.get.mockReturnValueOnce(old.promise)
    const socket = TestSocket.instances[0]!
    socket.receive({ type: 'message_created', thread_id: 'A-thread', message: { id: 'message', role: 'ai' } })
    socket.receive({ type: 'presence', online_users: ['queued-old'] })
    const signal = apiMock.get.mock.calls.at(-1)![1].signal as AbortSignal
    assetId.value = 'B'
    await flushPromises()
    expect(signal.aborted).toBe(true)
    old.resolve({ data: thread() })
    await flushPromises()
    expect(model.threads.value).toEqual([])
    expect(model.onlineUsers.value).toEqual([])
    expect(vi.getTimerCount()).toBe(0)
  })

  it('cancels a resync snapshot on switch and sends no acknowledgement from the old subscription', async () => {
    const { model, assetId } = setup()
    await flushPromises()
    const old = deferred()
    apiMock.get.mockReturnValueOnce(old.promise)
    const socket = TestSocket.instances[0]!
    socket.receive({ type: 'resync_required', epoch: 'e1', barrier_sequence: 5 })
    const signal = apiMock.get.mock.calls.at(-1)![1].signal as AbortSignal
    assetId.value = 'B'
    await flushPromises()
    old.resolve({ data: document() })
    await flushPromises()
    expect(signal.aborted).toBe(true)
    expect(socket.send).not.toHaveBeenCalled()
    expect(model.documentData.value?.asset.id).toBe('B')
    expect(TestSocket.instances).toHaveLength(2)
  })

  it('clears reconnect timers on switching and unmounting', async () => {
    const { assetId, wrapper } = setup()
    await flushPromises()
    TestSocket.instances[0]!.serverClose()
    expect(vi.getTimerCount()).toBe(1)
    assetId.value = 'B'
    expect(vi.getTimerCount()).toBe(0)
    await flushPromises()
    TestSocket.instances[1]!.serverClose()
    wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
    await vi.advanceTimersByTimeAsync(60000)
    expect(TestSocket.instances).toHaveLength(2)
  })
})
