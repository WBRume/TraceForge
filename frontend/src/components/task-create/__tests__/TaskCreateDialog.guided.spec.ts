import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import TaskCreateDialog from '../TaskCreateDialog.vue'
import TaskCreateForm from '../TaskCreateForm.vue'
import { useProvisioningStore } from '@/stores/provisioning'
import * as runtime from '@/utils/runtime'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/utils/api', () => ({ default: api }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('element-plus', () => ({ ElMessage: { error: vi.fn(), warning: vi.fn(), success: vi.fn() } }))
const repos = [
  { repository_id: 'r1', repo_name: 'web', repo_url: 'https://example.com/web', branch_name: 'release/web' },
  { repository_id: 'r2', repo_name: 'api', repo_url: 'https://example.com/api', branch_name: 'release/api' },
]
const modelData = { backend: 'dsh', current_model: 'model/a', options: [{ value: 'model/a', label: 'Model A' }, { value: 'model/b', label: 'Model B' }] }
let wrapper: VueWrapper
beforeEach(() => {
  localStorage.clear()
  api.get.mockReset().mockImplementation(async (url: string) => ({ data:
    url.endsWith('/agent-models') ? modelData : url === '/skills' ? { items: [{ id: 's1', name: 'Review code', publish_state: 'PUBLISHED' }], total: 1 } : { repositories: repos, items: [], groups: [] },
  }))
  api.post.mockReset().mockResolvedValue({ data: { task_id: 'task-guided', job_id: 'job-guided' } })
})
afterEach(() => { wrapper?.unmount(); localStorage.clear(); vi.restoreAllMocks() })
async function open(props: Record<string, unknown> = {}) {
  wrapper = mount(TaskCreateDialog, { attachTo: document.body, props: { wsId: 'ws', ...props }, global: { plugins: [createPinia()], mocks: { $t: (key: string) => key } } })
  await flushPromises()
}
async function advance() { await wrapper.get('form').trigger('submit'); await flushPromises() }
async function fillContent() {
  await wrapper.get('.primary-input').setValue('Guided task')
  await wrapper.get('textarea').setValue('Keep the selected configuration')
}
function currentStep() { return wrapper.get('[aria-current="step"]').text() }

