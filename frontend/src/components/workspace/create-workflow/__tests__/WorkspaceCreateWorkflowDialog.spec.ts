import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import WorkspaceCreateWorkflowDialog from '../WorkspaceCreateWorkflowDialog.vue'

const apiMock = vi.hoisted(() => ({
  post: vi.fn(),
}))

const managementApiMock = vi.hoisted(() => ({
  getProject: vi.fn(),
  getProjectRepoSet: vi.fn(),
  getRepoGroupTree: vi.fn(),
  listProjects: vi.fn(),
  listRepositories: vi.fn(),
  getRepositoryRefs: vi.fn(),
}))

const systemConfigStoreMock = vi.hoisted(() => ({
  projectProductManagementEnabled: false,
  workspaceRootDir: '',
  load: vi.fn(),
}))

vi.mock('@/utils/api', () => ({ default: apiMock }))
vi.mock('@/utils/error', () => ({ formatApiError: vi.fn((error: unknown) => String(error)) }))
vi.mock('@/services/managementApi', () => managementApiMock)
vi.mock('@/stores/systemConfig', () => ({ useSystemConfigStore: () => systemConfigStoreMock }))
vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))
vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn(), warning: vi.fn() },
}))

describe('WorkspaceCreateWorkflowDialog', () => {
  beforeEach(() => {
    apiMock.post.mockReset()
    apiMock.post.mockImplementation((url: string) => {
      if (url === '/workspaces/preflight') {
        return Promise.resolve({
          data: {
            name_conflict: false,
            name_conflict_workspaces: [],
            path_conflict: false,
            path_conflict_workspaces: [],
          },
        })
      }
      return Promise.resolve({ data: { job_id: 'job-empty-workspace' } })
    })
    systemConfigStoreMock.load.mockReset()
    systemConfigStoreMock.load.mockResolvedValue(undefined)
    systemConfigStoreMock.workspaceRootDir = ''
    managementApiMock.getRepoGroupTree.mockResolvedValue({ items: [] })
    managementApiMock.listRepositories.mockResolvedValue({ items: [], total: 0 })
  })

  it('allows creating a repository-free standalone workspace', async () => {
    const wrapper = mount(WorkspaceCreateWorkflowDialog, {
      props: { show: true },
      global: {
        mocks: { $t: (key: string) => key },
      },
    })

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('Script workspace')
    await inputs[1].setValue('Automation')
    await inputs[2].setValue('Scripts')
    await inputs[3].setValue('C:/workspaces/scripts')

    await wrapper.find('button.btn-primary').trigger('click')
    await flushPromises()

    const createButton = wrapper.find('button.btn-primary')
    expect(createButton.attributes('disabled')).toBeUndefined()

    await createButton.trigger('click')
    await flushPromises()

    expect(apiMock.post).toHaveBeenCalledWith('/workspaces', {
      name: 'Script workspace',
      description: undefined,
      project_path: 'C:/workspaces/scripts',
      project_name: 'Automation',
      product_name: 'Scripts',
      repositories: [],
    })
  })

  it('prefills project_path from workspace root dir and rejects paths outside base', async () => {
    systemConfigStoreMock.workspaceRootDir = 'D:\\sdd-root'
    const wrapper = mount(WorkspaceCreateWorkflowDialog, {
      props: { show: true },
      global: {
        mocks: { $t: (key: string) => key },
      },
    })

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('Script workspace')
    await inputs[1].setValue('Automation')
    await inputs[2].setValue('Scripts')

    // 输入名称后路径自动预填为 根目录/workspace/工作区名称（slug 化）
    const pathInput = inputs[3]
    expect((pathInput.element as HTMLInputElement).value).toBe(
      'D:\\sdd-root\\workspace\\Script workspace'
    )

    // 手动把路径改到 base 之外：下一步被禁用
    await pathInput.setValue('E:\\elsewhere\\ws')
    const nextButton = wrapper.find('button.btn-primary')
    expect(nextButton.attributes('disabled')).toBeDefined()

    // 改回 base 之内即可继续
    await pathInput.setValue('D:\\sdd-root\\workspace\\custom-ws')
    expect(nextButton.attributes('disabled')).toBeUndefined()
  })

  it('shows the conflict dialog at the basic step on Next and continues after confirm', async () => {
    apiMock.post.mockImplementation((url: string) => {
      if (url === '/workspaces/preflight') {
        return Promise.resolve({
          data: {
            name_conflict: true,
            name_conflict_workspaces: [{ id: 'ws-1', name: 'Script workspace', owner_name: 'User' }],
            path_conflict: true,
            path_conflict_workspaces: [
              { id: 'ws-2', name: 'Other WS', owner_name: 'User', project_path: 'C:/workspaces/scripts' },
            ],
          },
        })
      }
      return Promise.resolve({ data: { job_id: 'job-conflict-accepted' } })
    })

    const wrapper = mount(WorkspaceCreateWorkflowDialog, {
      props: { show: true },
      global: {
        mocks: { $t: (key: string) => key },
        stubs: { teleport: true },
      },
    })

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('Script workspace')
    await inputs[1].setValue('Automation')
    await inputs[2].setValue('Scripts')
    await inputs[3].setValue('C:/workspaces/scripts')

    // 基本信息步点击“下一步”即触发冲突预检并弹窗（无需等到最后一步创建）
    await wrapper.find('button.btn-primary').trigger('click')
    await flushPromises()

    expect(apiMock.post).toHaveBeenCalledWith('/workspaces/preflight', {
      name: 'Script workspace',
      project_path: 'C:/workspaces/scripts',
    })
    expect(apiMock.post).not.toHaveBeenCalledWith('/workspaces', expect.anything())
    const modal = wrapper.find('.modal')
    expect(modal.exists()).toBe(true)
    expect(modal.text()).toContain('conflict_title')
    // i18n mock 仅返回 key：通过文案 key 验证重名与目录冲突条目均已渲染
    expect(modal.text()).toContain('conflict_name_item')
    expect(modal.text()).toContain('conflict_path_item')

    // 用户确认后进入下一步（仓库确认），并不直接创建
    await modal.find('.confirm-btn').trigger('click')
    await flushPromises()
    expect(wrapper.find('.wf-step-item.active').text()).toContain('step_repos')
    expect(apiMock.post).not.toHaveBeenCalledWith('/workspaces', expect.anything())

    // 最后一步点击“创建工作区”：复用已缓存的预检结果，不再重复请求
    await wrapper.find('button.btn-primary').trigger('click')
    await flushPromises()

    const preflightCalls = apiMock.post.mock.calls.filter(
      (call) => call[0] === '/workspaces/preflight'
    )
    expect(preflightCalls).toHaveLength(1)
    expect(apiMock.post).toHaveBeenCalledWith('/workspaces', {
      name: 'Script workspace',
      description: undefined,
      project_path: 'C:/workspaces/scripts',
      project_name: 'Automation',
      product_name: 'Scripts',
      repositories: [],
    })
    wrapper.unmount()
  })

  it('stays on the basic step without creating when the user cancels the conflict dialog', async () => {
    apiMock.post.mockImplementation((url: string) => {
      if (url === '/workspaces/preflight') {
        return Promise.resolve({
          data: {
            name_conflict: true,
            name_conflict_workspaces: [{ id: 'ws-1', name: 'Script workspace' }],
            path_conflict: false,
            path_conflict_workspaces: [],
          },
        })
      }
      return Promise.resolve({ data: { job_id: 'job-should-not-create' } })
    })

    const wrapper = mount(WorkspaceCreateWorkflowDialog, {
      props: { show: true },
      global: {
        mocks: { $t: (key: string) => key },
        stubs: { teleport: true },
      },
    })

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('Script workspace')
    await inputs[1].setValue('Automation')
    await inputs[2].setValue('Scripts')
    await inputs[3].setValue('C:/workspaces/scripts')

    await wrapper.find('button.btn-primary').trigger('click')
    await flushPromises()

    const modal = wrapper.find('.modal')
    expect(modal.exists()).toBe(true)
    await modal.find('.btn-secondary').trigger('click')
    await flushPromises()

    // 取消后停留在基本信息步，未进入下一步，也未创建
    expect(wrapper.find('.wf-step-item.active').text()).toContain('step_basic')
    expect(apiMock.post).not.toHaveBeenCalledWith('/workspaces', expect.anything())
    wrapper.unmount()
  })
})
