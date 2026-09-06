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
    apiMock.post.mockResolvedValue({ data: { job_id: 'job-empty-workspace' } })
    systemConfigStoreMock.load.mockReset()
    systemConfigStoreMock.load.mockResolvedValue(undefined)
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
})
