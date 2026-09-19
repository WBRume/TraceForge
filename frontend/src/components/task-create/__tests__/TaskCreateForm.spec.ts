import { describe, expect, it, vi } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'

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
