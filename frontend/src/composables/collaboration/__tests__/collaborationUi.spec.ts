import { describe, expect, it, vi } from 'vitest'
import { computed, proxyRefs, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import zh from '@/locales/zh.json'
import { collaborationPresentation, openCollaborationView } from '../useCollaborationPresentation'
import { collaborationReview } from '../review'
import type { LocalCollaboration } from '../useLocalCollaboration'
import type { CollaborationManifest, CollaborationState, LocalCollaborationStatus } from '@/types/collaboration'
import LocalCollaborationPanel from '@/components/collaboration/LocalCollaborationPanel.vue'
import CollaborationInputStatus from '@/components/collaboration/CollaborationInputStatus.vue'
import CollaborationEntry from '@/components/collaboration/CollaborationEntry.vue'
vi.mock('@/components/collaboration/CodeComparison.vue', () => ({ default: { props: ['leftLabel', 'rightLabel'], template: '<section class="diff-stub">{{leftLabel}} / {{rightLabel}}</section>' } }))

function fixture() {
  const repositories = ['dsh', 'repo'].map((id, index) => ({ task_repository_id: id, repository_id: id, repo_slug: id, rel_path: id, repo_url: `https://example.test/${id}.git`, branch_name: index ? 'main' : 'master', base_commit_sha: id,
    files: [{ path: 'shared.txt', sha256: 'old', size: 3, mode: '100644' as const }] }))
  const input: CollaborationManifest = { protocol_version: 1, snapshot_id: 'start', task_id: 'task', workspace_revision: 1, session_generation: 1, session_revision: 1, repository_set_digest: 'digest', source: 'INITIAL', repositories }
  const cloud: CollaborationManifest = { ...input, snapshot_id: 'final', source: 'AGENT_OUTPUT', repositories: repositories.map(repo => ({ ...repo, files: [{ ...repo.files[0]!, sha256: 'agent' }] })) }
  const local = ref<LocalCollaborationStatus>({ task_id: 'task', directory_mode: 'MAPPED', baseline: cloud, received: cloud, manifest: cloud, state: 'READY', conflicts: [], local_changes: [], repositories: repositories.map(repo => ({ ...repo, mapped_repo_root: `G:/${repo.repo_slug}`, local_worktree_path: `G:/${repo.repo_slug}` })) })
  const state = ref<CollaborationState>({ ...cloud, enabled: true, sync_phase: 'READY', state_version: 1, lease_epoch: 1, binding_id: 'binding', input_snapshot_id: 'start', progress_snapshot_id: null, driver_connected: true, conflicts: [] })
  const model = {
    state, local, input: ref(input), cloud: ref<CollaborationManifest | null>(cloud), available: true, supported: ref(true), enabled: ref(true), driver: ref(true), remoteSender: ref(false), phase: computed(() => state.value.sync_phase),
    conflicts: computed(() => local.value.conflicts || []), error: ref(''), busy: ref(false), blocked: ref(false), loading: ref(false), preparationRequired: ref(false), mappingChecks: ref([]), mappings: ref({}),
    activity: ref({ direction: '', done: 0, total: 0, bytes: 0, totalBytes: 0 }), progressive: ref(false), operationStage: ref(''), operationSeconds: ref(0),
    view: ref({ page: 'files', tab: 'all', pair: 'auto', selected: '', selectedConflicts: [] as string[], conflictSetId: '' }),
    restore: vi.fn(), recover: vi.fn(), claimDriver: vi.fn(), listBackups: vi.fn().mockResolvedValue({ backups: [] }), checkMappings: vi.fn(), selectMapping: vi.fn(), readText: vi.fn().mockResolvedValue('text'),
  }
  const controller = model as unknown as LocalCollaboration
  return { controller, model, state, local, input, cloud }
}
const global = () => ({ plugins: [createI18n({ legacy: false, locale: 'zh', messages: { zh } })], stubs: { CodeComparison: { props: ['leftLabel', 'rightLabel'], template: '<section class="diff-stub">{{leftLabel}} / {{rightLabel}}</section>' } } })

describe('local collaboration presentation and review', () => {
  it('shows offline instead of ready, excludes inaccessible local counts, and keeps drafts actionable', () => {
    const { controller, model, state } = fixture()
    state.value.driver_connected = false
    model.blocked.value = true
    const ui = collaborationPresentation(proxyRefs(controller))
    expect(ui).toMatchObject({ key: 'offline', localAvailable: false, canRestore: false })
    const input = mount(CollaborationInputStatus, { props: { controller }, global: global() })
    expect(input.text()).toContain('本地连接已断开')
    expect(input.text()).not.toContain('已启用')
    input.unmount()
    state.value.driver_connected = true
    model.local.value.state = 'RECOVERY_REQUIRED'
    expect(collaborationPresentation(proxyRefs(controller))).toMatchObject({ key: 'error', inputKey: 'error', localAvailable: false, canRestore: false })
  })
  it('keeps the browser sender enabled without implying it can write local files', () => {
    const { controller, model } = fixture()
    model.driver.value = false; model.remoteSender.value = true
    expect(collaborationPresentation(proxyRefs(controller))).toMatchObject({ key: 'device', inputKey: '', localAvailable: false, canRestore: false })
  })
  it('retains both repositories in this-round diffs after delivery has aligned local and cloud files', () => {
    const { controller } = fixture()
    const review = collaborationReview(proxyRefs(controller), true)
    expect(review.files).toHaveLength(2)
    expect(new Set(review.files.map(file => file.key)).size).toBe(2)
    expect(review.files.every(file => file.kind === 'cloud' && file.delivered)).toBe(true)
  })
  it('does not render a missing cloud manifest as every file being deleted', () => {
    const { controller, model, local } = fixture()
    model.cloud.value = null; local.value.target = undefined
    const review = collaborationReview(proxyRefs(controller), true)
    expect(review.cloudKnown).toBe(false)
    expect(review.files).toEqual([])
  })
  it('has one entry, no routine composer notice, and opens the current local edits directly', async () => {
    const { controller, local } = fixture()
    const entry = mount(CollaborationEntry, { props: { controller }, global: global() })
    const input = mount(CollaborationInputStatus, { props: { controller }, global: global() })
    expect(entry.findAll('button')).toHaveLength(1)
    expect(entry.text()).toContain('本地协同')
    expect(input.find('[role="status"]').exists()).toBe(false)
    local.value.local_changes = [{ task_repository_id: 'dsh', path: 'extra.txt', base: null, local: { path: 'extra.txt', sha256: 'extra', size: 5, mode: '100644' } }]
    await entry.trigger('click')
    expect(controller.view.value.tab).toBe('local')
    expect(entry.emitted('open')).toHaveLength(1)
    entry.unmount(); input.unmount()
  })
  it('selects and confirms only one repository, retains selection on cancel, and never restores a running preview', async () => {
    const { controller, model, state, local, input, cloud } = fixture()
    const conflicts = input.repositories.map((repo, index) => ({ task_repository_id: repo.task_repository_id, path: 'shared.txt', local: { ...repo.files[0]!, sha256: 'human' }, base: repo.files[0], cloud: cloud.repositories[index]!.files[0] }))
    local.value = { ...local.value, conflicts, conflict_set_id: 'set1', manifest: { ...cloud, repositories: cloud.repositories.map(repo => ({ ...repo, files: [{ ...repo.files[0]!, sha256: 'human' }] })) } }
    state.value.sync_phase = 'CONFLICT_PENDING'; model.blocked.value = true
    openCollaborationView(controller)
    const panel = mount(LocalCollaborationPanel, { props: { controller, workspaceId: 'ws' }, global: global(), attachTo: document.body })
    expect(panel.text()).toContain('当前本地 / Agent 版本')
    expect(panel.findAll('input[type=checkbox]').every(input => !(input.element as HTMLInputElement).checked)).toBe(true)
    await panel.get('input[aria-label="选择 dsh/shared.txt"]').setValue(true)
    const button = () => panel.findAll('button').find(button => button.text() === '采用 Agent 版本（1）')!
    await button().trigger('click'); await flushPromises()
    const modal = () => document.querySelector('.confirm-action-modal') || document.querySelector('[role="dialog"]')!
    expect(modal().textContent).toContain('dsh/shared.txt')
    expect(modal().textContent).not.toContain('repo/shared.txt')
    const cancel = [...modal().querySelectorAll('button')].find(button => button.textContent?.trim() === '取消')!
    cancel.click(); await flushPromises()
    expect((panel.get('input[aria-label="选择 dsh/shared.txt"]').element as HTMLInputElement).checked).toBe(true)
    await button().trigger('click'); await flushPromises()
    ;[...modal().querySelectorAll('button')].find(button => button.textContent?.trim() === '备份并替换')!.click()
    await flushPromises()
    expect(controller.restore).toHaveBeenCalledWith([conflicts[0]], 'set1')
    state.value.sync_phase = 'RUNNING'; await flushPromises()
    expect(panel.findAll('input[type=checkbox]')).toHaveLength(0)
    expect(panel.text()).toContain('待 Agent 结束后处理')
    panel.unmount()
  })
})
