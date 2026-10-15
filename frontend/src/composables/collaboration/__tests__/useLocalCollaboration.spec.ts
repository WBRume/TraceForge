import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, nextTick, reactive, shallowRef, watch } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import zh from '@/locales/zh.json'
import type { CollaborationManifest, CollaborationState, LocalCollaborationStatus } from '@/types/collaboration'

const mocks = vi.hoisted(() => ({ desktop: true, changed: vi.fn(), unsubscribe: vi.fn(), api: { reviewBaseline: vi.fn(), review: vi.fn(), state: vi.fn(), post: vi.fn(), snapshot: vi.fn(), object: vi.fn(), upload: vi.fn() }, native: vi.fn(), mapping: vi.fn(), setMapping: vi.fn(), directory: vi.fn(), validate: vi.fn(), remotes: vi.fn(), open: vi.fn(), auth: { user: null as { id: string } | null } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => mocks.auth }))
vi.mock('@/utils/runtime', () => ({ getSddDesktop: () => mocks.desktop ? ({ collaboration: { execute: mocks.native, onChanged: mocks.changed }, config: { getRepoMapping: mocks.mapping, setRepoMapping: mocks.setMapping }, git: { selectDirectory: mocks.directory, validateGitRepo: mocks.validate, getFetchRemotes: mocks.remotes }, system: { openPath: mocks.open } }) : null }))
vi.mock('@/services/collaborationApi', () => ({ collaborationApi: () => mocks.api, base64Bytes: (content: string) => Uint8Array.from(atob(content), char => char.charCodeAt(0)), bytesBase64: () => 'AQ==' }))
vi.mock('@/components/collaboration/CodeComparison.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/utils/api', () => ({ default: { get:vi.fn().mockResolvedValue({ data:{ repositories:[], plan:null } }) } }))
import { useLocalCollaboration, type LocalCollaboration } from '../useLocalCollaboration'
import { readRepoPreferences, saveRepoPreferences } from '@/composables/localRepoPreferences'
import CollaborationActions from '@/components/collaboration/CollaborationActions.vue'
import LocalCollaborationPanel from '@/components/collaboration/LocalCollaborationPanel.vue'
import { manifestDelta } from '../../../../shared/collaboration-delta'

let state: CollaborationState, manifest: CollaborationManifest, local: LocalCollaborationStatus
let controller: LocalCollaboration
const wrappers: ReturnType<typeof mount>[] = []
function setup(task: () => Record<string, any> = () => ({ id: manifest.task_id, execution_location: 'SERVER' })) {
  const wrapper = mount(defineComponent({ setup() { controller = useLocalCollaboration({ workspaceId: () => 'ws', task }); return () => null } }), { global: { plugins: [createI18n({ legacy: false, locale: 'zh', messages: { zh } })] } })
  wrappers.push(wrapper)
  return wrapper
}
beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks()
  mocks.desktop = true
  mocks.changed.mockReturnValue(mocks.unsubscribe)
  mocks.auth = reactive({ user: { id: crypto.randomUUID() } })
  const repo = { task_repository_id: 'repo1', repository_id: 'r1', repo_url: 'https://example.test/api', repo_slug: 'api', rel_path: 'api', branch_name: 'release/2.x', base_commit_sha: 'commit', files: [{ path: 'auth.py', sha256: 'a'.repeat(64), size: 1, mode: '100644' as const }] }
  manifest = { protocol_version: 1, task_id: crypto.randomUUID(), snapshot_id: 'snapshot1', workspace_revision: 1, session_generation: 1, session_revision: 1, repository_set_digest: 'digest', source: 'INITIAL', repositories: [repo] }
  state = { ...manifest, enabled: false, sync_phase: 'OFF', state_version: 1, input_snapshot_id: null, progress_snapshot_id: null, lease_epoch: 1, binding_id: 'binding', conflicts: [] }
  local = { directory_mode: 'MAPPED', task_id: manifest.task_id, binding_id: 'binding', task_root: 'G:/private/task', manifest, baseline: manifest, target: manifest, repositories: [{ ...repo, local_worktree_path: 'G:/private/task/api', mapped_repo_root: 'G:/api' }], state: 'READY', conflicts: [], local_changes: [] }
  mocks.api.reviewBaseline.mockImplementation(async () => manifest)
  mocks.api.review.mockImplementation(async () => ({ input: { ...manifest, snapshot_id: 'before', repositories: manifest.repositories.map(repo => ({ ...repo, files: [] })) }, cloud: manifest, running: false }))
  mocks.api.state.mockImplementation(async () => ({ ...state }))
  mocks.api.snapshot.mockImplementation(async () => manifest)
  mocks.api.post.mockImplementation(async (action, body) => {
    if (action === 'enable') state = { ...state, ...body, driver_user_id: mocks.auth.user!.id, enabled: true, sync_phase: 'DELIVERY_PENDING', input_snapshot_id: manifest.snapshot_id }
    if (action === 'receipt') state = { ...state, sync_phase: body.conflicts.length ? 'CONFLICT_PENDING' : 'READY' }
    if (action === 'release-driver') state = { ...state, driver_connected: false, lease_epoch: state.lease_epoch + 1 }
    if (action === 'claim-driver') state = { ...state, ...body, driver_connected: true, sync_phase: 'DELIVERY_PENDING' }
    if (action === 'latest-snapshot') return manifest
    if (action === 'objects/missing') return { missing: [] }
    if (action === 'handoff') state = { ...state, input_submission_id: body.submission_id, input_snapshot_id: 'input2' }
    if (action === 'fail-preparation') state = { ...state, sync_phase: 'READY', pending_submission_id: null }
    return { ...state }
  })
  mocks.mapping.mockResolvedValue({ localPath: 'G:/api', gitRemoteUrl: repo.repo_url })
  mocks.directory.mockResolvedValue({ canceled: false, path: 'G:/selected-api' })
  mocks.validate.mockResolvedValue({ ok: true })
  mocks.remotes.mockResolvedValue([{ name: 'origin', fetchUrl: repo.repo_url }])
  mocks.setMapping.mockImplementation(async (mapping) => { mocks.mapping.mockResolvedValue(mapping); return mapping })
  mocks.api.upload.mockReset().mockResolvedValue(undefined)
  mocks.native.mockImplementation(async ({ kind, payload }) => {
    if (kind === 'inspect_mappings') return { ready: true, checks: manifest.repositories.map(repo => ({ task_repository_id: repo.task_repository_id, local_path: `G:/${repo.repo_slug}`, expected_head: repo.base_commit_sha, local_head: repo.base_commit_sha, clean: true, changes: [], errors: [] })) }
    if (kind === 'describe') return { mapped_repositories: 1, task_root: local.task_root, repositories: local.repositories }
    if (kind === 'binding' && payload.optional && !state.enabled) return null
    if (['status', 'binding'].includes(kind) && !state.enabled) throw new Error('COLLABORATION_BINDING_MISSING')
    if (kind === 'missing_objects') return { missing: [] }
    if (kind === 'capture') return { manifest, status: local, objects: [] }
    return local
  })
})
afterEach(async () => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount())
  mocks.auth.user = null; await nextTick(); vi.useRealTimers()
})

