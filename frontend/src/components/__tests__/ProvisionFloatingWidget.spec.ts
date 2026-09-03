import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ProvisionFloatingWidget from '@/components/ProvisionFloatingWidget.vue'
import { useProvisioningStore } from '@/stores/provisioning'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string, params?: Record<string, unknown>) => (params ? `${key}:${JSON.stringify(params)}` : key) }),
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

vi.mock('vue-router', () => ({
  useRouter: () => routerMock,
}))

vi.mock('@/utils/api', () => ({
  default: apiMock,
}))

let pinia: ReturnType<typeof createPinia>

const mountWidget = () =>
  mount(ProvisionFloatingWidget, {
    global: {
      plugins: [pinia],
      stubs: { 'el-progress': true, teleport: true },
    },
  })

describe('ProvisionFloatingWidget', () => {
  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    localStorage.clear()
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    routerMock.push.mockReset()
    apiMock.post.mockResolvedValue({ data: {} })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('tracks a newly created task and shows progress', async () => {
    apiMock.get.mockResolvedValue({
      data: { job_id: 'job-1', job_type: 'CREATE_TASK', status: 'RUNNING', progress: 40, stage: 'PREPARING_WORKTREE', message: 'Preparing worktree' },
    })

    const store = useProvisioningStore()
    store.startWatching({ jobId: 'job-1', taskId: 'task-1', workspaceId: 'ws-1', taskName: 'test-task' })
    await flushPromises()

    expect(apiMock.get).toHaveBeenCalledWith('/provision-jobs/job-1')
    const wrapper = mountWidget()
    expect(store.expanded).toBe(true)
    expect(wrapper.text()).toContain('test-task')
    expect(wrapper.text()).toContain('provisioning.stage_preparing_worktree')
    expect(wrapper.text()).toContain('40%')

    store.dismiss('job-1')
    wrapper.unmount()
  })

  it('uploads pending files and becomes ready after success', async () => {
    vi.useFakeTimers()
    apiMock.get
      .mockResolvedValueOnce({
        data: { job_id: 'job-1', job_type: 'CREATE_TASK', status: 'RUNNING', progress: 90, stage: 'PREPARING_WORKTREE' },
      })
      .mockResolvedValueOnce({
        data: { job_id: 'job-1', job_type: 'CREATE_TASK', status: 'SUCCESS', progress: 100, stage: 'COMPLETED' },
      })
      .mockResolvedValue({ data: { id: 'task-1', status: 'PENDING' } })

    const store = useProvisioningStore()
    store.setPendingTaskSpec('job-1', { workspaceId: 'ws-1', taskId: 'task-1', file: new File(['spec'], 'req.md') })
    store.startWatching({ jobId: 'job-1', taskId: 'task-1', workspaceId: 'ws-1', taskName: 'test-task' })
    // 首轮拉取（RUNNING）
    await vi.advanceTimersByTimeAsync(0)
    // 推进轮询 → SUCCESS → 上传暂存文件 → 确认任务 PENDING
    await vi.advanceTimersByTimeAsync(1300)

    const job = store.jobs['job-1']
    expect(job.terminal).toBe(true)
    expect(job.ready).toBe(true)
    expect(apiMock.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/tasks/task-1/upload-spec',
      expect.any(FormData),
      expect.anything(),
    )
    expect(store.taskListRefreshToken).toBeGreaterThan(0)

    vi.useRealTimers()
    // 最小化 pill：全部结束后进度显示 100%（成功图标），而非 0%
    store.minimize()
    const pillWrapper = mountWidget()
    expect(pillWrapper.text()).toContain('100%')
    expect(pillWrapper.find('.widget-ok').exists()).toBe(true)
    pillWrapper.unmount()

    store.expand()
    const wrapper = mountWidget()
    const enterButton = wrapper.findAll('button').find((btn) => btn.text().includes('provisioning.task_provision_enter_session'))
    expect(enterButton).toBeTruthy()
    await enterButton!.trigger('click')
    await flushPromises()
    expect(routerMock.push).toHaveBeenCalledWith('/ws/ws-1/chat/task-1')
    expect(store.jobs['job-1']).toBeUndefined()
    wrapper.unmount()
  })

  it('cancel asks for confirmation then calls the backend API', async () => {
    apiMock.get
      .mockResolvedValueOnce({
        data: { job_id: 'job-1', job_type: 'CREATE_TASK', status: 'RUNNING', progress: 20, stage: 'PREPARING_TASK' },
      })
      .mockResolvedValue({
        data: { job_id: 'job-1', job_type: 'CREATE_TASK', status: 'RUNNING', progress: 20, stage: 'CANCELLING', cancel_requested: true },
      })

    const store = useProvisioningStore()
    store.startWatching({ jobId: 'job-1', taskId: 'task-1', workspaceId: 'ws-1', taskName: 'test-task' })
    await flushPromises()

    const wrapper = mountWidget()
    const cancelButton = wrapper.findAll('button').find((btn) => btn.text().includes('common.cancel'))
    expect(cancelButton).toBeTruthy()
    await cancelButton!.trigger('click')
    await flushPromises()

    // 点击后先弹出确认弹窗，尚未调用后端
    expect(apiMock.post).not.toHaveBeenCalled()

    const modalActions = wrapper.find('.modal-actions')
    expect(modalActions.exists()).toBe(true)
    const confirmButton = modalActions.findAll('button').find((btn) => btn.text().includes('common.confirm'))
    expect(confirmButton).toBeTruthy()
    await confirmButton!.trigger('click')
    await flushPromises()

    expect(apiMock.post).toHaveBeenCalledWith('/provision-jobs/job-1/cancel')
    expect(store.jobs['job-1'].cancelRequested).toBe(true)

    store.dismiss('job-1')
    wrapper.unmount()
  })

  it('shows the failure state and dismiss removes the card', async () => {
    apiMock.get.mockResolvedValue({
      data: { job_id: 'job-1', job_type: 'CREATE_TASK', status: 'FAILED', progress: 60, stage: 'FAILED', error_message: 'Authentication failed' },
    })

    const store = useProvisioningStore()
    store.startWatching({ jobId: 'job-1', taskId: 'task-1', workspaceId: 'ws-1', taskName: 'test-task' })
    await flushPromises()

    expect(store.jobs['job-1'].terminal).toBe(true)

    const wrapper = mountWidget()
    expect(wrapper.text()).toContain('Authentication failed')
    expect(wrapper.text()).not.toContain('provisioning.task_provision_enter_session')

    const closeButton = wrapper.find('.widget-job-actions .widget-icon-btn')
    await closeButton.trigger('click')
    expect(store.jobs['job-1']).toBeUndefined()
    wrapper.unmount()
  })

  it('restores active jobs from the server on app start', async () => {
    apiMock.get.mockResolvedValue({
      data: [
        { job_id: 'job-2', job_type: 'CREATE_TASK', status: 'RUNNING', progress: 10, stage: 'WAITING_REPO_LOCK', task_id: 'task-2', workspace_id: 'ws-2', task_name: 'restored-task' },
      ],
    })

    const store = useProvisioningStore()
    await store.restoreFromServer()
    await flushPromises()

    expect(apiMock.get).toHaveBeenCalledWith('/provision-jobs/active')
    expect(store.jobs['job-2']).toBeTruthy()
    expect(store.jobs['job-2'].taskName).toBe('restored-task')
    // 恢复时默认最小化，不展开面板
    expect(store.expanded).toBe(false)

    store.dismiss('job-2')
  })
})
