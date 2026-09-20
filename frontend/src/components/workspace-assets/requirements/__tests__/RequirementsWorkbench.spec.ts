import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createI18n } from 'vue-i18n'
import ElementPlus from 'element-plus'
import RequirementsWorkbench from '../RequirementsWorkbench.vue'
import RequirementImportDialog from '../RequirementImportDialog.vue'
import { useProvisioningStore } from '@/stores/provisioning'
import en from '@/locales/en.json'
import zh from '@/locales/zh.json'
import type { RequirementSummary } from '@/types/workspaceAssets'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

const routeMock = vi.hoisted(() => ({
  query: {} as Record<string, unknown>,
}))

const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
}))

const ElMessageMock = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => routeMock,
  useRouter: () => routerMock,
}))

vi.mock('@/utils/api', () => ({
  default: apiMock,
}))

vi.mock('element-plus', async (importOriginal) => {
  const actual = await importOriginal<typeof import('element-plus')>()
  return { ...actual, ElMessage: ElMessageMock }
})

const workspaceAssetsMock = vi.hoisted(() => ({
  loading: false,
  error: undefined,
  loadRequirements: vi.fn(async () => null),
  createRequirement: vi.fn(),
  updateRequirement: vi.fn(),
  createRequirementImportPreviewJob: vi.fn(),
  fetchRequirementPreviewJob: vi.fn(),
  listActiveRequirementPreviewJobs: vi.fn(),
  directImportRequirement: vi.fn(),
  confirmRequirementImport: vi.fn(),
  createRequirementSplitPreviewJob: vi.fn(),
  confirmRequirementSplit: vi.fn(),
  findRequirementSplitDraft: vi.fn(async () => null),
}))

vi.mock('@/composables/useWorkspaceAssets', () => ({
  useWorkspaceAssets: () => workspaceAssetsMock,
}))

function i18nPlugin(locale = 'zh') {
  return createI18n({ legacy: false, locale, messages: { en, zh } })
}

function requirement(overrides: Partial<RequirementSummary> = {}): RequirementSummary {
  return {
    id: 'req-1',
    workspace_id: 'ws-1',
    title: 'Validate payment state',
    body: 'Checkout requires a valid payment state.',
    status: 'READY',
    acceptance_criteria: ['Reject invalid payment state'],
    priority: 'P1',
    parent_requirement_id: null,
    parent_title: null,
    child_count: 0,
    children: [],
    can_link_task: true,
    import_batch_id: null,
    source_kind: 'document',
    source_uri: null,
    source_ref: 'PRD-1',
    source_metadata: null,
    coverage_summary: {
      coverage_status: 'waiting_evidence',
      coverage_reason: 'Derived from real Task process assets.',
      related_task_count: 1,
      evidence_count: 0,
      human_review_count: 0,
      human_delta_count: 0,
    },
    change_history_count: 1,
    related_task_count: 1,
    linked_tasks: [],
    created_at: null,
    updated_at: null,
    ...overrides,
  }
}

const splitPreviewPayload = (overrides: Record<string, unknown> = {}) => ({
  job_id: 'job-split-1',
  workspace_id: 'ws-1',
  status: 'PENDING',
  progress: 0,
  message: 'Requirement split preview queued',
  job_kind: 'REQUIREMENT_SPLIT_PREVIEW',
  requirement_id: 'req-1',
  requirement_title: 'Validate payment state',
  batch: null,
  ...overrides,
})

const mountWorkbench = () =>
  mount(RequirementsWorkbench, {
    props: {
      workspaceId: 'ws-1',
      requirements: [requirement()],
    },
    global: {
      plugins: [createPinia(), i18nPlugin('zh'), ElementPlus],
      stubs: { teleport: true },
    },
  })

async function clickSplitButton(wrapper: ReturnType<typeof mountWorkbench>) {
  const splitButton = wrapper.findAll('button').find((btn) => btn.text().includes('拆分'))
  expect(splitButton, 'split row action should be rendered for parent requirements').toBeTruthy()
  await splitButton!.trigger('click')
  await flushPromises()
}

async function confirmSplitModal(wrapper: ReturnType<typeof mountWorkbench>) {
  const confirmButton = wrapper
    .find('.modal-actions')
    .findAll('button')
    .find((btn) => btn.text().includes('开始拆分'))
  expect(confirmButton, 'split confirm modal should be open').toBeTruthy()
  await confirmButton!.trigger('click')
  await flushPromises()
  await flushPromises()
}