describe('local collaboration coordinator', () => {
  it('enables a first-time binding without requesting status for a nonexistent binding', async () => {
    setup(); await flushPromises(); await controller.enable()
    const calls = mocks.native.mock.calls.map(([request]) => request)
    const preparedAt = calls.findIndex(request => request.kind === 'prepare')
    expect(preparedAt).toBeGreaterThan(-1)
    expect(calls.slice(0, preparedAt).some(request => request.kind === 'status')).toBe(false)
    expect(calls.filter(request => request.kind === 'binding').every(request => request.payload.optional === true)).toBe(true)
    expect(controller.phase.value).toBe('READY')
    expect(controller.error.value).toBe('')
  })
  it.each([false, true])('reads uncached preview text from the cloud (legacy host: %s)', async legacy => {
    setup(); await flushPromises()
    mocks.native.mockClear()
    mocks.native.mockImplementation(async ({ kind, payload }) => {
      expect(kind).toBe('read_object'); expect(payload.optional).toBe(true)
      if (legacy) throw new Error("Error invoking remote method 'sdd:collaboration:execute': Error: LOCAL_CONTENT_OBJECT_MISSING")
      return null
    })
    mocks.api.object.mockResolvedValue(new TextEncoder().encode('cloud text').buffer)
    await expect(controller.readText('a'.repeat(64))).resolves.toBe('cloud text')
    expect(mocks.api.object).toHaveBeenCalledWith('a'.repeat(64))
    expect(controller.participating.value).toBe(false)
  })
  it.each(['local text', ''])('uses cached preview bytes, including an empty file: %s', async content => {
    setup(); await flushPromises()
    mocks.native.mockResolvedValue({ content: btoa(content) })
    await expect(controller.readText('a'.repeat(64))).resolves.toBe(content)
    expect(mocks.api.object).not.toHaveBeenCalled()
  })
  it('reads preview text directly from the cloud in a browser and propagates download errors', async () => {
    mocks.desktop = false
    setup(); await flushPromises(); mocks.native.mockClear()
    mocks.api.object.mockResolvedValueOnce(new TextEncoder().encode('browser text').buffer)
    await expect(controller.readText('a'.repeat(64))).resolves.toBe('browser text')
    mocks.api.object.mockRejectedValueOnce(new Error('Cloud object unavailable'))
    await expect(controller.readText('b'.repeat(64))).rejects.toThrow('Cloud object unavailable')
    expect(mocks.native).not.toHaveBeenCalled()
  })
  it.each(['CORRUPT_LOCAL_CONTENT_OBJECT', 'Local resource worker exited (1)', 'EACCES: permission denied'])('keeps local preview failures visible: %s', async message => {
    setup(); await flushPromises()
    mocks.native.mockRejectedValue(new Error(message))
    await expect(controller.readText('a'.repeat(64))).rejects.toThrow(message)
    expect(mocks.api.object).not.toHaveBeenCalled()
  })
  it.each(['Unexpected token in binding JSON', 'ENOENT: missing Git index', 'EACCES: permission denied'])('does not enable over an unreadable local binding: %s', async message => {
    setup(); await flushPromises()
    const nativeImplementation = mocks.native.getMockImplementation()!
    mocks.native.mockImplementation(async request => {
      if (request.kind === 'binding') throw new Error(message)
      return nativeImplementation(request)
    })
    await controller.enable()
    expect(controller.error.value).toContain(message)
    expect(mocks.api.post).not.toHaveBeenCalled()
  })
  it.each([
    "Error invoking remote method 'sdd:collaboration:execute': Error: ENOENT: no such file or directory, open 'C:\\profile\\collaboration\\bindings\\TASK.json'",
    "ENOENT: no such file or directory, open '/profile/collaboration/bindings/TASK.json'",
    'COLLABORATION_BINDING_MISSING',
  ])('treats only the missing local task binding as an empty backup list on older hosts: %s', async message => {
    setup(); await flushPromises()
    mocks.native.mockClear().mockRejectedValue(new Error(message.replace('TASK', manifest.task_id)))
    mocks.api.post.mockClear()
    await expect(controller.listBackups()).resolves.toEqual({ backup_directory:'', backups:[] })
    expect(mocks.native).toHaveBeenCalledOnce()
    expect(mocks.native).toHaveBeenCalledWith(expect.objectContaining({ kind:'backups', payload:expect.objectContaining({ task_id:manifest.task_id }) }))
    expect(controller.participating.value).toBe(false)
    expect(mocks.api.post).not.toHaveBeenCalled()
  })
  it('does not hide missing backup contents, another task binding or permissions errors', async () => {
    setup(); await flushPromises()
    for (const message of [
      "ENOENT: no such file or directory, open 'C:\\profile\\collaboration\\objects\\missing.json'",
      "ENOENT: no such file or directory, open 'C:\\profile\\collaboration\\bindings\\other-task.json'",
      `EACCES: permission denied, open 'C:/profile/collaboration/bindings/${manifest.task_id}.json'`,
      'Unexpected token in binding JSON',
    ]) {
      mocks.native.mockRejectedValueOnce(new Error(message))
      await expect(controller.listBackups()).rejects.toThrow(message)
    }
  })
  it('still queries retained backups when not participating and avoids native access in a browser', async () => {
    setup(); await flushPromises()
    const saved = { backup_directory:'G:/backups', backups:[{ path:'shared.txt', sha256:'retained' }] }
    mocks.native.mockClear().mockResolvedValueOnce(saved)
    expect(controller.participating.value).toBe(false)
    expect(await controller.listBackups()).toEqual(saved)
    expect(mocks.native).toHaveBeenCalledOnce()
  })
  it('does not invoke the native backup API in a browser', async () => {
    mocks.desktop = false
    setup(); await flushPromises()
    mocks.native.mockClear()
    expect(await controller.listBackups()).toEqual({ backup_directory:'', backups:[] })
    expect(mocks.native).not.toHaveBeenCalled()
  })
  it('loads cloud results lazily with no mapping, connection, file scan or polling', async () => {
    mocks.mapping.mockResolvedValue(null)
    setup(); await flushPromises()
    expect(mocks.api.review).not.toHaveBeenCalled()
    mocks.native.mockClear(); mocks.api.post.mockClear()
    await controller.loadReview(); await flushPromises()
    expect(controller.input.value?.snapshot_id).toBe('before')
    expect(controller.reviewBaseline.value?.snapshot_id).toBe(manifest.snapshot_id)
    expect(mocks.api.reviewBaseline).toHaveBeenCalledTimes(1)
    expect(controller.cloud.value?.snapshot_id).toBe(manifest.snapshot_id)
    expect(controller.participating.value).toBe(false)
    expect(controller.blocked.value).toBe(false)
    expect(mocks.api.post).not.toHaveBeenCalled()
    expect(mocks.native).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(65000)
    expect(mocks.api.review).toHaveBeenCalledTimes(1)
    controller.refreshResults(); await flushPromises()
    expect(mocks.api.review).toHaveBeenCalledTimes(2)
    expect(mocks.api.reviewBaseline).toHaveBeenCalledTimes(1)
  })
  it('loads cloud results in a browser without desktop APIs', async () => {
    mocks.desktop = false
    setup(); await flushPromises(); await controller.loadReview(); await flushPromises()
    expect(controller.cloud.value?.snapshot_id).toBe(manifest.snapshot_id)
    expect(controller.reviewError.value).toBe('')
  })
  it('keeps the old comparison paired until the cloud snapshot reaches the new baseline', async () => {
    mocks.desktop = false
    setup(); await flushPromises(); await controller.loadReview(); await flushPromises()
    const original = controller.reviewBaseline.value
    const next = { ...manifest, snapshot_id:'updated', repositories:manifest.repositories.map(repo => ({ ...repo, base_commit_sha:'next-commit' })) }
    state = { ...state, repositories:next.repositories }
    mocks.api.reviewBaseline.mockResolvedValue(next)
    let publish!: (value: any) => void
    mocks.api.review.mockImplementationOnce(() => new Promise(resolve => { publish = resolve }))
    controller.refreshResults(); await flushPromises()
    expect(controller.reviewBaseline.value).toEqual(original)
    publish({ input:next, cloud:next, running:false }); await flushPromises()
    expect(controller.reviewBaseline.value?.repositories[0]?.base_commit_sha).toBe('next-commit')
    expect(controller.cloud.value?.snapshot_id).toBe('updated')
  })
  it('performs no periodic state, file, or backup reads while connected, retaining only lease renewal', async () => {
    setup(); await flushPromises(); await controller.enable()
    mocks.api.state.mockClear(); mocks.native.mockClear(); mocks.api.post.mockClear()
    await vi.advanceTimersByTimeAsync(65000)
    expect(mocks.api.state).not.toHaveBeenCalled()
    expect(mocks.native).not.toHaveBeenCalled()
    expect(mocks.api.post.mock.calls.length).toBeGreaterThan(0)
    expect(mocks.api.post.mock.calls.every(([action]) => action === 'lease')).toBe(true)
  })
  it('catches up once on the current task socket becoming ready, without a polling fallback', async () => {
    setup(); await flushPromises(); await controller.enable()
    mocks.api.state.mockClear()
    state = { ...state, state_version: state.state_version + 1, sync_phase: 'RUNNING' }
    controller.onConnectionReady('another-task'); await flushPromises()
    expect(mocks.api.state).not.toHaveBeenCalled()
    controller.onConnectionReady(manifest.task_id); await flushPromises()
    expect(mocks.api.state).toHaveBeenCalledTimes(1)
    expect(controller.phase.value).toBe('RUNNING')
    await vi.advanceTimersByTimeAsync(30000)
    expect(mocks.api.state).toHaveBeenCalledTimes(1)
  })
  it('coalesces duplicate socket events and ignores old events without reloading files', async () => {
    setup(); await flushPromises(); await controller.enable()
    mocks.api.state.mockClear()
    state = { ...state, state_version: state.state_version + 1, sync_phase: 'RUNNING' }
    const event = { task_id: manifest.task_id, state_version: state.state_version }
    controller.onEvent(event); controller.onEvent(event); controller.onEvent(event)
    await flushPromises()
    expect(mocks.api.state).toHaveBeenCalledTimes(1)
    mocks.native.mockClear()
    controller.onEvent(event); controller.onEvent({ ...event, task_id: 'other' })
    controller.onEvent({ ...event, state_version: event.state_version - 1 })
    await flushPromises()
    expect(mocks.api.state).toHaveBeenCalledTimes(1)
    expect(mocks.native).not.toHaveBeenCalled()
  })
  it('updates local differences on a native change without contacting the server and unsubscribes on exit', async () => {
    const wrapper = setup(); await flushPromises(); await controller.enable()
    const notify = mocks.changed.mock.calls[0][0]
    mocks.api.state.mockClear(); mocks.api.post.mockClear(); mocks.native.mockClear()
    notify({ task_id: 'other' }); await flushPromises()
    expect(mocks.native).not.toHaveBeenCalled()
    local = { ...local, local_changes: [{ task_repository_id: 'repo1', path: 'auth.py', base: null, local: manifest.repositories[0]!.files[0]! }] }
    notify({ task_id: manifest.task_id }); await flushPromises()
    expect(controller.local.value?.local_changes).toHaveLength(1)
    expect(mocks.api.state).not.toHaveBeenCalled()
    expect(mocks.api.post).not.toHaveBeenCalled()
    expect(mocks.api.upload).not.toHaveBeenCalled()
    expect(mocks.native.mock.calls.map(([request]) => request.kind)).toEqual(['status'])
    wrapper.unmount(); await flushPromises()
    expect(mocks.unsubscribe).toHaveBeenCalledOnce()
    mocks.native.mockClear(); notify({ task_id: manifest.task_id }); await flushPromises()
    expect(mocks.native).not.toHaveBeenCalled()
  })
  it('processes the event after a command response so its input snapshot is not left waiting for a poll', async () => {
    setup(); await flushPromises()
    const post = mocks.api.post.getMockImplementation()!
    mocks.api.post.mockImplementation(async (action, body) => {
      const result = await post(action, body)
      if (action === 'enable' || action === 'receipt') state = { ...result, state_version: result.state_version + 1 }
      return { ...state }
    })
    await controller.enable()
    expect(controller.input.value).toBeNull()
    mocks.api.state.mockClear()
    controller.onEvent({ task_id: manifest.task_id, state_version: state.state_version })
    await flushPromises()
    expect(controller.input.value?.snapshot_id).toBe(manifest.snapshot_id)
    expect(mocks.api.state).toHaveBeenCalledTimes(1)
  })
  it('fetches a newer notification received during an older in-flight snapshot', async () => {
    setup(); await flushPromises(); await controller.enable()
    const older = { ...state, state_version: 2 }
    let resolve!: (value: CollaborationState) => void
    mocks.api.state.mockClear().mockImplementationOnce(() => new Promise<CollaborationState>(done => { resolve = done }))
    const refresh = controller.refresh(); await flushPromises()
    state = { ...state, state_version: 3, sync_phase: 'RUNNING' }
    controller.onEvent({ task_id: manifest.task_id, state_version: 3 })
    resolve(older); await refresh
    expect(controller.state.value?.state_version).toBe(3)
    expect(controller.phase.value).toBe('RUNNING')
    expect(mocks.api.state).toHaveBeenCalledTimes(2)
  })
  it('applies the current cloud candidate immediately when auto-receive is enabled and previews after disabling', async () => {
    setup(); await flushPromises(); await controller.enable()
    manifest = { ...manifest, snapshot_id: 'progress1', source: 'PROGRESS' }
    state = { ...state, sync_phase: 'RUNNING', progress_snapshot_id: manifest.snapshot_id, state_version: state.state_version + 1 }
    controller.onEvent({ task_id: manifest.task_id, state_version: state.state_version }); await flushPromises()
    for (const enabled of [true, false]) {
      mocks.native.mockClear(); controller.setProgressive(enabled); await flushPromises()
      expect(mocks.native).toHaveBeenCalledWith(expect.objectContaining({ kind: 'reconcile', payload: expect.objectContaining({ preview: true, progressive: enabled }) }))
      expect(controller.progressive.value).toBe(enabled)
    }
  })
  it.each(['SERVER', 'LOCAL'])('does not initialize, poll or block diagnosis tasks on %s', async execution_location => {
    setup(() => ({ id: manifest.task_id, task_type: 'DIAGNOSIS', execution_location }))
    await flushPromises()
    await controller.enable(); await controller.receiveOnce(); await controller.refresh()
    await vi.advanceTimersByTimeAsync(10000)
    expect(controller.supported.value).toBe(false)
    expect(controller.blocked.value).toBe(false)
    expect(controller.participating.value).toBe(false)
    expect(controller.submissionMetadata()).toEqual({})
    expect(await controller.leave()).toBe(true)
    expect(mocks.api.state).not.toHaveBeenCalled()
    expect(mocks.api.post).not.toHaveBeenCalled()
    expect(mocks.native).not.toHaveBeenCalled()
  })
  it('releases the development binding and stops polling when navigating to a diagnosis task', async () => {
    const task = shallowRef({ id: manifest.task_id, task_type: 'DEVELOPMENT', execution_location: 'SERVER' })
    setup(() => task.value); await flushPromises(); await controller.enable()
    expect(controller.participating.value).toBe(true)
    task.value = { ...task.value, id: 'diagnosis-task', task_type: 'DIAGNOSIS' }
    await flushPromises()
    expect(controller.supported.value).toBe(false)
    expect(controller.blocked.value).toBe(false)
    expect(mocks.api.post.mock.calls.some(([action]) => action === 'release-driver')).toBe(true)
    mocks.api.state.mockClear(); mocks.native.mockClear()
    await vi.advanceTimersByTimeAsync(10000)
    expect(mocks.api.state).not.toHaveBeenCalled()
    expect(mocks.native).not.toHaveBeenCalled()
    expect(controller.submissionMetadata()).toEqual({})
  })
  it('allows cloud messages after disconnect without attaching local input metadata', async () => {
    setup(); await flushPromises(); await controller.enable(); await controller.leave()
    expect(controller.participating.value).toBe(false)
    expect(controller.blocked.value).toBe(false)
    expect(controller.submissionMetadata()).toEqual({})
  })
  it('does not replay an old human handoff when reconnecting to a cloud-only input', async () => {
    setup(); await flushPromises(); await controller.enable()
    manifest = { ...manifest, snapshot_id: 'cloud-input', workspace_revision: 2, source: 'HUMAN_HANDOFF' }
    state = { ...state, sync_phase: 'PREPARING', input_mode: 'CLOUD', input_snapshot_id: manifest.snapshot_id,
      input_submission_id: 'cloud-message', pending_submission_id: 'cloud-message' }
    mocks.native.mockClear(); mocks.api.post.mockClear()
    await controller.refresh()
    expect(controller.error.value).toBe('')
    expect(controller.input.value?.snapshot_id).toBe('cloud-input')
    expect(mocks.native.mock.calls.some(([request]) => ['capture', 'accept_input'].includes(request.kind))).toBe(false)
    expect(mocks.api.post.mock.calls.some(([action]) => action === 'handoff')).toBe(false)
  })
  it('labels reconnection as reusing the baseline and skips the first-connection cleanliness gate', async () => {
    setup(); await flushPromises(); await controller.enable(); await controller.leave()
    local = { ...local, released: true, suspended: true }
    const native = mocks.native.getMockImplementation()!
    let finish!: () => void
    const pending = new Promise<void>(resolve => { finish = resolve })
    mocks.native.mockImplementation(async request => { if (request.kind === 'prepare') await pending; return native(request) })
    mocks.native.mockClear()
    const connecting = controller.enable(); await flushPromises()
    expect(controller.operationStage.value).toBe('resumingBaseline')
    expect(mocks.native.mock.calls.some(([request]) => request.kind === 'inspect_mappings')).toBe(false)
    finish(); await connecting
  })
  it('receives once without enabling, claiming, uploading, or acknowledging another driver delivery', async () => {
    state = { ...state, enabled: true, sync_phase: 'RUNNING', driver_user_id: 'someone-else', driver_connected: true }
    setup(); await flushPromises()
    await controller.receiveOnce()
    expect(controller.receivedOnce.value).toBe(true)
    expect(controller.participating.value).toBe(false)
    expect(mocks.api.post.mock.calls.map(([action]) => action)).toEqual(['latest-snapshot'])
    expect(mocks.api.upload).not.toHaveBeenCalled()
    expect(mocks.native).toHaveBeenLastCalledWith(expect.objectContaining({ kind: 'suspend' }))
    const downloaded = controller.cloud.value, beforeDownload = controller.input.value
    manifest = { ...manifest, snapshot_id: 'later-cloud' }
    state = { ...state, progress_snapshot_id: 'later-cloud', input_snapshot_id: 'later-input' }
    mocks.native.mockClear(); mocks.api.post.mockClear()
    mocks.api.snapshot.mockClear()
    await vi.advanceTimersByTimeAsync(30000)
    expect(mocks.api.post).not.toHaveBeenCalled()
    expect(mocks.native).not.toHaveBeenCalled()
    expect(mocks.api.snapshot).not.toHaveBeenCalled()
    expect(controller.cloud.value).toBe(downloaded)
    expect(controller.input.value).toBe(beforeDownload)
  })
  it('retains download-only conflicts while the cloud Agent is running, and never acknowledges its delivery', async () => {
    state = { ...state, enabled: true, sync_phase: 'RUNNING', driver_user_id: 'other', driver_connected: true }
    local = { ...local, state: 'CONFLICT_PENDING', conflict_set_id: 'one-shot', conflicts: [{task_repository_id:'repo1',path:'auth.py',expected_sha256:'local'}] }
    setup(); await flushPromises(); await controller.receiveOnce()
    expect(controller.conflicts.value).toHaveLength(1)
    await controller.restore(controller.conflicts.value, 'one-shot')
    expect(mocks.native.mock.calls.some(([r]) => r.kind === 'restore')).toBe(true)
    expect(mocks.native).toHaveBeenLastCalledWith(expect.objectContaining({kind:'suspend'}))
    expect(mocks.api.post.mock.calls.map(([action]) => action)).toEqual(['latest-snapshot'])
  })
  it.each([false, true])('keeps a failed one-time delivery visible and releases it when collaboration is enabled=%s', async enabled => {
    state.enabled = enabled
    local = {...local, state:'RECOVERY_REQUIRED',errors:['write failed']}
    setup(); await flushPromises(); await controller.receiveOnce()
    expect(controller.receivedOnce.value).toBe(false)
    expect(controller.error.value).toContain('write failed')
    expect(controller.busy.value).toBe(false)
    expect(mocks.native).toHaveBeenLastCalledWith(expect.objectContaining({kind:'suspend'}))
    await vi.advanceTimersByTimeAsync(5000)
    expect(controller.error.value).toContain('write failed')
  })
  it('releases even with pending conflicts and does not reconnect when the page is reopened', async () => {
    const page = setup(); await flushPromises(); await controller.enable()
    state = { ...state, sync_phase: 'CONFLICT_PENDING' }
    local.conflicts = [{task_repository_id: 'repo1', path: 'auth.py', local: manifest.repositories[0]!.files[0]}]
    await controller.refresh()
    expect(await controller.leave()).toBe(true)
    expect(controller.participating.value).toBe(false)
    expect(state.driver_connected).toBe(false)
    expect(local.conflicts).toHaveLength(1)
    page.unmount(); await flushPromises()
    mocks.api.post.mockClear(); mocks.native.mockClear()
    setup(); await flushPromises(); await vi.advanceTimersByTimeAsync(30000)
    expect(controller.participating.value).toBe(false)
    expect(mocks.api.post).not.toHaveBeenCalled()
    expect(mocks.native.mock.calls.every(([request]) => ['describe', 'binding'].includes(request.kind))).toBe(true)
  })
  it('keeps release failures visible and permits a retry instead of silently leaving a lease behind', async () => {
    setup(); await flushPromises(); await controller.enable()
    const post = mocks.api.post.getMockImplementation()!
    mocks.api.post.mockImplementation(async (action, body) => { if (action === 'release-driver') throw new Error('release unavailable'); return post(action, body) })
    expect(await controller.leave()).toBe(false)
    expect(controller.participating.value).toBe(true)
    expect(controller.error.value).toContain('release unavailable')
    mocks.api.post.mockImplementation(post)
    expect(await controller.leave()).toBe(true)
  })
  it('configures the selected repository inline without enabling or writing files', async () => {
    manifest.repositories[0]!.repository_id = ''
    saveRepoPreferences('ws', mocks.auth.user!.id, [{ repository_id: '', configured_git_url: 'https://example.test/other', local_path: 'G:/other' }])
    setup(); await flushPromises()
    await controller.selectMapping('repo1')
    expect(mocks.setMapping).toHaveBeenCalledWith({ workspaceId: 'ws', remoteUrl: manifest.repositories[0]!.repo_url, localPath: 'G:/selected-api', gitRemoteUrl: manifest.repositories[0]!.repo_url })
    expect(controller.mappings.value.repo1?.local_path).toBe('G:/selected-api')
    expect(controller.mappingChecks.value).toHaveLength(1)
    expect(readRepoPreferences('ws', mocks.auth.user!.id).some(row => row.local_path === 'G:/other')).toBe(true)
    expect(mocks.api.post.mock.calls.some(([action]) => action === 'enable')).toBe(false)
    expect(mocks.native.mock.calls.some(([request]) => ['prepare', 'reconcile', 'restore'].includes(request.kind))).toBe(false)
  })
  it('does not change a mapping when directory selection is canceled or invalid', async () => {
    setup(); await flushPromises()
    mocks.directory.mockResolvedValue({ canceled: true })
    await controller.selectMapping('repo1')
    expect(mocks.validate).not.toHaveBeenCalled()
    mocks.directory.mockResolvedValue({ canceled: false, path: 'G:/not-a-repo' })
    mocks.validate.mockResolvedValue({ ok: false })
    await controller.selectMapping('repo1')
    expect(mocks.setMapping).not.toHaveBeenCalled()
    expect(controller.error.value).toBeTruthy()
    expect(controller.busy.value).toBe(false)
  })
  it('keeps an active binding mapped to the same directory', async () => {
    setup(); await flushPromises(); await controller.enable()
    await controller.selectMapping('repo1')
    expect(mocks.directory).not.toHaveBeenCalled()
  })
  it('downloads missing dual-repository objects when an input manifest was viewed but never received locally', async () => {
    const first = manifest.repositories[0]!
    const second = { ...first, task_repository_id: 'repo2', repository_id: 'r2', repo_slug: 'web', rel_path: 'web' }
    const baseline = { ...manifest, snapshot_id: '', repositories: [first, second] }
    manifest = { ...manifest, repositories: [first, second].map((repo, i) => ({ ...repo, files: [{ ...repo.files[0]!, sha256: (i ? 'c' : 'b').repeat(64) }] })) }
    local = { ...local, baseline, manifest: baseline, target: undefined, state: 'PREPARED', repositories: baseline.repositories.map(repo => ({ ...repo, local_worktree_path: `G:/${repo.repo_slug}`, mapped_repo_root: `G:/${repo.repo_slug}` })) }
    state = { ...state, repositories: manifest.repositories, enabled: true, sync_phase: 'DELIVERY_PENDING', input_snapshot_id: manifest.snapshot_id,
      client_id: 'existing-client', instance_id: 'existing-instance', driver_user_id: mocks.auth.user!.id, driver_connected: true }
    mocks.api.snapshot.mockImplementation(async (_id, base) => base === manifest.snapshot_id ? manifestDelta(manifest, manifest) : manifest)
    const cached = new Set(['a'.repeat(64)]), implementation = mocks.native.getMockImplementation()!
    mocks.native.mockImplementation(async request => {
      if (request.kind === 'describe') return { mapped_repositories: 1, client_id: state.client_id, instance_id: state.instance_id }
      if (request.kind === 'missing_objects') return { missing: request.payload.sha256.filter((hash: string) => !cached.has(hash)) }
      if (request.kind === 'cache_objects') { request.payload.objects.forEach((object: { sha256: string }) => cached.add(object.sha256)); return {} }
      if (request.kind === 'reconcile') {
        if (manifest.repositories.some(repo => repo.files.some(file => !cached.has(file.sha256)))) throw new Error('LOCAL_CONTENT_OBJECT_MISSING')
        return { ...local, baseline: manifest, manifest, state: 'READY' }
      }
      return implementation(request)
    })
    setup(); await flushPromises(); await controller.enable(); await flushPromises()
    expect(controller.error.value).toBe('')
    expect(controller.phase.value).toBe('READY')
    expect(mocks.api.object.mock.calls.map(([hash]) => hash)).toEqual(['b'.repeat(64), 'c'.repeat(64)])
    expect(mocks.native.mock.calls.filter(([r]) => r.kind === 'missing_objects').flatMap(([r]) => r.payload.sha256)).toEqual(['b'.repeat(64), 'c'.repeat(64)])
  })
  it('keeps a delivery error stable across polls and retries only after an explicit recovery', async () => {
    const implementation = mocks.native.getMockImplementation()!
    let broken = true, attempts = 0
    mocks.native.mockImplementation(async request => {
      if (request.kind === 'reconcile') { attempts++; if (broken) throw new Error('LOCAL_CONTENT_OBJECT_MISSING') }
      return implementation(request)
    })
    setup(); await flushPromises(); await controller.enable()
    const errors: string[] = []
    const stop = watch(controller.error, value => errors.push(value), { flush: 'sync' })
    await vi.advanceTimersByTimeAsync(7500)
    expect(attempts).toBe(1)
    expect(errors).not.toContain('')
    expect(controller.error.value).toContain('LOCAL_CONTENT_OBJECT_MISSING')
    expect(controller.cloud.value?.snapshot_id).toBe(manifest.snapshot_id)
    expect(controller.label.value).toContain('等待重试')
    broken = false; await controller.recover(); stop()
    expect(attempts).toBe(2)
    expect(controller.error.value).toBe('')
    expect(controller.phase.value).toBe('READY')
  })
  it('checks only changed target objects after a confirmed baseline', async () => {
    setup(); await flushPromises(); await controller.enable()
    const old = manifest
    manifest = { ...manifest, snapshot_id: 'next-output', repositories: manifest.repositories.map(repo => ({ ...repo, files: [...repo.files, { ...repo.files[0]!, path: 'new.py', sha256: 'b'.repeat(64) }] })) }
    state = { ...state, snapshot_id: manifest.snapshot_id, sync_phase: 'DELIVERY_PENDING' }
    mocks.api.snapshot.mockImplementation(async () => manifestDelta(old, manifest))
    mocks.native.mockClear(); await controller.refresh()
    expect(mocks.native.mock.calls.filter(([r]) => r.kind === 'missing_objects').flatMap(([r]) => r.payload.sha256)).toEqual(['b'.repeat(64)])
  })
  it('can explicitly retry failed progress delivery while the Agent is still running', async () => {
    setup(); await flushPromises(); await controller.enable()
    manifest = { ...manifest, snapshot_id: 'progress2', source: 'PROGRESS' }
    state = { ...state, sync_phase: 'RUNNING', progress_snapshot_id: manifest.snapshot_id }
    const implementation = mocks.native.getMockImplementation()!
    let broken = true
    mocks.native.mockImplementation(async request => {
      if (request.kind === 'reconcile' && broken) throw new Error('LOCAL_CONTENT_OBJECT_MISSING')
      return implementation(request)
    })
    await controller.refresh(); expect(controller.error.value).toContain('LOCAL_CONTENT_OBJECT_MISSING')
    mocks.native.mockClear(); mocks.api.upload.mockClear()
    await controller.refresh(); expect(mocks.native).not.toHaveBeenCalled()
    broken = false; await controller.recover()
    expect(mocks.native).toHaveBeenCalledWith(expect.objectContaining({ kind: 'reconcile', payload: expect.objectContaining({ preview: true, progressive: false }) }))
    expect(controller.error.value).toBe('')
    expect(controller.phase.value).toBe('RUNNING')
    expect(mocks.api.upload).not.toHaveBeenCalled()
  })
  it('refuses cloud enable when either repository fails HEAD or cleanliness checks', async () => {
    const nativeImplementation = mocks.native.getMockImplementation()!
    mocks.native.mockImplementation(async request => request.kind === 'inspect_mappings' ? {
      ready: false, checks: [{ task_repository_id: 'repo1', local_path: 'G:/api', expected_head: 'commit', local_head: 'different', clean: false, changes: [' M auth.py'], errors: ['HEAD_MISMATCH', 'WORKTREE_DIRTY'] }],
    } : nativeImplementation(request))
    setup(); await flushPromises(); await controller.enable()
    expect(controller.error.value).toBe(zh.collaboration.mappingCheckFailed)
    expect(controller.mappingChecks.value[0].errors).toEqual(['HEAD_MISMATCH', 'WORKTREE_DIRTY'])
    expect(mocks.api.post).not.toHaveBeenCalled()
    expect(mocks.native.mock.calls.some(([request]) => request.kind === 'prepare')).toBe(false)
    expect(controller.busy.value).toBe(false)
  })
  it('requires the updated native capability instead of invoking the old worktree preparation', async () => {
    const nativeImplementation = mocks.native.getMockImplementation()!
    mocks.native.mockImplementation(async request => request.kind === 'describe' ? { task_root: local.task_root, repositories: [] } : nativeImplementation(request))
    setup(); await flushPromises(); await controller.enable()
    expect(controller.error.value).toBe(zh.collaboration.restartDesktop)
    expect(mocks.api.post).not.toHaveBeenCalled()
    expect(mocks.native.mock.calls.some(([request]) => request.kind === 'prepare')).toBe(false)
  })
  it('shows the real baseline preparation stage and elapsed time while native capture is pending', async () => {
    const nativeImplementation = mocks.native.getMockImplementation()!
    let finish!: () => void
    const pending = new Promise<void>(resolve => { finish = resolve })
    mocks.native.mockImplementation(async request => {
      if (request.kind === 'prepare') { expect(request.payload.directory_mode).toBe('MAPPED'); expect(request.payload.workspace_root).toBeUndefined(); await pending }
      return nativeImplementation(request)
    })
    setup(); await flushPromises(); const enabling = controller.enable(); await flushPromises()
    expect(controller.operationStage.value).toBe('capturingBaseline')
    await vi.advanceTimersByTimeAsync(3000)
    expect(controller.operationSeconds.value).toBe(3)
    finish(); await enabling; await flushPromises()
    expect(controller.phase.value).toBe('READY')
    expect(controller.operationStage.value).toBe('')
  })
  it('opening a server task only reads state and mappings, without enabling or touching files', async () => {
    setup(); await flushPromises()
    expect(controller.enabled.value).toBe(false)
    expect(controller.blocked.value).toBe(false)
    expect(mocks.native.mock.calls.every(([request]) => ['describe', 'binding'].includes(request.kind))).toBe(true)
    expect(mocks.api.post).not.toHaveBeenCalled()
    expect(controller.mappings.value.repo1?.local_path).toBe('G:/api')
  })
  it('enables only explicitly, and waits for native reconciliation and the repository receipt', async () => {
    setup(); await flushPromises(); await controller.enable()
    expect(mocks.native.mock.calls.map(([request]) => request.kind)).toContain('prepare')
    expect(mocks.api.post).toHaveBeenCalledWith('receipt', expect.objectContaining({ repository_results: [{ task_repository_id: 'repo1', status: 'ALIGNED' }] }))
    expect(controller.phase.value).toBe('READY')
    expect(mocks.open).not.toHaveBeenCalled()
    await controller.openDirectory('repo1')
    expect(mocks.open).toHaveBeenCalledWith('G:/private/task/api')
  })
  it('retries failed local preparation using the enabled server binding without another enable request', async () => {
    const prepared = { ...local, binding_id: 'binding' }
    const nativeImplementation = mocks.native.getMockImplementation()!
    let preparations = 0
    mocks.native.mockImplementation(async request => {
      if (request.kind === 'prepare') {
        if (++preparations === 1) { local = { ...local, binding_id: 'binding', baseline: undefined, repositories: [], state: 'PREPARED' }; throw new Error('Git checkout failed: Filename too long') }
        local = prepared; return local
      }
      return nativeImplementation(request)
    })
    setup(); await flushPromises(); await controller.enable()
    expect(controller.enabled.value).toBe(true)
    expect(controller.preparationRequired.value).toBe(true)
    expect(controller.phase.value).toBe('DELIVERY_PENDING')
    expect(controller.blocked.value).toBe(true)
    await vi.advanceTimersByTimeAsync(5000)
    expect(preparations).toBe(1)
    expect(controller.error.value).toContain('Filename too long')
    await controller.recover()
    expect(preparations).toBe(2)
    expect(mocks.native).toHaveBeenLastCalledWith(expect.objectContaining({ kind: 'reconcile' }))
    expect(mocks.native.mock.calls.filter(([request]) => request.kind === 'prepare').map(([request]) => request.payload.binding_id)).toEqual(['binding', 'binding'])
    expect(mocks.api.post.mock.calls.filter(([action]) => action === 'enable')).toHaveLength(1)
    expect(controller.preparationRequired.value).toBe(false)
    expect(controller.phase.value).toBe('READY')
    expect(controller.error.value).toBe('')
  })

  it('requires an explicit retry when the same driver opens a pending initial delivery without a native binding', async () => {
    state = { ...state, enabled: true, sync_phase: 'DELIVERY_PENDING', client_id: 'existing-client', instance_id: 'existing-instance', driver_user_id: mocks.auth.user!.id, driver_connected: true }
    const nativeImplementation = mocks.native.getMockImplementation()!
    let exists = false
    mocks.native.mockImplementation(async request => {
      if (request.kind === 'describe') return { mapped_repositories: 1, task_root: local.task_root, repositories: local.repositories, client_id: state.client_id, instance_id: state.instance_id }
      if (request.kind === 'binding' && request.payload.optional && !exists) return null
      if (['status', 'binding'].includes(request.kind) && !exists) throw new Error('COLLABORATION_BINDING_MISSING')
      if (request.kind === 'prepare') exists = true
      return nativeImplementation(request)
    })
    setup(); await flushPromises(); await vi.advanceTimersByTimeAsync(5000)
    expect(controller.participating.value).toBe(false)
    expect(controller.preparationRequired.value).toBe(false)
    expect(mocks.native.mock.calls.some(([request]) => request.kind === 'prepare')).toBe(false)
    await controller.enable() // A reused activation entry must also route to recovery.
    expect(mocks.api.post.mock.calls.some(([action]) => action === 'enable')).toBe(false)
    expect(mocks.native.mock.calls.filter(([request]) => request.kind === 'prepare')).toHaveLength(1)
    expect(controller.phase.value).toBe('READY')
  })

  it('retries delivery with an already complete local binding without preparing it again', async () => {
    setup(); await flushPromises(); await controller.enable()
    const preparationCount = mocks.native.mock.calls.filter(([request]) => request.kind === 'prepare').length
    state = { ...state, sync_phase: 'RECOVERY_REQUIRED', recovery_kind: 'LOCAL_DELIVERY' }
    await controller.recover()
    expect(mocks.native.mock.calls.filter(([request]) => request.kind === 'prepare')).toHaveLength(preparationCount)
    expect(controller.phase.value).toBe('READY')
  })
  it('refreshes both mappings saved after a missing binding, across settings navigation, and enables explicit recovery', async () => {
    const second = { ...manifest.repositories[0], task_repository_id: 'repo2', repository_id: 'r2', repo_url: 'https://example.test/web', repo_slug: 'web', rel_path: 'web', branch_name: 'main', base_commit_sha: 'other-commit' }
    manifest = { ...manifest, repositories: [...manifest.repositories, second] }
    state = { ...state, repositories: manifest.repositories, enabled: true, sync_phase: 'DELIVERY_PENDING', client_id: 'existing-client', instance_id: 'existing-instance', driver_user_id: mocks.auth.user!.id, driver_connected: true }
    local = { ...local, manifest, baseline: manifest, target: manifest, repositories: [...(local.repositories || []), { ...second, mapped_repo_root: 'G:/web', local_worktree_path: 'G:/private/task/web' }] }
    mocks.mapping.mockResolvedValue(null)
    const nativeImplementation = mocks.native.getMockImplementation()!
    let exists = false
    mocks.native.mockImplementation(async request => {
      if (request.kind === 'describe') return { mapped_repositories: 1, task_root: local.task_root, repositories: local.repositories, client_id: state.client_id, instance_id: state.instance_id }
      if (['status', 'binding'].includes(request.kind) && !exists) throw new Error(`Error invoking remote method 'sdd:collaboration:execute': ENOENT: no such file or directory, open 'C:/profile/collaboration/bindings/${manifest.task_id}.json'`)
      if (request.kind === 'prepare') exists = true
      return nativeImplementation(request)
    })
    const page = setup(); await flushPromises()
    expect(controller.participating.value).toBe(false)
    expect(controller.error.value).toBe('')
    page.unmount(); await flushPromises() // Returning creates a fresh, disconnected page controller.
    setup(); await flushPromises()
    saveRepoPreferences('another-workspace', mocks.auth.user!.id, [{ repository_id: 'r1', local_path: 'G:/wrong', configured_git_url: second.repo_url }])
    await flushPromises()
    expect(controller.mappings.value).toEqual({})
    saveRepoPreferences('ws', mocks.auth.user!.id, [{ repository_id: 'r1', local_path: 'G:/api', configured_git_url: 'https://fork.test/api' }, { repository_id: 'r2', local_path: 'G:/web', configured_git_url: second.repo_url }])
    await flushPromises()
    expect(controller.mappings.value).toEqual({ repo1: { local_path: 'G:/api', configured_git_url: 'https://fork.test/api' }, repo2: { local_path: 'G:/web', configured_git_url: second.repo_url } })
    const panel = mount(LocalCollaborationPanel, { props: { controller, workspaceId: 'ws', taskId: 'task' }, global: { plugins: [createI18n({ legacy: false, locale: 'zh', messages: { zh } }), createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })], stubs: { CodeComparison: true, CollaborationBackups: true } } })
    wrappers.push(panel)
    await panel.findAll('button').find(button => button.text() === '仓库与版本')!.trigger('click')
    expect(panel.text()).toContain('G:/api')
    expect(panel.text()).toContain('G:/web')
    expect(panel.text()).not.toContain(zh.collaboration.mappingMissing)
    expect(panel.text()).not.toContain('ENOENT')
    await flushPromises()
    const actions = mount(CollaborationActions, { props: { controller }, global: { plugins: [createI18n({ legacy: false, locale: 'zh', messages: { zh } })] } })
    wrappers.push(actions)
    const retry = actions.get('input[role="switch"][aria-label="本地协同"]')
    expect(retry.attributes('disabled')).toBeUndefined()
    await vi.advanceTimersByTimeAsync(5000)
    expect(mocks.native.mock.calls.filter(([request]) => request.kind === 'describe')).toHaveLength(2)
    expect(mocks.native.mock.calls.some(([request]) => request.kind === 'prepare')).toBe(false)
    expect(mocks.api.post.mock.calls.some(([action]) => action === 'objects/missing' || action === 'handoff')).toBe(false)
    await retry.setValue(true); await flushPromises()
    const prepared = mocks.native.mock.calls.find(([request]) => request.kind === 'prepare')![0].payload
    expect(prepared.repositories.map((repo: any) => [repo.task_repository_id, repo.local_path, repo.branch_name, repo.base_commit_sha])).toEqual([['repo1', 'G:/api', 'release/2.x', 'commit'], ['repo2', 'G:/web', 'main', 'other-commit']])
    expect(mocks.api.post.mock.calls.some(([action]) => action === 'enable')).toBe(false)
    expect(controller.phase.value).toBe('READY')
  })
  it('reloads desktop-only mapping changes on refresh while preparation is blocked, without reading a missing binding again', async () => {
    state = { ...state, enabled: true, sync_phase: 'DELIVERY_PENDING', client_id: 'existing-client', instance_id: 'existing-instance', driver_user_id: mocks.auth.user!.id, driver_connected: true }
    mocks.mapping.mockResolvedValue(null)
    mocks.native.mockImplementation(async ({ kind }) => {
      if (kind === 'inspect_mappings') return { ready: true, checks: [] }
    if (kind === 'describe') return { mapped_repositories: 1, task_root: local.task_root, repositories: local.repositories, client_id: state.client_id, instance_id: state.instance_id }
      throw new Error('COLLABORATION_BINDING_MISSING')
    })
    setup(); await flushPromises()
    const statuses = mocks.native.mock.calls.filter(([request]) => request.kind === 'status').length
    mocks.mapping.mockResolvedValue({ localPath: 'G:/api', gitRemoteUrl: manifest.repositories[0].repo_url })
    await controller.refreshComparison()
    expect(controller.mappings.value.repo1.local_path).toBe('G:/api')
    expect(mocks.native.mock.calls.filter(([request]) => request.kind === 'status')).toHaveLength(statuses)
    expect(controller.preparationRequired.value).toBe(false)
    expect(controller.error.value).not.toContain('ENOENT')
  })
  it('keeps other filesystem failures visible during local preparation', async () => {
    state = { ...state, enabled: true, sync_phase: 'DELIVERY_PENDING', client_id: 'existing-client', instance_id: 'existing-instance', driver_user_id: mocks.auth.user!.id, driver_connected: true }
    mocks.native.mockImplementation(async ({ kind }) => {
      if (kind === 'inspect_mappings') return { ready: true, checks: [] }
    if (kind === 'describe') return { mapped_repositories: 1, task_root: local.task_root, repositories: local.repositories, client_id: state.client_id, instance_id: state.instance_id }
      throw new Error('ENOENT: missing Git index')
    })
    setup(); await flushPromises(); await controller.enable()
    expect(controller.error.value).toContain('missing Git index')
  })
  it('releases the bound coordinator and stops polling after the task view unmounts', async () => {
    const wrapper = setup(); await flushPromises(); await controller.enable()
    wrapper.unmount(); const calls = mocks.api.state.mock.calls.length
    await vi.advanceTimersByTimeAsync(2600)
    expect(mocks.api.state.mock.calls.length).toBe(calls)
    expect(mocks.api.post).toHaveBeenCalledWith('release-driver', expect.objectContaining({lease_epoch: 1}))
    expect(mocks.native).toHaveBeenCalledWith(expect.objectContaining({ kind: 'suspend' }))
  })
  it('retries an explicitly busy lease after ten seconds without claiming success or hiding lease failures', async () => {
    setup(); await flushPromises(); await controller.enable()
    const postImplementation = mocks.api.post.getMockImplementation()!
    let attempts = 0, failure: unknown
    mocks.api.post.mockImplementation(async (action, body) => {
      if (action === 'lease') {
        attempts++
        if (failure) throw failure
        if (attempts === 1) throw { response: { status: 409, data: { detail: { code: 'TASK_BUSY', message: 'Input handoff holds the task row' } } } }
      }
      return postImplementation(action, body)
    })
    await controller.refresh()
    expect(attempts).toBe(1)
    expect(controller.error.value).toBe('')
    expect(controller.blocked.value).toBe(false)
    await vi.advanceTimersByTimeAsync(9999)
    expect(attempts).toBe(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(attempts).toBe(2) // Advancing lastLease on TASK_BUSY would suppress this retry.
    expect(controller.error.value).toBe('')
    vi.setSystemTime(Date.now() + 21000)
    failure = { response: { status: 409, data: { detail: { code: 'LEASE_EXPIRED', message: 'Lease expired' } } } }
    await controller.refresh()
    expect(controller.error.value).toContain('Lease expired')
    expect(controller.blocked.value).toBe(true)
    failure = { response: { status: 500, data: { detail: { code: 'TASK_BUSY', message: 'Unexpected server failure' } } } }
    await controller.refresh()
    expect(controller.error.value).toContain('Unexpected server failure')
  })
  it('captures only after a persisted PREPARING request and checks server objects again', async () => {
    setup(); await flushPromises(); await controller.enable(); await controller.refresh()
    expect(mocks.native.mock.calls.some(([request]) => request.kind === 'capture')).toBe(false)
    mocks.native.mockClear()
    state = { ...state, sync_phase: 'PREPARING', pending_submission_id: 'submission1' }
    await controller.refresh()
    expect(mocks.native).toHaveBeenCalledWith({ kind: 'capture', payload: expect.objectContaining({ task_id: manifest.task_id, operation_id: 'handoff:submission1', include_objects: false, session_generation: 1, session_revision: 1, delta_transport: true }) })
    expect(mocks.native).toHaveBeenCalledWith({ kind: 'capture', payload: expect.objectContaining({ manifest_delta: false }) })
    expect(mocks.api.post).toHaveBeenCalledWith('handoff', expect.objectContaining({ submission_id: 'submission1', manifest }))
    expect(mocks.api.post.mock.calls.filter(([action]) => action === 'objects/missing')).toHaveLength(1)
    expect(mocks.native.mock.calls.some(([request]) => request.kind === 'status')).toBe(false)
  })
  it.each(['capture', 'upload'])('automatically ends the pending input after a %s failure', async stage => {
    setup(); await flushPromises(); await controller.enable(); await controller.refresh()
    const native = mocks.native.getMockImplementation()!, post = mocks.api.post.getMockImplementation()!
    mocks.native.mockClear().mockImplementation(async request => {
      if (stage === 'capture' && request.kind === 'capture') throw new Error('local snapshot missing')
      return native(request)
    })
    mocks.api.post.mockClear().mockImplementation(async (action, body) => {
      if (stage === 'upload' && action === 'objects/missing') throw new Error('object upload failed')
      return post(action, body)
    })
    state = { ...state, sync_phase: 'PREPARING', pending_submission_id: 'failed-input' }
    await controller.refresh()
    expect(mocks.api.post).toHaveBeenCalledWith('fail-preparation', expect.objectContaining({
      submission_id: 'failed-input', operation_id: 'preparation-failed:failed-input',
      error_message: stage === 'capture' ? 'local snapshot missing' : 'object upload failed',
    }))
    expect(controller.busy.value).toBe(false)
    expect(controller.phase.value).toBe('READY')
    expect(controller.error.value).toContain(stage === 'capture' ? 'local snapshot missing' : 'object upload failed')
    expect(mocks.api.post.mock.calls.some(([action]) => action === 'handoff')).toBe(false)
    await controller.refresh()
    expect(mocks.native.mock.calls.filter(([request]) => request.kind === 'capture')).toHaveLength(1)
  })
  it('retries only the failure report on reconnect without recapturing failed input', async () => {
    setup(); await flushPromises(); await controller.enable(); await controller.refresh()
    const native = mocks.native.getMockImplementation()!, post = mocks.api.post.getMockImplementation()!
    mocks.native.mockClear().mockImplementation(async request => {
      if (request.kind === 'capture') throw new Error('capture failed')
      return native(request)
    })
    let attempts = 0
    mocks.api.post.mockImplementation(async (action, body) => {
      if (action === 'fail-preparation' && ++attempts === 1) throw new Error('connection lost')
      return post(action, body)
    })
    state = { ...state, sync_phase: 'PREPARING', pending_submission_id: 'failed-input' }
    await controller.refresh()
    expect(controller.phase.value).toBe('PREPARING')
    controller.onConnectionReady(manifest.task_id); await flushPromises()
    expect(attempts).toBe(2)
    expect(controller.phase.value).toBe('READY')
    expect(mocks.native.mock.calls.filter(([request]) => request.kind === 'capture')).toHaveLength(1)
  })
  it('discards a delayed failure report before preparing a newer message', async () => {
    setup(); await flushPromises(); await controller.enable(); await controller.refresh()
    const native = mocks.native.getMockImplementation()!, post = mocks.api.post.getMockImplementation()!
    mocks.native.mockImplementation(async request => {
      if (request.kind === 'capture' && request.payload.operation_id === 'handoff:old-input') throw new Error('capture failed')
      return native(request)
    })
    mocks.api.post.mockImplementation(async (action, body) => {
      if (action === 'fail-preparation') throw new Error('response lost')
      return post(action, body)
    })
    state = { ...state, sync_phase: 'PREPARING', pending_submission_id: 'old-input' }
    await controller.refresh()
    mocks.api.post.mockClear()
    state = { ...state, pending_submission_id: 'next-input' }
    await controller.refresh()
    expect(mocks.api.post.mock.calls.some(([action]) => action === 'fail-preparation')).toBe(false)
    expect(mocks.api.post).toHaveBeenCalledWith('handoff', expect.objectContaining({ submission_id: 'next-input' }))
  })
  it('does not fail an accepted input when a handoff acknowledgement was lost', async () => {
    setup(); await flushPromises(); await controller.enable(); await controller.refresh()
    const post = mocks.api.post.getMockImplementation()!
    mocks.api.post.mockClear().mockImplementation(async (action, body) => {
      if (action === 'handoff') {
        await post(action, body)
        throw new Error('handoff response lost')
      }
      if (action === 'fail-preparation') throw { response: { status: 409, data: { detail: { code: 'STATE_CHANGED' } } } }
      return post(action, body)
    })
    state = { ...state, sync_phase: 'PREPARING', pending_submission_id: 'accepted-input' }
    await controller.refresh()
    const attempts = mocks.api.post.mock.calls.filter(([action]) => action === 'fail-preparation').length
    controller.onConnectionReady(manifest.task_id); await flushPromises()
    expect(mocks.api.post.mock.calls.filter(([action]) => action === 'fail-preparation')).toHaveLength(attempts)
    expect(controller.state.value?.input_submission_id).toBe('accepted-input')
    expect(controller.phase.value).toBe('PREPARING')
  })
  it('only enables delta handoff after the server advertises support', async () => {
    state.capabilities = { manifest_delta: 1 }
    setup(); await flushPromises(); await controller.enable(); await controller.refresh()
    mocks.native.mockClear()
    state = { ...state, sync_phase: 'PREPARING', pending_submission_id: 'submission-delta' }
    await controller.refresh()
    expect(mocks.native).toHaveBeenCalledWith({ kind: 'capture', payload: expect.objectContaining({ manifest_delta: true }) })
  })
  it('only previews intermediate versions and never sends a final receipt for a preview', async () => {
    setup(); await flushPromises(); await controller.enable()
    state = { ...state, sync_phase: 'RUNNING', progress_snapshot_id: 'progress1' }
    manifest = { ...manifest, source: 'PROGRESS', snapshot_id: 'progress1' }
    mocks.api.post.mockClear()
    await controller.refresh()
    expect(mocks.native).toHaveBeenCalledWith(expect.objectContaining({ kind: 'reconcile', payload: expect.objectContaining({ preview: true }) }))
    expect(mocks.api.post.mock.calls.some(([action]) => action === 'receipt')).toBe(false)
  })
  it('lets the same user request connected desktop input from a browser without granting local writes', async () => {
    mocks.desktop = false
    state = { ...state, enabled: true, sync_phase: 'READY', driver_user_id: mocks.auth.user!.id, driver_connected: true }
    setup(); await flushPromises()
    expect(controller.blocked.value).toBe(false)
    expect(controller.submissionMetadata()).toEqual({ collaboration: { request_driver_input: true, binding_id: 'binding', lease_epoch: 1 } })
    expect(mocks.native).not.toHaveBeenCalled()
    state = { ...state, driver_connected: false }; await controller.refresh()
    expect(controller.blocked.value).toBe(false)
    expect(controller.submissionMetadata()).toEqual({})
  })
  it('re-comparing never applies files, sends receipts, or starts a pending input handoff', async () => {
    setup(); await flushPromises(); await controller.enable()
    state = { ...state, sync_phase: 'PREPARING', pending_submission_id: 'submission1' }
    mocks.native.mockClear(); mocks.api.post.mockClear()
    await controller.refreshComparison()
    expect(mocks.native.mock.calls.map(([request]) => request.kind)).toEqual(['status'])
    expect(mocks.api.post).not.toHaveBeenCalled()
  })

  it.each(['READY', 'RUNNING', 'WAITING_HITL'] as const)('keeps local changes on the client while %s', async phase => {
    setup(); await flushPromises(); await controller.enable()
    state = { ...state, sync_phase: phase }
    local = { ...local, local_changes: [{ task_repository_id: 'repo1', path: 'local.py', base: null, local: manifest.repositories[0]!.files[0]! }] }
    mocks.api.post.mockClear(); mocks.api.upload.mockClear()
    await controller.refresh()
    await vi.advanceTimersByTimeAsync(2500)
    expect(mocks.api.upload).not.toHaveBeenCalled()
    expect(mocks.api.post.mock.calls.some(([action]) => action === 'objects/missing' || action === 'handoff')).toBe(false)
  })

  it('delivers cloud output without uploading concurrent local files', async () => {
    setup(); await flushPromises(); await controller.enable()
    mocks.api.post.mockClear(); mocks.api.upload.mockClear()
    manifest = { ...manifest, snapshot_id: 'final2', workspace_revision: 2, source: 'FINAL' }
    state = { ...state, snapshot_id: 'final2', state_version: state.state_version + 1, sync_phase: 'DELIVERY_PENDING' }
    controller.onEvent({ task_id: manifest.task_id, state_version: state.state_version, sync_phase: 'DELIVERY_PENDING' })
    await flushPromises()
    expect(mocks.api.upload).not.toHaveBeenCalled()
    expect(mocks.api.post.mock.calls.some(([action]) => action === 'objects/missing')).toBe(false)
    expect(mocks.api.post).toHaveBeenCalledWith('receipt', expect.objectContaining({ snapshot_id: 'final2' }))
    expect(controller.cloud.value?.snapshot_id).toBe('final2')
    expect(controller.phase.value).toBe('READY')
  })

  it('finishes the immutable authoritative upload when another refresh arrives, without recapturing H', async () => {
    setup(); await flushPromises(); await controller.enable()
    manifest = { ...manifest, repositories: manifest.repositories.map(repo => ({ ...repo, files: Array.from({ length: 8 }, (_, index) => ({ path: `${index}.py`, sha256: index.toString(16).repeat(64), size: 1, mode: '100644' as const })) })) }
    let release!: () => void
    const firstBatch = new Promise<void>(resolve => { release = resolve })
    mocks.api.upload.mockImplementation(async () => { if (mocks.api.upload.mock.calls.length <= 4) await firstBatch })
    const nativeImplementation = mocks.native.getMockImplementation()!
    mocks.native.mockImplementation(async request => request.kind === 'read_object' ? { sha256: request.payload.sha256, content: 'AQ==' } : nativeImplementation(request))
    const postImplementation = mocks.api.post.getMockImplementation()!
    mocks.api.post.mockImplementation(async (action, body) => action === 'objects/missing' ? { missing: body.hashes } : postImplementation(action, body))
    state = { ...state, sync_phase: 'PREPARING', pending_submission_id: 'fixed-input' }
    const preparing = controller.refresh(); await flushPromises()
    expect(mocks.api.upload).toHaveBeenCalledTimes(4)
    controller.onEvent({ task_id: manifest.task_id, state_version: state.state_version, sync_phase: 'PREPARING' })
    release(); await preparing; await flushPromises()
    expect(mocks.api.upload).toHaveBeenCalledTimes(8)
    expect(mocks.native.mock.calls.filter(([request]) => request.kind === 'capture')).toHaveLength(1)
    expect(mocks.api.post.mock.calls.filter(([action]) => action === 'handoff')).toHaveLength(1)
    expect(mocks.api.upload.mock.calls.every(([, , lease]) => lease.lease_epoch === 1 && lease.client_id === state.client_id && lease.instance_id === state.instance_id)).toBe(true)
  })
})
