import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, defineComponent, nextTick, proxyRefs, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import zh from '@/locales/zh.json'
import api from '@/utils/api'
import { collaborationPresentation, openCollaborationView } from '../useCollaborationPresentation'
import { collaborationReview } from '../review'
import type { LocalCollaboration } from '../useLocalCollaboration'
import type { CollaborationManifest, CollaborationState, LocalCollaborationStatus } from '@/types/collaboration'
import LocalCollaborationPanel from '@/components/collaboration/LocalCollaborationPanel.vue'
import RepositoryUpdateChanges from '@/components/collaboration/RepositoryUpdateChanges.vue'
import CollaborationInputStatus from '@/components/collaboration/CollaborationInputStatus.vue'
import CollaborationEntry from '@/components/collaboration/CollaborationEntry.vue'
import CollaborationHeader from '@/components/collaboration/CollaborationHeader.vue'
import CollaborationActions from '@/components/collaboration/CollaborationActions.vue'
import CollaborationHistory from '@/components/collaboration/CollaborationHistory.vue'
vi.mock('@/components/collaboration/CodeComparison.vue', () => ({ default: { props: ['leftLabel', 'rightLabel'], template: '<section class="diff-stub">{{leftLabel}} / {{rightLabel}}</section>' } }))
vi.mock('@/components/collaboration/RepositoryUpdatePanel.vue', () => ({ default: { template: '<section class="repository-update-stub" />' } }))
vi.mock('@/utils/api', () => ({ default: { get:vi.fn().mockResolvedValue({ data:{ repositories:[], plan:null } }) } }))
beforeEach(() => vi.mocked(api.get).mockResolvedValue({ data:{ repositories:[], plan:null, items:[] } }))

function fixture() {
  const repositories = ['dsh', 'repo'].map((id, index) => ({ task_repository_id: id, repository_id: id, repo_slug: id, rel_path: id, repo_url: `https://example.test/${id}.git`, branch_name: index ? 'main' : 'master', base_commit_sha: id,
    files: [{ path: 'shared.txt', sha256: 'old', size: 3, mode: '100644' as const }] }))
  const input: CollaborationManifest = { protocol_version: 1, snapshot_id: 'start', task_id: 'task', workspace_revision: 1, session_generation: 1, session_revision: 1, repository_set_digest: 'digest', source: 'INITIAL', repositories }
  const cloud: CollaborationManifest = { ...input, snapshot_id: 'final', source: 'AGENT_OUTPUT', repositories: repositories.map(repo => ({ ...repo, files: [{ ...repo.files[0]!, sha256: 'agent' }] })) }
  const local = ref<LocalCollaborationStatus>({ task_id: 'task', directory_mode: 'MAPPED', baseline: cloud, received: cloud, manifest: cloud, state: 'READY', conflicts: [], local_changes: [], repositories: repositories.map(repo => ({ ...repo, mapped_repo_root: `G:/${repo.repo_slug}`, local_worktree_path: `G:/${repo.repo_slug}` })) })
  const state = ref<CollaborationState>({ ...cloud, enabled: true, sync_phase: 'READY', state_version: 1, lease_epoch: 1, binding_id: 'binding', input_snapshot_id: 'start', progress_snapshot_id: null, driver_connected: true, conflicts: [] })
  const model = {
    reviewBaseline: ref(input),
    loadReview: vi.fn(), reviewRunning: ref(false), reviewLoading: ref(false), reviewError: ref(''),
    participating: ref(true), leaving: ref(false), receivedOnce: ref(false), leave: vi.fn(), receiveOnce: vi.fn(), enable: vi.fn(), state, local, input: ref(input), cloud: ref<CollaborationManifest | null>(cloud), available: true, supported: ref(true), enabled: ref(true), driver: ref(true), remoteSender: ref(false), phase: computed(() => state.value.sync_phase),
    conflicts: computed(() => local.value.conflicts || []), error: ref(''), busy: ref(false), blocked: ref(false), loading: ref(false), preparationRequired: ref(false), mappingChecks: ref([]), mappings: ref({}),
    activity: ref({ direction: '', done: 0, total: 0, bytes: 0, totalBytes: 0 }), progressive: ref(false), operationStage: ref(''), operationSeconds: ref(0),
    view: ref({ page: 'files', tab: 'all', pair: 'auto', selected: '', selectedConflicts: [] as string[], conflictSetId: '' }),
    restore: vi.fn(), recover: vi.fn(), cancelPreparation: vi.fn(), claimDriver: vi.fn(), listBackups: vi.fn().mockResolvedValue({ backups: [] }), checkMappings: vi.fn(), selectMapping: vi.fn(), readText: vi.fn().mockResolvedValue('text'), setProgressive: vi.fn(), refresh: vi.fn(), refreshResults:vi.fn(),
  }
  const controller = model as unknown as LocalCollaboration
  return { controller, model, state, local, input, cloud }
}
const global = () => ({ plugins: [createI18n({ legacy: false, locale: 'zh', messages: { zh } })], stubs: { CodeComparison: { props: ['leftLabel', 'rightLabel'], template: '<section class="diff-stub">{{leftLabel}} / {{rightLabel}}</section>' } } })

