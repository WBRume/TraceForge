import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import NewTaskModal from '@/components/NewTaskModal.vue'
import { useProvisioningStore } from '@/stores/provisioning'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

vi.mock('@/utils/api', () => ({
  default: apiMock,
}))

const mountModal = async () => {
  const wrapper = mount(NewTaskModal, {
    props: { show: true, wsId: 'ws-1' },
    global: {
      plugins: [createPinia()],
      mocks: { $t: (key: string) => key },
    },
  })
  await flushPromises()
  return wrapper
}

const diagnosisTypeCard = (wrapper: ReturnType<typeof mount>) =>
  wrapper.findAll('.task-type-card').find((card) => card.text().includes('task_types.diagnosis'))!

const setInputFiles = async (input: any, files: File[]) => {
  Object.defineProperty(input.element, 'files', { value: files, configurable: true })
  await input.trigger('change')
}

describe('NewTaskModal diagnosis mode', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    apiMock.get.mockImplementation(async () => ({ data: { items: [], repositories: [] } }))
    apiMock.post.mockResolvedValue({
      data: { job_id: 'job-1', task_id: 'task-9' },
    })
  })

  it('hides the generic description field for diagnosis tasks', async () => {
    const wrapper = await mountModal()

    // 研发态默认显示描述
    expect(wrapper.findAll('textarea')).toHaveLength(1)

    await diagnosisTypeCard(wrapper).trigger('click')
    await flushPromises()

    // 诊断态：描述隐藏，现象显示；研发态专属内容隐藏
    const textareas = wrapper.findAll('textarea')
    expect(textareas).toHaveLength(1)
    expect(textareas[0].attributes('placeholder')).toContain('diagnosis.phenomenon_placeholder')
    expect(textareas[0].attributes('required')).toBeDefined()
    expect(wrapper.find('textarea[placeholder="dashboard.desc_placeholder"]').exists()).toBe(false)
  })

  it('shows multi-file upload for diagnosis docs', async () => {
    const wrapper = await mountModal()
    await diagnosisTypeCard(wrapper).trigger('click')
    await flushPromises()

    const fileInput = wrapper.find('input[type="file"][multiple]')
    expect(fileInput.exists()).toBe(true)
    expect(wrapper.text()).toContain('diagnosis.docs_upload_label')

    // 选择两个文件后列表出现
    const files = [new File(['a'], 'req.md', { type: 'text/markdown' }), new File(['b'], 'issue.log', { type: 'text/plain' })]
    await setInputFiles(fileInput, files)
    await flushPromises()
    expect(wrapper.findAll('.diagnosis-file-row')).toHaveLength(2)
    expect(wrapper.text()).toContain('req.md')
    expect(wrapper.text()).toContain('issue.log')
  })

  it('creates diagnosis task without description and stages pending docs', async () => {
    const wrapper = await mountModal()
    await diagnosisTypeCard(wrapper).trigger('click')
    await flushPromises()

    await wrapper.find('input[placeholder="dashboard.task_name_placeholder"]').setValue('定位超时问题')
    const phenomenon = wrapper.find('textarea[placeholder="diagnosis.phenomenon_placeholder"]')
    await phenomenon.setValue('接口偶发超时')

    const fileInput = wrapper.find('input[type="file"][multiple]')
    const files = [new File(['log'], 'issue.log', { type: 'text/plain' })]
    await setInputFiles(fileInput, files)
    await flushPromises()

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(apiMock.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/tasks',
      expect.objectContaining({
        name: '定位超时问题',
        task_type: 'DIAGNOSIS',
        phenomenon: '接口偶发超时',
        priority: 'P2',
      }),
    )
    const callArgs = apiMock.post.mock.calls[0][1] as Record<string, unknown>
    expect(callArgs.description).toBeUndefined()

    const provisioningStore = useProvisioningStore()
    const pending = provisioningStore.consumePendingTaskDocs('job-1')
    expect(pending).not.toBeNull()
    expect(pending!.files).toHaveLength(1)
    expect(pending!.files[0].name).toBe('issue.log')

    const createdEvent = wrapper.emitted('created')
    expect(createdEvent).toHaveLength(1)
    expect((createdEvent![0][0] as Record<string, unknown>).expectDiagnosisDocs).toBe(true)
  })

  it('does not create diagnosis task without phenomenon', async () => {
    const wrapper = await mountModal()
    await diagnosisTypeCard(wrapper).trigger('click')
    await flushPromises()

    await wrapper.find('input[placeholder="dashboard.task_name_placeholder"]').setValue('定位超时问题')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(apiMock.post).not.toHaveBeenCalled()
  })
})
