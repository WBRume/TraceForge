import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest'
import { effectScope, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import zh from '@/locales/zh.json'
import api from '@/utils/api'
import { useRepositoryUpdates } from '../useRepositoryUpdates'
import { notifyRepositoryUpdate, type UpdateFileDetail, type UpdatePlan } from '@/services/repositoryUpdates'
import RepositoryUpdateFile from '@/components/collaboration/RepositoryUpdateFile.vue'
import RepositoryUpdatePanel from '@/components/collaboration/RepositoryUpdatePanel.vue'
import RepositoryUpdateChanges from '@/components/collaboration/RepositoryUpdateChanges.vue'
import RepositoryUpdateEntry from '@/components/collaboration/RepositoryUpdateEntry.vue'
import CodeComparison from '@/components/collaboration/CodeComparison.vue'
import type { LocalCollaboration } from '../useLocalCollaboration'

vi.mock('@/utils/api', () => ({ default: { get:vi.fn(), post:vi.fn() } }))
vi.mock('@/components/diff/MonacoDiffViewer.vue', () => ({ default: { props:['original','modified'], template:'<section>{{ original }} / {{ modified }}</section>' } }))
const plan = (state: UpdatePlan['state'] = 'CONFLICTS'): UpdatePlan => ({ id:'plan', version:2, state, repositories:[{
  id:'repo', name:'api', branch:'release/2.x', baseline:'oldsha', base:'basesha', target:'newsha', has_output:true, mode:'MERGE',
  files:[{ path:'shared.txt', conflict:state === 'CONFLICTS', was_conflict:true, resolved:state === 'READY' }],
}] })
const detail = (): UpdateFileDetail => ({ path:'shared.txt', conflict:true, was_conflict:true, resolved:false, version:2,
  versions:{ base:{ exists:true, text:'base', binary:false, mode:'100644' }, task:{ exists:false, text:'', binary:false, mode:null },
    remote:{ exists:true, text:'remote update', binary:false, mode:'100644' }, result:{ exists:true, text:'candidate', binary:false, mode:'100644' } } })
const global = { plugins:[createI18n({ legacy:false, locale:'zh', messages:{ zh } })] }
const scopes: ReturnType<typeof effectScope>[] = []
beforeEach(() => vi.mocked(window.matchMedia).mockReturnValue({ matches:false, addEventListener:vi.fn(), removeEventListener:vi.fn() } as unknown as MediaQueryList))
function model() { const scope = effectScope(); scopes.push(scope); return scope.run(() => useRepositoryUpdates(() => ({ workspaceId:'ws', taskId:'task' })))! }
afterEach(() => { scopes.splice(0).forEach(scope => scope.stop()); vi.clearAllMocks() })

describe('repository update review', () => {
  it('keeps update notices on the workflow entry and removes them from repository settings', async () => {
    vi.mocked(api.get).mockImplementation(async url => ({ data:String(url).endsWith('/file') ? detail() : { repositories:[], plan:plan(), can_update:true } }))
    const shared = model()
    const entry = mount(RepositoryUpdateEntry, { props:{ model:shared }, global })
    const settings = mount(RepositoryUpdatePanel, { props:{ model:shared }, global })
    await flushPromises()
    expect(entry.text()).toContain('更新任务基线')
    expect(entry.text()).toContain('1 个冲突')
    expect(settings.text()).not.toMatch(/冲突|检查远端更新|查看差异|待审查|代码已更新/)
    await entry.trigger('click')
    expect(entry.emitted('open')).toHaveLength(1)
    expect(api.post).not.toHaveBeenCalled()
    vi.mocked(api.get).mockImplementation(async url => ({ data:String(url).endsWith('/file') ? detail() : { repositories:[], plan:{ ...plan('APPLIED'), version:3 } } }))
    notifyRepositoryUpdate({ task_id:'task', version:3 }); await flushPromises()
    expect(entry.find('small').exists()).toBe(false)
    expect(settings.text()).not.toContain('任务代码已更新')
    entry.unmount(); settings.unmount()
  })
  it('starts checking remote branches only from the dedicated workflow action', async () => {
    vi.mocked(api.get).mockResolvedValue({ data:{ can_update:true, repositories:[{ id:'repo', name:'api', branch:'release/2.x', baseline:'oldbaseline' }], plan:null } })
    const shared = model()
    const wrapper = mount(RepositoryUpdateChanges, { props:{ model:shared }, global })
    await flushPromises()
    expect(api.post).not.toHaveBeenCalled()
    expect(wrapper.get('.baseline-repository').text()).toContain('release/2.x')
    expect(wrapper.find('.file-filters').exists()).toBe(false)
    vi.mocked(api.post).mockResolvedValue({ data:plan() })
    await wrapper.get('.check-remote').trigger('click'); await flushPromises()
    expect(api.post).toHaveBeenCalledWith(expect.stringContaining('/repository-updates/prepare'), expect.anything(), expect.anything())
    wrapper.unmount()
  })
  it('reuses the two-pane comparison with the remote baseline and confirms task edits explicitly', async () => {
    const wrapper = mount(RepositoryUpdateFile, { props:{ detail:detail(), busy:false, editable:true }, global })
    for (const label of ['任务版本','远端版本 · 最新基线']) expect(wrapper.text()).toContain(label)
    expect(wrapper.text()).not.toContain('共同基线')
    expect(wrapper.find('textarea').exists()).toBe(false)
    expect(wrapper.getComponent(CodeComparison).props()).toMatchObject({ leftText:'remote update', rightText:'', editable:true })
    wrapper.getComponent(CodeComparison).vm.$emit('update:rightText', 'reviewed result'); await flushPromises()
    expect(wrapper.emitted('resolve')).toBeUndefined()
    await wrapper.findAll('button').find(b => b.text() === '确认此文件结果')!.trigger('click')
    expect(wrapper.emitted('resolve')?.[0]).toEqual(['edit','reviewed result',2])
    await wrapper.findAll('button').find(b => b.text() === '按任务版本删除')!.trigger('click')
    expect(wrapper.emitted('resolve')?.[1]).toEqual(['task',undefined,2])
    wrapper.unmount()
  })
  it('keeps binary conflicts out of the text editor', () => {
    const value = detail(); value.versions.remote.binary = true
    const wrapper = mount(RepositoryUpdateFile, { props:{ detail:value, busy:false, editable:true }, global })
    expect(wrapper.find('textarea').exists()).toBe(false)
    expect(wrapper.text()).toContain('使用远端版本')
    wrapper.unmount()
  })
  it('preserves a draft when another reviewer changes the preview and requires reconciliation', async () => {
    const wrapper = mount(RepositoryUpdateFile, { props:{ detail:detail(), busy:false, editable:true }, global })
    wrapper.getComponent(CodeComparison).vm.$emit('update:rightText', 'my unsaved resolution'); await flushPromises()
    const next = detail(); next.version = 3; next.versions.result.text = 'other reviewer result'
    await wrapper.setProps({ detail:next })
    expect(wrapper.getComponent(CodeComparison).props('rightText')).toBe('my unsaved resolution')
    expect(wrapper.findAll('button').find(b => b.text() === '确认此文件结果')!.attributes('disabled')).toBeDefined()
    await wrapper.findAll('button').find(b => b.text() === '继续使用我的编辑')!.trigger('click')
    await wrapper.findAll('button').find(b => b.text() === '确认此文件结果')!.trigger('click')
    expect(wrapper.emitted('resolve')?.[0]).toEqual(['edit','my unsaved resolution',3])
    wrapper.unmount()
  })
  it('refreshes on task WebSocket events, filters other tasks and releases its listener', async () => {
    vi.mocked(api.get).mockImplementation(async url => ({ data:String(url).endsWith('/file') ? detail() : { repositories:[], plan:plan() } }))
    const scope = effectScope()
    scope.run(() => useRepositoryUpdates(() => ({ workspaceId:'ws', taskId:'task' })))
    await flushPromises()
    const before = vi.mocked(api.get).mock.calls.length
    notifyRepositoryUpdate({ task_id:'other', version:3 }); await flushPromises()
    expect(api.get).toHaveBeenCalledTimes(before)
    notifyRepositoryUpdate({ task_id:'task', version:3 }); await flushPromises()
    expect(vi.mocked(api.get).mock.calls.length).toBeGreaterThan(before)
    scope.stop()
    const after = vi.mocked(api.get).mock.calls.length
    notifyRepositoryUpdate({ task_id:'task', version:4 }); await flushPromises()
    expect(api.get).toHaveBeenCalledTimes(after)
  })
  it('retains an unconfirmed draft across tab remounts and prevents applying an older saved result', async () => {
    const saved = detail(); saved.conflict = false; saved.resolved = true
    vi.mocked(api.get).mockImplementation(async url => ({ data:String(url).endsWith('/file') ? saved : { repositories:[], plan:plan('READY') } }))
    const shared = model()
    let wrapper = mount(RepositoryUpdateChanges, { props:{ model:shared }, global })
    await flushPromises()
    wrapper.getComponent(CodeComparison).vm.$emit('update:rightText', 'pending edit'); await flushPromises()
    expect(shared.drafts.value['repo:shared.txt']?.text).toBe('pending edit')
    expect(wrapper.findAll('button').find(b => b.text() === '应用到任务代码')!.attributes('disabled')).toBeDefined()
    wrapper.unmount()
    wrapper = mount(RepositoryUpdateChanges, { props:{ model:shared }, global }); await flushPromises()
    expect(wrapper.getComponent(CodeComparison).props('rightText')).toBe('pending edit')
    expect(wrapper.text()).toContain('1 个文件的编辑尚未确认')
    wrapper.unmount()
  })
  it('blocks applying unresolved conflicts and uses an explicit confirmation for a ready result', async () => {
    vi.mocked(api.get).mockImplementation(async url => ({ data:String(url).endsWith('/file') ? detail() : { repositories:[], plan:plan() } }))
    const wrapper = mount(RepositoryUpdateChanges, { props:{ model:model() }, global })
    await flushPromises()
    expect(wrapper.findAll('button').find(b => b.text() === '应用到任务代码')!.attributes('disabled')).toBeDefined()
    vi.mocked(api.get).mockImplementation(async url => ({ data:String(url).endsWith('/file') ? detail() : { repositories:[], plan:{ ...plan('READY'), version:3 } } }))
    notifyRepositoryUpdate({ task_id:'task', version:3 }); await flushPromises()
    await wrapper.findAll('button').find(b => b.text() === '应用到任务代码')!.trigger('click')
    expect(api.post).not.toHaveBeenCalled()
    expect(wrapper.findComponent({ name:'ConfirmActionModal' }).props('show')).toBe(true)
    wrapper.unmount()
  })
  it('refreshes a new operation with a lower version and clears a discarded preview', async () => {
    let current: UpdatePlan | null = { ...plan(), version:9 }
    vi.mocked(api.get).mockImplementation(async url => ({ data:String(url).endsWith('/file') ? detail() : { repositories:[], plan:current } }))
    const scope = effectScope()
    const model = scope.run(() => useRepositoryUpdates(() => ({ workspaceId:'ws', taskId:'task' })))!
    await flushPromises()
    current = { ...plan(), id:'new-plan', version:2 }
    notifyRepositoryUpdate({ task_id:'task', id:'new-plan', version:2 })
    await flushPromises()
    expect(model.plan.value?.id).toBe('new-plan')
    current = null
    notifyRepositoryUpdate({ task_id:'task', id:'new-plan', version:3, state:'DISCARDED' })
    await flushPromises()
    expect(model.plan.value).toBeNull()
    expect(model.detail.value).toBeNull()
    scope.stop()
  })
  it('does not show the previous operation detail while loading the same path in a new preview', async () => {
    let current = plan()
    let finish!: (value: unknown) => void
    vi.mocked(api.get).mockImplementation(async url => {
      if (!String(url).endsWith('/file')) return { data:{ repositories:[], plan:current } }
      if (current.id === 'plan') return { data:detail() }
      return new Promise(resolve => { finish = resolve })
    })
    const shared = model(); await flushPromises()
    expect(shared.detail.value).not.toBeNull()
    current = { ...plan(), id:'new-preview' }
    notifyRepositoryUpdate({ task_id:'task', id:current.id, version:2 }); await flushPromises()
    expect(shared.detail.value).toBeNull()
    expect(shared.fileLoading.value).toBe(true)
    finish({ data:detail() }); await flushPromises()
    expect(shared.detail.value?.path).toBe('shared.txt')
  })
  it('lets a read-only member inspect results without mutation controls', async () => {
    vi.mocked(api.get).mockImplementation(async url => ({ data:String(url).endsWith('/file') ? detail() : { can_update:false, repositories:[], plan:plan('READY') } }))
    const wrapper = mount(RepositoryUpdateChanges, { props:{ model:model() }, global })
    await flushPromises()
    expect(wrapper.text()).toContain('远端版本 · 最新基线')
    for (const action of ['应用到任务代码','确认此文件结果','让 Agent 重新适配','放弃本次预览']) {
      expect(wrapper.findAll('button').some(button => button.text() === action)).toBe(false)
    }
    expect(wrapper.getComponent(CodeComparison).props('editable')).toBe(false)
    wrapper.unmount()
  })
  it('renders each repository once with its version and mapping and preserves directory actions', async () => {
    const repositories = [{ id:'repo', name:'api', branch:'release/2.x', baseline:'newbaseline', creation_baseline:'creation' }]
    vi.mocked(api.get).mockResolvedValue({ data:{ repositories, plan:null, can_update:true } })
    const selectMapping = vi.fn()
    const controller = { available:true, participating:ref(false), preparationRequired:ref(false), busy:ref(false), loading:ref(false),
      state:ref({ repositories:[{ task_repository_id:'repo', repo_slug:'api', branch_name:'release/2.x', base_commit_sha:'oldbaseline' }] }),
      local:ref(null), mappings:ref({ repo:{ local_path:'G:/work/api' } }), mappingChecks:ref([{ task_repository_id:'repo', errors:[], changes:[], local_head:'newbaseline', local_branch:'release/2.x' }]),
      checkMappings:vi.fn(), selectMapping,
    } as unknown as LocalCollaboration
    const wrapper = mount(RepositoryUpdatePanel, { props:{ model:model(), controller }, global })
    await flushPromises()
    expect(wrapper.findAll('.repository-row')).toHaveLength(1)
    expect(wrapper.find('.repository-row').text()).toContain('newbasel')
    expect(wrapper.find('.path-text').text()).toBe('G:/work/api')
    expect(wrapper.find('.version-row').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('云端任务版本')
    await wrapper.get('button[aria-label="更换 api 本地仓库"]').trigger('click')
    expect(selectMapping).toHaveBeenCalledWith('repo')
    wrapper.unmount()
  })
})