describe('local collaboration presentation and review', () => {
  it('defaults to cumulative differences even when the latest turn made no edits', async () => {
    const { controller, model, cloud } = fixture()
    model.participating.value = false
    model.input.value = cloud
    expect(collaborationReview(proxyRefs(controller), false).files).toHaveLength(2)
    expect(collaborationReview(proxyRefs(controller), false, 'round').files).toHaveLength(0)
    const panel = mount(LocalCollaborationPanel, { props:{ controller, workspaceId:'ws', taskId:'task' }, global:global() })
    expect(panel.text()).toContain('累计差异')
    expect(panel.findAll('.file')).toHaveLength(2)
    expect(panel.get('.diff-stub').text()).toBe('远端基线 / 任务版本')
    panel.unmount()
  })
  it('keeps unsent local edits out of cumulative task results and exposes them in the round view', async () => {
    const { controller, local, cloud } = fixture()
    local.value.manifest = { ...cloud, repositories: cloud.repositories.map(repo => ({ ...repo, files: [
      { ...repo.files[0]!, sha256:'human' }, { path:'local-only.txt', sha256:'new', size:3, mode:'100644' },
    ] })) }
    const cumulative = collaborationReview(proxyRefs(controller), true)
    expect(cumulative.files).toHaveLength(2)
    expect(cumulative.files.every(file => file.kind === 'cloud' && file.right?.sha256 === 'agent')).toBe(true)
    const round = collaborationReview(proxyRefs(controller), true, 'round')
    expect(round.files).toHaveLength(4)
    expect(round.files.every(file => file.kind === 'local')).toBe(true)
    const panel = mount(LocalCollaborationPanel, { props:{ controller, workspaceId:'ws', taskId:'task' }, global:global() })
    expect(panel.find('.file-filters').exists()).toBe(false)
    expect(panel.findAll('.file')).toHaveLength(2)
    await panel.get('.diff-purpose-tabs button:nth-child(2)').trigger('click')
    expect(panel.findAll('.file')).toHaveLength(4)
    expect(panel.findAll('.file-filters button').find(button => button.text().startsWith('本地修改'))!.get('small').text()).toBe('4')
    expect(panel.get('.human-records-link').text()).toBe('人工修改记录')
    await panel.get('.human-records-link').trigger('click')
    expect(controller.view.value.page).toBe('history')
    panel.unmount()
  })
  it('opens remote updates as a separate workflow from the two diff purposes and returns to the same purpose', async () => {
    const { controller } = fixture()
    const panel = mount(LocalCollaborationPanel, { props:{ controller, workspaceId:'ws', taskId:'task' }, global:global() })
    await flushPromises()
    expect(panel.get('.diff-purpose-tabs').text()).toBe('累计差异本轮差异')
    expect(panel.find('.diff-scope-bar [role="combobox"]').exists()).toBe(false)
    await panel.get('.diff-purpose-tabs button:nth-child(2)').trigger('click')
    await panel.get('.baseline-entry').trigger('click')
    expect(controller.view.value.page).toBe('updates')
    expect(panel.find('.diff-purpose-tabs').exists()).toBe(false)
    expect(panel.find('.file-filters').exists()).toBe(false)
    expect(panel.get('.workflow-title h3').text()).toBe('更新任务基线')
    expect(panel.get('.check-remote').text()).toBe('检查远端更新')
    await panel.get('.back-link').trigger('click')
    expect(controller.view.value.page).toBe('files')
    expect(panel.get('.diff-purpose-tabs button[aria-pressed="true"]').text()).toBe('本轮差异')
    controller.view.value.tab = 'local'
    await panel.get('.baseline-entry').trigger('click')
    panel.getComponent(RepositoryUpdateChanges).vm.$emit('applied'); await nextTick()
    expect(controller.view.value.page).toBe('files')
    expect(controller.view.value.tab).toBe('all')
    expect(panel.get('.diff-purpose-tabs button[aria-pressed="true"]').text()).toBe('累计差异')
    expect(controller.refreshResults).toHaveBeenCalledOnce()
    panel.unmount()
  })
  it('shows both repositories and diffs before connecting, without showing another device conflicts', async () => {
    const { controller, model, state } = fixture()
    model.participating.value = false; model.enabled.value = false; model.driver.value = false
    state.value.conflicts = [{ task_repository_id: 'dsh', path: 'shared.txt' } as any]
    expect(collaborationPresentation(proxyRefs(controller))).toMatchObject({ setup: false, localAvailable: false })
    expect(collaborationReview(proxyRefs(controller), false).files.every(file => file.kind === 'cloud')).toBe(true)
    const panel = mount(LocalCollaborationPanel, { props: { controller, workspaceId: 'ws', taskId: 'task' }, global: global() })
    expect(panel.findAll('.file')).toHaveLength(2)
    expect(panel.findAll('.file-row button')).toHaveLength(2)
    expect(panel.find('.diff-stub').exists()).toBe(true)
    expect(panel.find('.repository-settings').exists()).toBe(false)
    expect(model.enable).not.toHaveBeenCalled()
    panel.unmount()
  })
  it('keeps one pair of session actions above every tab and routes missing mappings to settings', async () => {
    const { controller, model } = fixture()
    model.participating.value = false; model.enabled.value = false
    const host = mount(defineComponent({
      components: { CollaborationHeader, CollaborationActions, LocalCollaborationPanel },
      setup: () => ({ controller }),
      template: '<header><CollaborationHeader :controller="controller"/><CollaborationActions :controller="controller"/></header><LocalCollaborationPanel :controller="controller" workspace-id="ws" task-id="task"/>',
    }), { global: global() })
    const receive = () => host.findAll('button').filter(button => button.text() === '接收最新代码')
    const connect = () => host.findAll('input[role="switch"][aria-label="本地协同"]')
    expect(receive()).toHaveLength(1); expect(connect()).toHaveLength(1)
    await receive()[0]!.trigger('click')
    expect(controller.view.value.page).toBe('settings')
    expect(model.receiveOnce).not.toHaveBeenCalled()
    expect(receive()).toHaveLength(1); expect(connect()).toHaveLength(1)
    expect(host.find('.repository-settings .btn-primary').exists()).toBe(false)
    model.mappings.value = { dsh: { local_path: 'G:/dsh' }, repo: { local_path: 'G:/repo' } }
    await connect()[0]!.setValue(true)
    expect(model.enable).toHaveBeenCalledOnce()
    expect((connect()[0]!.element as HTMLInputElement).checked).toBe(false)
    await receive()[0]!.trigger('click')
    expect(model.receiveOnce).toHaveBeenCalledOnce()
    model.enabled.value = true; await nextTick()
    expect(connect()[0]!.attributes('disabled')).toBeDefined()
    host.unmount()
  })
  it('keeps the collaboration switch on until disconnect succeeds and preserves the current tab', async () => {
    const { controller, model } = fixture()
    model.view.value.page = 'settings'
    const actions = mount(CollaborationActions, { props: { controller }, global: global(), attachTo: document.body })
    const toggle = actions.get('input[aria-label="本地协同"]')
    const checked = () => (toggle.element as HTMLInputElement).checked
    const modalButton = (text: string) => [...document.querySelectorAll<HTMLButtonElement>('.modal-overlay .modal button')].find(button => button.textContent?.trim() === text)!
    await toggle.setValue(false); await flushPromises()
    expect(checked()).toBe(true)
    expect(model.leave).not.toHaveBeenCalled()
    modalButton('取消').click(); await flushPromises()
    expect(checked()).toBe(true)
    expect(model.view.value.page).toBe('settings')
    await toggle.setValue(false); await flushPromises()
    model.leave.mockResolvedValueOnce(false)
    modalButton('断开本地协同').click(); await flushPromises()
    expect(checked()).toBe(true)
    expect(document.querySelector('.modal-overlay .modal')).not.toBeNull()
    model.leave.mockImplementationOnce(async () => { model.participating.value = false; return true })
    modalButton('断开本地协同').click(); await flushPromises()
    expect(checked()).toBe(false)
    expect(model.leave).toHaveBeenCalledTimes(2)
    expect(model.view.value.page).toBe('settings')
    actions.unmount()
  })
  it('keeps errors in the header across tabs and exposes full details on demand', async () => {
    const { controller, model } = fixture()
    model.error.value = '本地仓库未通过启用检查，请处理仓库问题后重试。'
    const header = mount(CollaborationHeader, { props: { controller }, global: global(), attachTo: document.body })
    const panel = mount(LocalCollaborationPanel, { props: { controller, workspaceId: 'ws', taskId: 'task' }, global: global() })
    expect(header.get('[role="status"]').text()).toContain(model.error.value)
    expect(panel.text()).not.toContain(model.error.value)
    await header.get('button[aria-label="查看错误详情"]').trigger('click'); await flushPromises()
    expect(document.querySelector('.header-errors')?.textContent).toContain(model.error.value)
    controller.view.value.page = 'settings'; await nextTick()
    expect(header.get('[role="status"]').text()).toContain(model.error.value)
    expect(panel.find('.error-details').exists()).toBe(false)
    model.error.value = ''; await header.setProps({ error: '无法启动 IDE' })
    expect(header.get('[role="status"]').text()).toContain('无法启动 IDE')
    header.unmount(); panel.unmount()
  })
  it('recovers a participating session from the header without creating another binding', async () => {
    const { controller, model } = fixture()
    model.error.value = 'delivery failed'
    model.mappings.value = { dsh: { local_path: 'G:/dsh' }, repo: { local_path: 'G:/repo' } }
    const actions = mount(CollaborationActions, { props: { controller }, global: global() })
    await actions.get('.session-button').trigger('click')
    expect(model.recover).toHaveBeenCalledOnce()
    expect(model.enable).not.toHaveBeenCalled()
    actions.unmount()
  })
  it('keeps auto-receive beside refresh as an accessible switch only on the participating desktop', async () => {
    const { controller, model } = fixture()
    const actions = mount(CollaborationActions, { props: { controller }, global: global() })
    const toggle = actions.get('input[role="switch"][aria-label="执行中自动接收修改"]')
    expect(toggle.attributes('aria-label')).toBe('执行中自动接收修改')
    await toggle.setValue(true)
    expect(model.setProgressive).toHaveBeenCalledWith(true)
    await actions.get('button').trigger('click')
    expect(model.refresh).toHaveBeenCalledOnce()
    model.busy.value = true; await nextTick()
    expect(toggle.attributes('disabled')).toBeDefined()
    model.busy.value = false; model.driver.value = false; await nextTick()
    expect(actions.find('[role="switch"][aria-label="执行中自动接收修改"]').exists()).toBe(false)
    model.driver.value = true; model.participating.value = false; await nextTick()
    expect(actions.find('[role="switch"][aria-label="执行中自动接收修改"]').exists()).toBe(false)
    actions.unmount()
  })
  it('switches history inside the panel while keeping every navigation tab and the current file selection', async () => {
    const { controller } = fixture()
    const panel = mount(LocalCollaborationPanel, { props: { controller, workspaceId: 'ws', taskId: 'task' }, global: {
      ...global(), stubs: { ...global().stubs, CollaborationHistory: { props: ['workspaceId', 'taskId'], template: '<section>历史记录内容</section>' } },
    } })
    const selected = controller.view.value.selected
    const tabs = () => panel.findAll('.drawer-subnav button')
    await tabs().find(button => button.text() === '协作历史')!.trigger('click')
    expect(panel.findComponent(CollaborationHistory).props()).toMatchObject({ workspaceId: 'ws', taskId: 'task' })
    expect(panel.text()).toContain('历史记录内容')
    expect(tabs()).toHaveLength(4)
    expect(tabs().find(button => button.classes().includes('active'))?.text()).toBe('协作历史')
    expect(panel.emitted('history')).toBeUndefined()
    await tabs().find(button => button.text() === '变更差异')!.trigger('click')
    expect(panel.findComponent(CollaborationHistory).exists()).toBe(false)
    expect(controller.view.value.selected).toBe(selected)
    panel.unmount()
  })
  it('shows real collaboration state and animates only ongoing work', async () => {
    const { controller, model, state } = fixture()
    const header = mount(CollaborationHeader, { props: { controller }, global: global() })
    expect(header.get('[role="status"]').text()).toBe('已同步到本地')
    expect(header.classes()).not.toContain('is-active')
    expect(header.text()).toContain('2 个仓库')
    expect(header.text()).not.toMatch(/Desktop Bridge|127\.0\.0\.1|8ms|已链接/)
    for (const [phase, text, active] of [['RUNNING', 'Agent 正在执行', true], ['WAITING_HITL', 'Agent 等待确认', false], ['SETTLING', '正在同步并核对代码', true]] as const) {
      state.value.sync_phase = phase; await nextTick()
      expect(header.get('[role="status"]').text()).toBe(text)
      expect(header.classes().includes('is-active')).toBe(active)
    }
    state.value.driver_connected = false; await nextTick()
    expect(header.get('[role="status"]').text()).toBe('本地连接已断开')
    expect(header.classes()).toContain('warning')
    expect(header.classes()).not.toContain('is-active')
    state.value.driver_connected = true; model.error.value = 'failed'; await nextTick()
    expect(header.get('[role="status"]').text()).toContain('failed')
    expect(header.classes()).not.toContain('is-active')
    model.error.value = ''; model.participating.value = false; model.enabled.value = false; state.value.repositories = []; await nextTick()
    expect(header.get('[role="status"]').text()).toBe('未启用本地协同')
    expect(header.text()).not.toContain('个仓库')
    expect(header.classes()).not.toContain('is-active')
    header.unmount()
  })
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
    const review = collaborationReview(proxyRefs(controller), true, 'round')
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
    expect(entry.text()).toContain('任务代码')
    expect(input.find('[role="status"]').exists()).toBe(false)
    local.value.local_changes = [{ task_repository_id: 'dsh', path: 'extra.txt', base: null, local: { path: 'extra.txt', sha256: 'extra', size: 5, mode: '100644' } }]
    await entry.trigger('click')
    expect(controller.view.value.tab).toBe('local')
    expect(entry.emitted('open')).toHaveLength(1)
    expect(input.find('[role="status"]').exists()).toBe(false)
    entry.unmount(); input.unmount()
  })
  it('selects and confirms only one repository, retains selection on cancel, and never restores a running preview', async () => {
    const { controller, model, state, local, input, cloud } = fixture()
    const conflicts = input.repositories.map((repo, index) => ({ task_repository_id: repo.task_repository_id, path: 'shared.txt', local: { ...repo.files[0]!, sha256: 'human' }, base: repo.files[0], cloud: cloud.repositories[index]!.files[0] }))
    local.value = { ...local.value, conflicts, conflict_set_id: 'set1', manifest: { ...cloud, repositories: cloud.repositories.map(repo => ({ ...repo, files: [{ ...repo.files[0]!, sha256: 'human' }] })) } }
    state.value.sync_phase = 'CONFLICT_PENDING'; model.blocked.value = true
    const notice = mount(CollaborationInputStatus, { props: { controller }, global: global() })
    expect(notice.get('[role="status"]').text()).toContain('2 个文件待处理')
    await notice.get('button').trigger('click')
    expect(controller.view.value.tab).toBe('conflicts')
    expect(notice.emitted('open')).toHaveLength(1)
    notice.unmount()
    openCollaborationView(controller)
    const panel = mount(LocalCollaborationPanel, { props: { controller, workspaceId: 'ws', taskId: 'task' }, global: global(), attachTo: document.body })
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

describe('composer feedback only when attention is needed', () => {
  afterEach(() => { vi.useRealTimers() })

  function preparing() {
    vi.useFakeTimers()
    const context = fixture()
    context.state.value.sync_phase = 'PREPARING'
    context.model.blocked.value = true
    const wrapper = mount(CollaborationInputStatus, { props: { controller: context.controller }, global: global() })
    return { ...context, wrapper }
  }

  it('does not show preparation or cancellation during a normal send, including after completion', async () => {
    const { wrapper, state, model } = preparing()
    await vi.advanceTimersByTimeAsync(3000)
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    expect(wrapper.find('button').exists()).toBe(false)
    state.value.sync_phase = 'RUNNING'; model.blocked.value = false
    await nextTick()
    await vi.advanceTimersByTimeAsync(10000)
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('offers only details after a long wait and never allows cancelling preparation', async () => {
    const { wrapper, model, state } = preparing()
    await vi.advanceTimersByTimeAsync(7999)
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    expect(wrapper.get('[role="status"]').text()).toContain('发送准备耗时较长')
    expect(wrapper.find('[aria-label="取消本轮准备"]').exists()).toBe(false)
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('open')).toHaveLength(1)
    expect(model.cancelPreparation).not.toHaveBeenCalled()
    state.value.sync_phase = 'RUNNING'; model.blocked.value = false
    await nextTick()
    expect(wrapper.find('button').exists()).toBe(false)
    wrapper.unmount()
  })

  it('counts consecutive sync stages together and opens details when cancellation is unavailable', async () => {
    const { wrapper, state } = preparing()
    await vi.advanceTimersByTimeAsync(4000)
    state.value.sync_phase = 'SETTLING'
    await nextTick()
    await vi.advanceTimersByTimeAsync(4000)
    expect(wrapper.get('[role="status"]').text()).toContain('代码同步耗时较长')
    expect(wrapper.find('[aria-label="取消本轮准备"]').exists()).toBe(false)
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('open')).toHaveLength(1)
    wrapper.unmount()
  })

  it('shows errors immediately and cancels pending feedback timers', async () => {
    const { wrapper, model } = preparing()
    await vi.advanceTimersByTimeAsync(100)
    model.error.value = 'Sync failed'
    await nextTick()
    expect(wrapper.get('[role="status"]').text()).toContain('代码尚未接收完成')
    expect(wrapper.find('[aria-label="取消本轮准备"]').exists()).toBe(false)
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('open')).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(10000)
    expect(wrapper.text()).not.toContain('耗时较长')
    wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('disposes delayed feedback when leaving the composer', () => {
    const { wrapper } = preparing()
    wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('starts a fresh wait when switching tasks', async () => {
    vi.useFakeTimers()
    const { controller, state, model } = fixture()
    state.value.sync_phase = 'PREPARING'; model.blocked.value = true
    const taskId = ref('task-a')
    const wrapper = mount(defineComponent({
      components: { CollaborationInputStatus },
      setup: () => ({ taskId, controller }),
      template: '<CollaborationInputStatus :key="taskId" :controller="controller" />',
    }), { global: global() })
    await vi.advanceTimersByTimeAsync(7000)
    taskId.value = 'task-b'
    await nextTick()
    await vi.advanceTimersByTimeAsync(1000)
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    await vi.advanceTimersByTimeAsync(7000)
    expect(wrapper.get('[role="status"]').text()).toContain('发送准备耗时较长')
    wrapper.unmount()
  })
})
