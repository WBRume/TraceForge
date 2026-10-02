import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'

const api = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/utils/api', () => ({ default: api }))
beforeEach(() => api.get.mockResolvedValue({ data: {
  backend: 'dsh', current_model: 'private/a', items: [], options: [
    { value: 'private/a', label: 'Model A' }, { value: 'private/b', label: 'Model B' },
  ],
} }))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

import TaskCreateForm from '@/components/task-create/TaskCreateForm.vue'
import type { RequirementSummary } from '@/types/workspaceAssets'

const baseProps = {
  wsId: 'ws-1',
  taskType: 'DEVELOPMENT' as const,
  creating: false,
  reposTotal: 0,
  selectedRepoCount: 0,
  selectedSkillCount: 0,
  activeSidebar: 'none' as const,
}

const findSpecInput = (wrapper: VueWrapper) => wrapper.find('#spec-upload-ws-1')

const selectSpecFile = async (wrapper: VueWrapper, file: File) => {
  const input = findSpecInput(wrapper).element as HTMLInputElement
  Object.defineProperty(input, 'files', { value: [file], configurable: true })
  await findSpecInput(wrapper).trigger('change')
}

const mountForm = () =>
  mount(TaskCreateForm, {
    props: baseProps,
    global: { mocks: { $t: (key: string) => key } },
  })

describe('TaskCreateForm spec upload', () => {
  it('opens the requirements sidebar and submits the selected association or an independent task', async () => {
    const wrapper = mountForm()
      await wrapper.find('.requirement-entry-card').trigger('click')
      expect(wrapper.emitted('toggle-sidebar')?.[0]).toEqual(['requirements'])
      expect(wrapper.findComponent({ name:'RequirementSelect' }).exists()).toBe(false)
      await wrapper.setProps({ selectedRequirement:{ id:'req-search', title:'Payment rules', status:'READY' } })
      await wrapper.find('form').trigger('submit')
      expect(wrapper.emitted('submit')?.[0]?.[0]).toMatchObject({ requirementId:'req-search' })
      await wrapper.setProps({ selectedRequirement:null })
      await wrapper.find('form').trigger('submit')
      expect(wrapper.emitted('submit')?.[1]?.[0]).toMatchObject({ requirementId:undefined })
      wrapper.unmount()
  })
  it('inherits and locks the current requirement, and includes it in the submitted draft', async () => {
    const wrapper = mount(TaskCreateForm, {
      props:{ ...baseProps, selectedRequirement:{ id:'req-101', title:'Payments', status:'READY', source_ref:'REQ-101' }, requirementLocked:true },
      global:{ mocks:{ $t:(key:string) => key } },
    })
    expect(wrapper.find('.requirement-entry-card').text()).toContain('Payments')
    expect(wrapper.find('.requirement-context-hint').text()).toBe('task_rail.inherited')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')?.[0]?.[0]).toMatchObject({ requirementId:'req-101' })
    wrapper.unmount()
  })
  it('fills the saved prompt and document and preserves manual edits when association changes', async () => {
    const context: RequirementSummary = { id:'req-a', workspace_id:'ws-1', title:'Payments', body:'# Specification\nValidate payments.', status:'READY', child_count:0, can_link_task:true,
      change_history_count:0, related_task_count:0, coverage_summary:{ coverage_status:'waiting_evidence', coverage_reason:'', related_task_count:0, evidence_count:0, human_review_count:0, human_delta_count:0 },
      acceptance_criteria:['Reject invalid payments'], source_metadata:{ task_prompt:'Implement payment validation' } }
    const wrapper = mountForm()
    await wrapper.setProps({ selectedRequirement:context, requirementContext:context })
    await wrapper.find('form').trigger('submit')
    const draft = wrapper.emitted('submit')?.[0]?.[0] as { name:string; description:string; specFile:File }
    expect(draft.name).toBe('Payments')
    expect(draft.description).toBe('Implement payment validation')
    expect(draft.specFile.name).toBe('Payments.md')
    const document = await new Promise<string>((resolve) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.readAsText(draft.specFile) })
    expect(document).toContain('Validate payments.')
    expect(document).toContain('Reject invalid payments')
    await wrapper.find('.primary-input').setValue('Custom delivery name')
    await wrapper.find('textarea').setValue('My edited prompt')
    await selectSpecFile(wrapper, new File(['my spec'], 'custom.md'))
    const other = { ...context, id:'req-b', title:'Delivery', source_metadata:{ task_prompt:'Implement delivery' } }
    await wrapper.setProps({ selectedRequirement:other, requirementContext:other })
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')?.[1]?.[0]).toMatchObject({ requirementId:'req-b', name:'Custom delivery name', description:'My edited prompt', specFile:{ name:'custom.md' } })
    wrapper.unmount()
  })
  it('refreshes the catalogue on opening without replacing the selected draft', async () => {
    const wrapper = mountForm()
    await flushPromises()
    await wrapper.find('.agent-model-select .select-trigger').trigger('click')
    await wrapper.findAll('.agent-model-select .option-item')[1]!.trigger('click')
    await flushPromises()
    api.get.mockResolvedValue({ data: {
      backend: 'dsh', current_model: 'private/a', options: [
        { value: 'private/a', label: 'Model A' }, { value: 'private/b', label: 'Model B' },
        { value: 'private/c', label: 'New Model C' },
      ],
    } })
    await wrapper.find('.agent-model-select .select-trigger').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.agent-model-select .option-item')).toHaveLength(3)
    expect(wrapper.find('.agent-model-select .selected-text').text()).toBe('Model B')
    wrapper.unmount()
  })
  it('includes the selected engine model in the task draft', async () => {
    const wrapper = mountForm()
    await flushPromises()
    expect(wrapper.find('.agent-model-select').text()).toContain('Model A')
    await wrapper.find('.agent-model-select .select-trigger').trigger('click')
    await wrapper.findAll('.agent-model-select .option-item')[1]!.trigger('click')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')?.[0]?.[0]).toMatchObject({ agentModel: { backend: 'dsh', model: 'private/b' } })
    wrapper.unmount()
  })
  it('accept 不再包含 .doc', () => {
    const wrapper = mountForm()
    expect(findSpecInput(wrapper).attributes('accept')).toBe('.pdf,.docx,.md,.txt')
  })

  it('选择 PDF 时显示 agent 能力提示', async () => {
    const wrapper = mountForm()
    expect(wrapper.find('.pdf-agent-hint').exists()).toBe(false)
    await selectSpecFile(wrapper, new File(['x'], 'req.pdf', { type: 'application/pdf' }))
    expect(wrapper.find('.pdf-agent-hint').exists()).toBe(true)
    expect(wrapper.find('.pdf-agent-hint').text()).toBe('dashboard.spec_pdf_agent_hint')
  })

  it('选择 docx 时不显示提示', async () => {
    const wrapper = mountForm()
    await selectSpecFile(
      wrapper,
      new File(['x'], 'req.docx', {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      }),
    )
    expect(wrapper.find('.pdf-agent-hint').exists()).toBe(false)
  })
})
