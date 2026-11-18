import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import DocReviewWorkbench from '../DocReviewWorkbench.vue'

const { get } = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/utils/api', () => ({ default: { get } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ token: 'test-token' }) }))
vi.mock('@/utils/ws', () => ({ buildBackendWsUrl: (path: string) => `ws://test${path}` }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))

afterEach(() => {
  vi.unstubAllGlobals()
  get.mockReset()
})

it('loads versions and existing discussions when the baseline becomes ready during the initial document load', async () => {
  vi.stubGlobal('WebSocket', class { close() {} })
  const asset = { id: 'spec', task_id: 'task', workspace_id: 'workspace', asset_type: 'SPEC', name: 'spec.md' }
  const version = { id: 'version-2', asset_id: asset.id, version_no: 2 }
  const thread = { id: 'existing-thread', asset_id: asset.id, workspace_id: asset.workspace_id, messages: [] }
  const capabilities = {
    can_view: true, can_comment: true, can_ai_reply: true, can_apply_resolution: false,
    can_manual_edit: false, inline_review_enabled: true, ai_available: true,
  }
  const payload = { data: { asset, active_version: version, blocks: [], thread_markers: [], capabilities } }
  let finishInitialDocument!: (data: typeof payload) => void
  const initialDocument = new Promise<typeof payload>(resolve => { finishInitialDocument = resolve })
  let documentRequests = 0

  get.mockImplementation(async (url: string) => {
    if (url.endsWith('/spec-asset')) return { data: asset }
    if (url.endsWith('/document')) return ++documentRequests === 1 ? initialDocument : payload
    if (url.endsWith('/versions')) return { data: { items: [version] } }
    if (url.endsWith('/threads')) return { data: { items: [thread] } }
    if (url.endsWith('/ai-jobs')) return { data: { items: [] } }
    throw new Error(`Unexpected GET ${url}`)
  })

  const wrapper = shallowMount(DocReviewWorkbench, {
    props: {
      wsId: 'workspace',
      taskId: 'task',
      bootstrapStatus: { status: 'RUNNING', progress: 75 },
    },
  })
  try {
    await flushPromises()
    expect(documentRequests).toBe(1)
    await wrapper.setProps({ bootstrapStatus: { status: 'READY', progress: 100 } })
    await flushPromises()
    finishInitialDocument(payload)
    await flushPromises()

    const switcher = wrapper.getComponent({ name: 'VersionSwitcher' })
    expect(switcher.props('modelValue')).toBe(version.id)
    expect(switcher.props('versions')).toEqual([version])
    expect(wrapper.getComponent({ name: 'ThreadSidebar' }).props('threads')).toEqual([thread])
  } finally {
    wrapper.unmount()
  }
})