describe('RequirementsWorkbench split preview', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    apiMock.get.mockResolvedValue({ data: splitPreviewPayload({ status: 'RUNNING', progress: 16 }) })
    apiMock.post.mockResolvedValue({ data: {} })
    routeMock.query = {}
    routerMock.push.mockReset()
    routerMock.replace.mockReset()
    workspaceAssetsMock.loadRequirements.mockClear()
    workspaceAssetsMock.listActiveRequirementPreviewJobs.mockClear()
    workspaceAssetsMock.listActiveRequirementPreviewJobs.mockResolvedValue([])
    ElMessageMock.error.mockClear()
  })

  it('asks for confirmation before starting the AI split preview', async () => {
    workspaceAssetsMock.createRequirementSplitPreviewJob.mockResolvedValue(splitPreviewPayload())

    const wrapper = mountWorkbench()
    await flushPromises()

    await clickSplitButton(wrapper)

    // 二次确认弹窗出现，确认前绝不发起 CLI 作业
    const modalActions = wrapper.find('.modal-actions')
    expect(modalActions.exists()).toBe(true)
    expect(wrapper.text()).toContain('发起 AI 需求拆分')
    expect(wrapper.text()).toContain('Validate payment state')
    expect(apiMock.post).not.toHaveBeenCalled()
    expect(workspaceAssetsMock.createRequirementSplitPreviewJob).not.toHaveBeenCalled()

    // 取消：关闭确认弹窗，不发起作业
    const cancelButton = modalActions.findAll('button').find((btn) => btn.text().includes('取消'))
    await cancelButton!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.modal-actions').exists()).toBe(false)
    expect(apiMock.post).not.toHaveBeenCalled()
    expect(wrapper.findComponent(RequirementImportDialog).props('open')).toBe(false)

    // 再次点击拆分并确认：发起拆分预览作业并打开进度弹窗
    await clickSplitButton(wrapper)
    await confirmSplitModal(wrapper)

    expect(workspaceAssetsMock.createRequirementSplitPreviewJob).toHaveBeenCalledWith('ws-1', 'req-1')
    expect(wrapper.find('.modal-actions').exists()).toBe(false)
    const dialog = wrapper.findAllComponents(RequirementImportDialog).find((d) => d.props('mode') === 'split')!
    expect(dialog.props('open')).toBe(true)
    expect(dialog.props('previewJob')?.job_id).toBe('job-split-1')
    expect(dialog.text()).toContain('AI Preview 生成中')
  })

  it('rebinds an active split preview job from the server instead of creating a duplicate', async () => {
    // store 无记录（刷新/卡片被清理），但服务端仍有该需求进行中的拆分作业
    workspaceAssetsMock.listActiveRequirementPreviewJobs.mockResolvedValue([
      splitPreviewPayload({ job_id: 'job-server-1', status: 'RUNNING', progress: 40 }),
    ])
    // 轮询返回同一作业的进度
    apiMock.get.mockResolvedValue({
      data: splitPreviewPayload({ job_id: 'job-server-1', status: 'RUNNING', progress: 40 }),
    })

    const wrapper = mountWorkbench()
    await flushPromises()

    await clickSplitButton(wrapper)
    await confirmSplitModal(wrapper)

    // 回绑服务端作业，绝不重复发起新 CLI
    expect(workspaceAssetsMock.createRequirementSplitPreviewJob).not.toHaveBeenCalled()
    const dialog = wrapper.findAllComponents(RequirementImportDialog).find((d) => d.props('mode') === 'split')!
    expect(dialog.props('open')).toBe(true)
    expect(dialog.props('previewJob')?.job_id).toBe('job-server-1')
    expect(dialog.props('previewJob')?.status).toBe('RUNNING')
  })

  it('closing the progress dialog cancels the running CLI job before closing', async () => {
    apiMock.get.mockResolvedValue({
      data: splitPreviewPayload({ status: 'RUNNING', progress: 20 }),
    })
    apiMock.post.mockResolvedValue({ data: {} })

    const wrapper = mountWorkbench()
    await flushPromises()

    const store = useProvisioningStore()
    store.trackRequirementPreviewJob({
      jobId: 'job-split-1',
      workspaceId: 'ws-1',
      kind: 'requirement_split_preview',
      requirementId: 'req-1',
      requirementTitle: 'Validate payment state',
    })
    await flushPromises()

    // store 已有进行中的作业：点击拆分并确认后直接回绑弹窗，不再发起新作业
    await clickSplitButton(wrapper)
    await confirmSplitModal(wrapper)
    const dialog = wrapper.findAllComponents(RequirementImportDialog).find((d) => d.props('mode') === 'split')!
    expect(dialog.props('open')).toBe(true)
    expect(workspaceAssetsMock.createRequirementSplitPreviewJob).not.toHaveBeenCalled()

    // 右上角 X：等待后端取消受理后再关闭弹窗
    const closeButton = dialog.findAll('.close-btn').at(-1)!
    await closeButton.trigger('click')
    await flushPromises()

    expect(apiMock.post).toHaveBeenCalledWith('/workspaces/ws-1/ai-jobs/job-split-1/cancel')
    expect(dialog.props('open')).toBe(false)
    // 取消受理后作业保留（cancelRequested），轮询收敛 CANCELLED 后由 store 自动清理
    expect(store.jobs['job-split-1']).toBeTruthy()
    expect(store.jobs['job-split-1'].cancelRequested).toBe(true)
  })

  it('keeps the progress dialog open when the cancel request fails', async () => {
    apiMock.get.mockResolvedValue({
      data: splitPreviewPayload({ status: 'RUNNING', progress: 20 }),
    })
    apiMock.post.mockRejectedValue({ response: { status: 500 } })

    const wrapper = mountWorkbench()
    await flushPromises()

    const store = useProvisioningStore()
    store.trackRequirementPreviewJob({
      jobId: 'job-split-1',
      workspaceId: 'ws-1',
      kind: 'requirement_split_preview',
      requirementId: 'req-1',
      requirementTitle: 'Validate payment state',
    })
    await flushPromises()

    await clickSplitButton(wrapper)
    await confirmSplitModal(wrapper)
    const dialog = wrapper.findAllComponents(RequirementImportDialog).find((d) => d.props('mode') === 'split')!
    expect(dialog.props('open')).toBe(true)

    const closeButton = dialog.findAll('.close-btn').at(-1)!
    await closeButton.trigger('click')
    await flushPromises()

    // 取消失败：明确报错并保持弹窗打开（作业仍在后台运行），不静默泄漏 CLI
    expect(apiMock.post).toHaveBeenCalledWith('/workspaces/ws-1/ai-jobs/job-split-1/cancel')
    expect(ElMessageMock.error).toHaveBeenCalledWith('取消预览失败，请稍后重试。')
    expect(dialog.props('open')).toBe(true)
  })
})
