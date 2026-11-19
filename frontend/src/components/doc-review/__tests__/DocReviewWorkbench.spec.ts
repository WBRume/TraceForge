import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { useProvisioningStore } from '@/stores/provisioning'
import type { AssetAiJob } from '@/composables/useAssetDiscussion'
import DocReviewWorkbench from '../DocReviewWorkbench.vue'

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/utils/api', () => ({ default: { get, post } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ token: 'test-token' }) }))
vi.mock('@/utils/ws', () => ({ buildBackendWsUrl: (path: string) => `ws://test${path}` }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))

afterEach(() => {
  vi.unstubAllGlobals()
  get.mockReset()
  post.mockReset()
  localStorage.clear()
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
    global: { plugins: [createPinia()] },
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

it('tracks one comparison request, then opens the saved result after minimizing and reloading', async () => {
  vi.stubGlobal('WebSocket', class { close() {} })
  const asset = { id: 'spec', task_id: 'task', workspace_id: 'workspace', asset_type: 'SPEC', name: 'spec.md' }
  const version = { id: 'version', asset_id: asset.id, version_no: 1 }
  const proposal = {
    id: 'ready-draft', base_version_id: version.id, status: 'draft',
    proposed_patch_json: { source_thread_ids: ['thread'], rewrite_status: 'ready', merged_blocks_ast: [{ id: 'blk-1' }] },
  }
  const thread = { id: 'thread', asset_id: asset.id, workspace_id: asset.workspace_id, status: 'resolved',
    version_id: version.id, block_id: 'blk-1', proposals: [], messages: [] }
  const capabilities = { can_view: true, can_comment: true, can_ai_reply: true, can_apply_resolution: true,
    can_manual_edit: false, inline_review_enabled: true, ai_available: true }
  const queued: AssetAiJob = {
    id: 'revision-job', task_id: asset.task_id, workspace_id: asset.workspace_id, asset_id: asset.id,
    thread_id: thread.id, creator_id: 'user', channel: 'ASSET_THREAD', queue_key: 'ASSET_THREAD:thread',
    status: 'PENDING', version: 1, progress: 0, created_at: '2026-11-19T00:00:00Z',
    context_json: { job_kind: 'RESOLUTION_REWRITE', context_version_id: version.id, source_thread_ids: [thread.id] },
  }
  let completed = false
  get.mockImplementation(async (url: string) => {
    if (url === '/document-revision-jobs') return { data: completed ? [
      { ...queued, status: 'SUCCESS', version: 2, progress: 100, result_json: { proposal_id: proposal.id } },
    ] : [] }
    if (url.endsWith('/spec-asset')) return { data: asset }
    if (url.endsWith('/document')) return { data: { asset, active_version: version, blocks: [], thread_markers: [], capabilities } }
    if (url.endsWith('/versions')) return { data: { items: [version] } }
    if (url.endsWith('/threads')) return { data: { items: [thread] } }
    if (url.endsWith('/threads/thread')) return { data: { ...thread, proposals: [proposal] } }
    if (url.endsWith('/ai-jobs')) return { data: { items: [] } }
    throw new Error(`Unexpected GET ${url}`)
  })
  post.mockResolvedValue({ data: queued })
  const pinia = createPinia()
  const store = useProvisioningStore(pinia)
  await store.restoreRevisionJobs('user')
  const props = { wsId: asset.workspace_id, taskId: asset.task_id }
  const original = shallowMount(DocReviewWorkbench, { props, global: { plugins: [pinia] } })
  try {
    await flushPromises()
    original.getComponent({ name: 'ThreadSidebar' }).vm.$emit('generate-proposal')
    original.getComponent({ name: 'ProposalDraftModal' }).vm.$emit('generate', [thread.id])
    await flushPromises()
    expect(post).toHaveBeenCalledWith('/workspaces/workspace/assets/spec/resolution/proposals', {
      thread_ids: [thread.id], context_version_id: version.id, overwrite_existing_draft: false,
    })
    const review = original.getComponent({ name: 'ResolutionDiffModal' })
    expect(review.props('job')).toMatchObject({ jobId: queued.id, status: 'PENDING' })
    review.vm.$emit('minimize')
    await flushPromises()
    expect(review.props('visible')).toBe(false)
    expect(store.getTrackedJob(queued.id)?.handedOver).toBe(true)
  } finally {
    original.unmount()
    await store.restoreRevisionJobs('')
  }

  completed = true
  const nextPinia = createPinia()
  const nextStore = useProvisioningStore(nextPinia)
  await nextStore.restoreRevisionJobs('user')
  expect(get).toHaveBeenCalledWith('/document-revision-jobs', { params: { job_ids: queued.id } })
  const reopened = shallowMount(DocReviewWorkbench, {
    props: { ...props, revisionJobId: queued.id }, global: { plugins: [nextPinia] },
  })
  try {
    await flushPromises()
    expect(reopened.getComponent({ name: 'ResolutionDiffModal' }).props('proposal')).toEqual(proposal)
    expect(reopened.emitted('revisionJobOpened')).toEqual([[queued.id]])
    expect(nextStore.getTrackedJob(queued.id)?.viewed).toBe(true)
    expect(post).toHaveBeenCalledTimes(1)
  } finally {
    reopened.unmount()
  }
})