describe('guided task creation', () => {
  it('defaults to one step at a time, blocks missing content and only submits after review', async () => {
    await open()
    expect(currentStep()).toContain('steps.content.title')
    expect(wrapper.get('.agent-model-select').isVisible()).toBe(false)
    expect(wrapper.get('.skill-picker-entry-card').isVisible()).toBe(false)
    await advance()
    expect(wrapper.get('[role="alert"]').text()).toBe('task_create.name_required')
    expect(api.post).not.toHaveBeenCalled()
    await fillContent()
    await advance()
    expect(currentStep()).toContain('steps.environment.title')
    expect(wrapper.get('.primary-input').isVisible()).toBe(false)
    expect(wrapper.get('.agent-model-select').isVisible()).toBe(true)
    await advance()
    expect(currentStep()).toContain('steps.options.title')
    await advance()
    expect(wrapper.get('.create-review').text()).toContain('web · release/web')
    expect(wrapper.get('.create-review').text()).toContain('api · release/api')
    expect(wrapper.get('.create-review').text()).toContain('task_create.not_added')
    expect(api.post).not.toHaveBeenCalled()
    await advance()
    expect(api.post).toHaveBeenCalledTimes(1)
    expect(api.post).toHaveBeenCalledWith('/workspaces/ws/tasks', expect.objectContaining({ name: 'Guided task', task_type: 'DEVELOPMENT', agent_model: { backend: 'dsh', model: 'model/a' } }))
  })

  it('preserves files, models, repositories and skills across mode switches and review edits', async () => {
    await open()
    await wrapper.get('[data-mode="quick"]').trigger('click')
    await fillContent()
    const input = wrapper.get('input[type="file"]')
    const file = new File(['spec'], 'delivery.md')
    Object.defineProperty(input.element, 'files', { value: [file] })
    await input.trigger('change')
    await wrapper.get('.agent-model-select .select-trigger').trigger('click')
    await flushPromises()
    await wrapper.findAll('.agent-model-select .option-item')[1]!.trigger('click')
    await wrapper.get('.repo-entry-card').trigger('click')
    await flushPromises()
    await wrapper.get('.repo-batch-input').setValue('feature/wizard')
    await wrapper.get('.repo-batch-apply-btn').trigger('click')
    await wrapper.get('.skill-picker-entry-card').trigger('click')
    await wrapper.get('.skill-card-item').trigger('click')
    await wrapper.get('[data-mode="guided"]').trigger('click')
    expect(wrapper.find('.modal-skills-sidebar.open').exists()).toBe(false)
    await advance(); await advance(); await advance()
    const review = wrapper.get('.create-review').text()
    for (const value of ['delivery.md', 'Model B', 'feature/wizard', 'Review code']) expect(review).toContain(value)
    await wrapper.findAll('.review-edit')[0]!.trigger('click')
    await wrapper.get('.primary-input').setValue('Edited task')
    await advance(); await advance(); await advance(); await advance()
    expect(api.post).toHaveBeenCalledWith('/workspaces/ws/tasks', expect.objectContaining({ name: 'Edited task', skill_ids: ['s1'], agent_model: { backend: 'dsh', model: 'model/b' }, repository_branches: repos.map(repo => ({ repository_id: repo.repository_id, branch_name: 'feature/wizard' })) }))
    expect(useProvisioningStore().consumePendingTaskSpec('job-guided')?.file).toBe(file)
  })

  it('remembers the presentation preference without retaining a previous task draft', async () => {
    await open()
    await fillContent()
    await wrapper.get('[data-mode="quick"]').trigger('click')
    wrapper.unmount()
    await open()
    expect(wrapper.find('.create-progress').exists()).toBe(false)
    expect((wrapper.get('.primary-input').element as HTMLInputElement).value).toBe('')
    expect(wrapper.get('[data-mode="quick"]').attributes('aria-pressed')).toBe('true')
  })

  it('requires diagnosis symptoms and reviews diagnosis-only settings before creating', async () => {
    await open({ initialTaskType: 'DIAGNOSIS' })
    await wrapper.get('.primary-input').setValue('Diagnose timeout')
    await advance()
    expect(wrapper.get('[role="alert"]').text()).toBe('diagnosis.phenomenon_required')
    await wrapper.get('textarea').setValue('Checkout intermittently times out')
    await advance(); await advance()
    await wrapper.get('[aria-label="自动执行全流程"]').setValue(true)
    const input = wrapper.get('input[type="file"][multiple]')
    Object.defineProperty(input.element, 'files', { value: [new File(['trace'], 'error.log')] })
    await input.trigger('change')
    await advance()
    const review = wrapper.get('.create-review').text()
    expect(review).toContain('task_create.auto_run')
    expect(review).toContain('error.log')
    expect(review).not.toContain('dashboard.requirement_duration')
    await advance()
    const payload = api.post.mock.calls[0]![1]
    expect(payload).toMatchObject({ task_type: 'DIAGNOSIS', phenomenon: 'Checkout intermittently times out', sop_auto_run: true })
    expect(payload).not.toHaveProperty('requirement_id')
    expect(payload).not.toHaveProperty('description')
    expect(useProvisioningStore().consumePendingTaskDocs('job-guided')?.files[0]?.name).toBe('error.log')
  })

  it('blocks empty repository selection and closes the picker when continuing', async () => {
    await open(); await fillContent(); await advance()
    await wrapper.get('.repo-entry-card').trigger('click')
    await flushPromises()
    await wrapper.get('.repo-select-all-btn').trigger('click')
    await advance()
    expect(currentStep()).toContain('steps.environment.title')
    expect(wrapper.get('[role="alert"]').text()).toBe('dashboard.task_repo_required')
    expect(api.post).not.toHaveBeenCalled()
    await wrapper.get('.repo-entry-card').trigger('click')
    await wrapper.get('.repo-select-all-btn').trigger('click')
    await advance()
    expect(currentStep()).toContain('steps.options.title')
    expect(wrapper.find('.modal-skills-sidebar.open').exists()).toBe(false)
  })

  it('does not mistake failed repository loading for a workspace without repositories', async () => {
    api.get.mockImplementation(async (url: string) => {
      if (url === '/workspaces/ws') throw new Error('offline')
      return { data: url.endsWith('/agent-models') ? modelData : { items: [] } }
    })
    await open(); await fillContent(); await advance(); await advance()
    expect(currentStep()).toContain('steps.environment.title')
    expect(api.post).not.toHaveBeenCalled()
    api.get.mockResolvedValue({ data: { repositories: repos } })
    await wrapper.findAll('.guide-error button')[0]!.trigger('click')
    await flushPromises()
    await advance()
    expect(currentStep()).toContain('steps.options.title')
  })

  it('validates hidden required fields on review and returns to the affected step', async () => {
    await open(); await fillContent(); await advance(); await advance()
    await wrapper.get('input[type="number"]').setValue('')
    await advance()
    expect(currentStep()).toContain('steps.options.title')
    expect(wrapper.get('[role="alert"]').text()).toBe('task_create.duration_invalid')
    await wrapper.get('input[type="number"]').setValue('1.5')
    await advance()
    await wrapper.get('.primary-input').setValue('   ')
    await advance()
    expect(currentStep()).toContain('steps.content.title')
    expect(api.post).not.toHaveBeenCalled()
  })

  it('guards duplicate submits and retains the review after a failed create for retry', async () => {
    let reject!: (error: Error) => void
    api.post.mockImplementationOnce(() => new Promise((_, no) => { reject = no }))
    const log = vi.spyOn(console, 'error').mockImplementation(() => {})
    await open(); await fillContent(); await advance(); await advance(); await advance()
    await advance(); await advance()
    expect(api.post).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-mode="quick"]').attributes('disabled')).toBeDefined()
    reject(new Error('temporary failure'))
    await flushPromises()
    expect(wrapper.get('.create-review').text()).toContain('Guided task')
    await advance()
    expect(api.post).toHaveBeenCalledTimes(2)
    expect(wrapper.emitted('created')).toHaveLength(1)
    log.mockRestore()
  })

  it('waits for required requirement context before leaving the first step', async () => {
    wrapper = mount(TaskCreateForm, { props: { wsId: 'ws', taskType: 'DEVELOPMENT', mode: 'guided', creating: false, reposTotal: 0, selectedRepoCount: 0, selectedSkillCount: 0, activeSidebar: 'none', requirementRequired: true, requirementLoading: true }, global: { mocks: { $t: (key: string) => key } } })
    await flushPromises(); await fillContent(); await advance()
    expect(wrapper.get('[role="alert"]').text()).toBe('task_rail.loading_context')
    await wrapper.setProps({ requirementLoading: false })
    await advance()
    expect(wrapper.get('[role="alert"]').text()).toBe('task_rail.select_requirement')
    expect(wrapper.emitted('submit')).toBeUndefined()
  })

  it('keeps a local execution resource mounted across steps and mode switches', async () => {
    vi.spyOn(runtime, 'isDesktop').mockReturnValue(true)
    api.get.mockImplementation(async (url: string) => ({ data:
      url.endsWith('/local-resources') ? { enabled: true, items: [{ id: 'local-1', name: 'My workstation', backend: 'dsh', profile_revision: 3 }] }
        : url.endsWith('/agent-backends') ? { effective_agent_backend: 'dsh' }
          : url.endsWith('/agent-models') ? modelData : { repositories: repos, items: [] },
    }))
    await open(); await fillContent(); await advance()
    await wrapper.get('.exec-seg-local').trigger('click')
    await flushPromises()
    await advance()
    await wrapper.get('[data-mode="quick"]').trigger('click')
    await wrapper.get('[data-mode="guided"]').trigger('click')
    await advance(); await advance(); await advance()
    expect(wrapper.get('.create-review').text()).toContain('My workstation')
    expect(wrapper.get('.create-review').text()).not.toContain('collaboration.createIntent')
    await advance()
    expect(api.post).toHaveBeenCalledWith('/workspaces/ws/tasks', expect.objectContaining({ execution: { location: 'LOCAL', resource_id: 'local-1', profile_revision: 3 } }))
  })

  it('carries inherited requirement content and staged specification through the guided flow', async () => {
    const requirement = { id: 'req', title: 'Inherited task', body: 'Specification', task_prompt: 'Implement this requirement', acceptance_criteria: ['Check behavior'], can_link_task: true, child_count: 0, status: 'READY' }
    api.get.mockImplementation(async (url: string) => ({ data: url.endsWith('/requirements/req') ? { requirement } : url.endsWith('/agent-models') ? modelData : { repositories: repos, items: [] } }))
    await open({ initialRequirement: requirement })
    await advance(); await advance(); await advance()
    const review = wrapper.get('.create-review').text()
    expect(review).toContain('Inherited task.md')
    expect(review).toContain('Implement this requirement')
    await advance()
    expect(api.post).toHaveBeenCalledWith('/workspaces/ws/tasks', expect.objectContaining({ requirement_id: 'req', name: 'Inherited task', description: 'Implement this requirement' }))
    expect(useProvisioningStore().consumePendingTaskSpec('job-guided')?.file.name).toBe('Inherited task.md')
  })
})
