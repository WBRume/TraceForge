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

const ElMessageMock = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string, params?: Record<string, unknown>) => (params ? `${key}:${JSON.stringify(params)}` : key) }),
}))

vi.mock('element-plus', () => ({
  ElMessage: ElMessageMock,
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
    expect(routerMock.push).toHaveBeenCalledWith('/workspaces/ws-1/chat/task-1')
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

  it('tracks a requirement split preview job and shows progress only after minimize', async () => {
    apiMock.get.mockResolvedValue({
      data: {
        job_id: 'pjob-1',
        workspace_id: 'ws-1',
        status: 'RUNNING',
        progress: 42,
        message: 'Running Claude Code CLI split preview',
        job_kind: 'REQUIREMENT_SPLIT_PREVIEW',
        requirement_id: 'req-1',
        requirement_title: 'Big requirement',
      },
    })

    const store = useProvisioningStore()
    store.trackRequirementPreviewJob({
      jobId: 'pjob-1',
      workspaceId: 'ws-1',
      kind: 'requirement_split_preview',
      requirementId: 'req-1',
      requirementTitle: 'Big requirement',
    })
    await flushPromises()

    expect(apiMock.get).toHaveBeenCalledWith(
      '/workspaces/ws-1/workspace-assets/requirements/preview-jobs/pjob-1',
    )
    expect(store.jobs['pjob-1'].kind).toBe('requirement_split_preview')
    expect(store.jobs['pjob-1'].terminal).toBe(false)

    // 弹窗还在展示进度：浮窗不出现卡片
    const before = mountWidget()
    expect(before.text()).not.toContain('Big requirement')
    before.unmount()

    // 点「缩小」后才出现在右下角（展开面板承接）
    store.minimizePreviewJob('pjob-1')
    expect(store.expanded).toBe(true)
    const wrapper = mountWidget()
    expect(wrapper.text()).toContain('Big requirement')
    expect(wrapper.text()).toContain('42%')
    expect(wrapper.text()).toContain('provisioning.preview_stage_running')
    // 预览作业不提供取消按钮
    const cancelButton = wrapper.findAll('button').find((btn) => btn.text().includes('common.cancel'))
    expect(cancelButton).toBeUndefined()
    wrapper.unmount()
    store.dismiss('pjob-1')
  })

  it('shows the open-preview action on success without the error style, and hides the card once viewed', async () => {
    apiMock.get.mockResolvedValue({
      data: {
        job_id: 'pjob-2',
        workspace_id: 'ws-1',
        status: 'SUCCESS',
        progress: 100,
        message: 'Requirement split preview created',
        job_kind: 'REQUIREMENT_SPLIT_PREVIEW',
        requirement_id: 'req-2',
        requirement_title: 'Split me',
        batch: { id: 'batch-1', workspace_id: 'ws-1', status: 'PREVIEW', item_count: 2, confirmed_count: 0, items: [] },
      },
    })

    const store = useProvisioningStore()
    store.trackRequirementPreviewJob({
      jobId: 'pjob-2',
      workspaceId: 'ws-1',
      kind: 'requirement_split_preview',
      requirementId: 'req-2',
      requirementTitle: 'Split me',
    })
    store.minimizePreviewJob('pjob-2')
    await flushPromises()

    expect(store.jobs['pjob-2'].terminal).toBe(true)
    expect(store.jobs['pjob-2'].batch?.id).toBe('batch-1')

    const wrapper = mountWidget()
    expect(wrapper.text()).toContain('provisioning.preview_success_hint')
    // 成功卡片不得套用红色错误背景
    const card = wrapper.find('.widget-job')
    expect(card.classes()).not.toContain('widget-job-error')
    const openButton = wrapper.findAll('button').find((btn) => btn.text().includes('provisioning.preview_open_action'))
    expect(openButton).toBeTruthy()
    await openButton!.trigger('click')
    await flushPromises()
    expect(routerMock.push).toHaveBeenCalledWith({
      path: '/workspaces/ws-1/assets/requirements/req-2',
      query: { previewJob: 'pjob-2' },
    })
    // 跳转不丢数据：store 保留作业供弹窗绑定，标记 viewed 后浮窗隐藏卡片
    expect(store.jobs['pjob-2']).toBeTruthy()
    expect(store.jobs['pjob-2'].viewed).toBe(false)

    store.markPreviewJobViewed('pjob-2')
    const hidden = mountWidget()
    expect(hidden.text()).not.toContain('Split me')
    hidden.unmount()
    wrapper.unmount()
    store.dismiss('pjob-2')
  })

  it('restores active requirement preview jobs from the global endpoint', async () => {
    apiMock.get.mockImplementation((url: string) => {
      if (url === '/provision-jobs/active') return Promise.resolve({ data: [] })
      if (url === '/requirement-preview-jobs/active') {
        return Promise.resolve({
          data: [
            {
              job_id: 'pjob-9',
              workspace_id: 'ws-1',
              status: 'RUNNING',
              progress: 8,
              job_kind: 'REQUIREMENT_SPLIT_PREVIEW',
              requirement_id: 'req-9',
              requirement_title: 'R9',
            },
          ],
        })
      }
      return Promise.resolve({ data: {} })
    })

    const store = useProvisioningStore()
    await store.restoreFromServer()
    await flushPromises()

    expect(apiMock.get).toHaveBeenCalledWith('/requirement-preview-jobs/active')
    expect(store.jobs['pjob-9']).toBeTruthy()
    expect(store.jobs['pjob-9'].kind).toBe('requirement_split_preview')
    expect(store.jobs['pjob-9'].requirementTitle).toBe('R9')
    // 刷新恢复的作业没有弹窗承接：直接出现在浮窗
    expect(store.jobs['pjob-9'].handedOver).toBe(true)
    const wrapper = mountWidget()
    expect(wrapper.text()).toContain('R9')
    wrapper.unmount()

    store.dismiss('pjob-9')
  })

  it('closing a running preview card cancels the CLI job and cleans up after convergence', async () => {
    vi.useFakeTimers()
    apiMock.get
      .mockResolvedValueOnce({
        data: {
          job_id: 'pjob-3',
          workspace_id: 'ws-1',
          status: 'RUNNING',
          progress: 20,
          message: 'Running Claude Code CLI split preview',
          job_kind: 'REQUIREMENT_SPLIT_PREVIEW',
          requirement_id: 'req-3',
          requirement_title: 'Cancel me',
        },
      })
      .mockResolvedValue({
        data: {
          job_id: 'pjob-3',
          workspace_id: 'ws-1',
          status: 'CANCELLED',
          progress: 100,
          job_kind: 'REQUIREMENT_SPLIT_PREVIEW',
          requirement_id: 'req-3',
          requirement_title: 'Cancel me',
        },
      })
    apiMock.post.mockResolvedValue({ data: {} })

    const store = useProvisioningStore()
    store.trackRequirementPreviewJob({
      jobId: 'pjob-3',
      workspaceId: 'ws-1',
      kind: 'requirement_split_preview',
      requirementId: 'req-3',
      requirementTitle: 'Cancel me',
    })
    store.minimizePreviewJob('pjob-3')
    await vi.advanceTimersByTimeAsync(0)

    const wrapper = mountWidget()
    const closeButton = wrapper.find('.widget-job-actions .widget-icon-btn')
    expect(closeButton.exists()).toBe(true)
    await closeButton.trigger('click')
    await flushPromises()

    // 复用任务会话的 ai-jobs cancel 通道：终止 CLI 进程（各 backend 统一收敛）
    expect(apiMock.post).toHaveBeenCalledWith('/workspaces/ws-1/ai-jobs/pjob-3/cancel')
    // 取消受理后作业先保留（cancelRequested 标记），避免重开弹窗时误判为无作业
    expect(store.jobs['pjob-3']).toBeTruthy()
    expect(store.jobs['pjob-3'].cancelRequested).toBe(true)

    // 后端收敛 CANCELLED 后自动清理卡片
    await vi.advanceTimersByTimeAsync(1300)
    expect(store.jobs['pjob-3']).toBeUndefined()
    wrapper.unmount()
  })

  it('shows the cancelling preview card even before handover so close-cancel is visible', async () => {
    apiMock.get.mockResolvedValue({
      data: {
        job_id: 'pjob-5',
        workspace_id: 'ws-1',
        status: 'RUNNING',
        progress: 35,
        job_kind: 'REQUIREMENT_SPLIT_PREVIEW',
        requirement_id: 'req-5',
        requirement_title: 'Dialog closed',
      },
    })
    apiMock.post.mockResolvedValue({ data: {} })

    const store = useProvisioningStore()
    store.trackRequirementPreviewJob({
      jobId: 'pjob-5',
      workspaceId: 'ws-1',
      kind: 'requirement_split_preview',
      requirementId: 'req-5',
      requirementTitle: 'Dialog closed',
    })
    await flushPromises()

    // 未缩小：取消前不出现在浮窗
    const before = mountWidget()
    expect(before.text()).not.toContain('Dialog closed')
    before.unmount()

    // 弹窗关闭发起取消：受理后即使未缩小，浮窗也要显示「正在取消」卡片
    await store.cancelPreviewJob('pjob-5')
    expect(store.jobs['pjob-5'].cancelRequested).toBe(true)
    store.expand()
    const wrapper = mountWidget()
    expect(wrapper.text()).toContain('Dialog closed')
    expect(wrapper.text()).toContain('provisioning.preview_stage_cancelling')
    wrapper.unmount()
    store.dismiss('pjob-5')
  })

  it('keeps the preview card when the cancel request fails', async () => {
    apiMock.get.mockResolvedValue({
      data: {
        job_id: 'pjob-4',
        workspace_id: 'ws-1',
        status: 'RUNNING',
        progress: 30,
        job_kind: 'REQUIREMENT_SPLIT_PREVIEW',
        requirement_id: 'req-4',
        requirement_title: 'Sticky',
      },
    })
    apiMock.post.mockRejectedValue({ response: { status: 403 } })

    const store = useProvisioningStore()
    store.trackRequirementPreviewJob({
      jobId: 'pjob-4',
      workspaceId: 'ws-1',
      kind: 'requirement_split_preview',
      requirementId: 'req-4',
      requirementTitle: 'Sticky',
    })
    store.minimizePreviewJob('pjob-4')
    await flushPromises()

    const wrapper = mountWidget()
    const closeButton = wrapper.find('.widget-job-actions .widget-icon-btn')
    await closeButton.trigger('click')
    await flushPromises()

    // 取消失败：卡片保留（进程仍在跑），提示用户重试
    expect(store.jobs['pjob-4']).toBeTruthy()
    expect(ElMessageMock.error).toHaveBeenCalledWith('provisioning.preview_cancel_failed')
    wrapper.unmount()
    store.dismiss('pjob-4')
  })
})
