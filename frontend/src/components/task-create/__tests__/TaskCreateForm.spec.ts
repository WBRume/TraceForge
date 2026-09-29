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
