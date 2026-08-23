import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import TaskProvisionProgressModal from '@/components/TaskProvisionProgressModal.vue'
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

let pinia: ReturnType<typeof createPinia>

const mountModal = () =>
  mount(TaskProvisionProgressModal, {
    props: { show: true, jobId: 'job-1', taskId: 'task-1', workspaceId: 'ws-1' },
    global: {
      plugins: [pinia],
      stubs: { 'el-progress': true },
    },
  })

describe('TaskProvisionProgressModal', () => {
  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    apiMock.get.mockReset()
    apiMock.post.mockReset()
  })

  it('shows provisioning progress and opens session after success', async () => {
    vi.useFakeTimers()
    try {
      apiMock.get
        .mockResolvedValueOnce({
          data: { job_id: 'job-1', job_type: 'CREATE_TASK', status: 'RUNNING', progress: 40, stage: 'PREPARING_WORKTREE', message: 'Preparing worktree' },
        })
        .mockResolvedValueOnce({
          data: { job_id: 'job-1', job_type: 'CREATE_TASK', status: 'SUCCESS', progress: 100, stage: 'COMPLETED', message: 'Task is ready' },
        })
        .mockResolvedValueOnce({
          data: { id: 'task-1', status: 'PENDING' },
        })

      const wrapper = mountModal()
      await flushPromises()

      // 首轮：进度展示
      expect(apiMock.get).toHaveBeenCalledWith('/provision-jobs/job-1')
      expect(wrapper.text()).toContain('provisioning.stage_preparing_worktree')
      expect(wrapper.text()).toContain('40%')

      // 推进轮询定时器 → 成功 → 出现「进入会话」按钮
      await vi.advanceTimersByTimeAsync(1300)
      await flushPromises()

      const enterButton = wrapper.findAll('button').find((btn) => btn.text().includes('provisioning.task_provision_enter_session'))
      expect(enterButton).toBeTruthy()
      await enterButton!.trigger('click')
      expect(wrapper.emitted('openSession')).toHaveLength(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it('uploads pending spec and diagnosis docs after success', async () => {
    const provisioningStore = useProvisioningStore()
    provisioningStore.setPendingTaskSpec('job-1', {
      workspaceId: 'ws-1',
      taskId: 'task-1',
      file: new File(['spec'], 'req.md', { type: 'text/markdown' }),
    })
    provisioningStore.setPendingTaskDocs('job-1', {
      workspaceId: 'ws-1',
      taskId: 'task-1',
      files: [new File(['log'], 'issue.log', { type: 'text/plain' })],
    })

    apiMock.get
      .mockResolvedValueOnce({
        data: { job_id: 'job-1', job_type: 'CREATE_TASK', status: 'SUCCESS', progress: 100, stage: 'COMPLETED' },
      })
      .mockResolvedValue({
        data: { id: 'task-1', status: 'PENDING' },
      })
    apiMock.post.mockResolvedValue({ data: { status: 'success' } })

    const wrapper = mountModal()
    await flushPromises()
    await flushPromises()

    expect(apiMock.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/tasks/task-1/upload-spec',
      expect.any(FormData),
      expect.anything(),
    )
    expect(apiMock.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/tasks/task-1/upload-diagnosis-doc',
      expect.any(FormData),
      expect.anything(),
    )
    expect(wrapper.text()).toContain('provisioning.task_provision_enter_session')

    const enterButton = wrapper.findAll('button').find((btn) => btn.text().includes('provisioning.task_provision_enter_session'))
    await enterButton!.trigger('click')
    expect(wrapper.emitted('openSession')).toHaveLength(1)
  })

  it('shows the failure state with the error message', async () => {
    apiMock.get.mockResolvedValue({
      data: { job_id: 'job-1', job_type: 'CREATE_TASK', status: 'FAILED', progress: 60, stage: 'FAILED', error_message: 'repo busy' },
    })

    const wrapper = mountModal()
    await flushPromises()

    expect(wrapper.find('.provision-error-box').text()).toContain('repo busy')
    expect(wrapper.text()).not.toContain('provisioning.task_provision_enter_session')
  })

  it('emits close when the cancel button is clicked', async () => {
    apiMock.get.mockResolvedValue({
      data: { job_id: 'job-1', job_type: 'CREATE_TASK', status: 'RUNNING', progress: 10, stage: 'PREPARING_TASK' },
    })

    const wrapper = mountModal()
    await flushPromises()

    const cancelButton = wrapper.findAll('button').find((btn) => btn.text().includes('common.cancel'))
    await cancelButton!.trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})
