import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import DiagnosisDocsDrawer from '@/components/chat/DiagnosisDocsDrawer.vue'

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

const assetsResponse = {
  items: [
    {
      id: 'asset-1',
      name: 'issue.log',
      asset_type: 'DIAGNOSIS_DOC',
      source_ext: '.log',
      source_file_name: 'issue.log',
      created_at: '2026-08-15T10:00:00Z',
    },
    {
      id: 'asset-2',
      name: 'req.md',
      asset_type: 'DIAGNOSIS_DOC',
      source_ext: '.md',
      source_file_name: 'req.md',
      created_at: '2026-08-15T10:01:00Z',
    },
  ],
  total: 2,
}

const mountDrawer = () =>
  mount(DiagnosisDocsDrawer, {
    props: { open: true, wsId: 'ws-1', taskId: 'task-1' },
  })

describe('DiagnosisDocsDrawer', () => {
  it('loads and lists diagnosis documents', async () => {
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.includes('/assets')) {
        return { data: assetsResponse }
      }
      if (url.endsWith('/tasks/task-1')) {
        return { data: { project_path: 'G:/repo/.sdd/diag-task-1' } }
      }
      if (url.endsWith('/workspaces/ws-1')) {
        return { data: { repositories: [{ repo_name: 'backend', branch_name: 'main' }] } }
      }
      return { data: {} }
    })

    const wrapper = mountDrawer()
    await flushPromises()

    expect(apiMock.get).toHaveBeenCalledWith('/workspaces/ws-1/assets', expect.objectContaining({
      params: expect.objectContaining({ task_id: 'task-1', asset_type: 'DIAGNOSIS_DOC' }),
    }))
    expect(wrapper.text()).toContain('issue.log')
    expect(wrapper.text()).toContain('req.md')
  })

  it('shows document content preview on selection', async () => {
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.includes('/assets')) {
        if (url.includes('/assets/asset-1')) {
          return { data: { id: 'asset-1', content_text: '2026-08-15 ERROR timeout' } }
        }
        return { data: assetsResponse }
      }
      return { data: {} }
    })

    const wrapper = mountDrawer()
    await flushPromises()

    const docButtons = wrapper.findAll('.diag-doc-item')
    expect(docButtons.length).toBe(2)
    await docButtons[0].trigger('click')
    await flushPromises()

    expect(apiMock.get).toHaveBeenCalledWith('/workspaces/ws-1/assets/asset-1')
    expect(wrapper.find('.diag-doc-preview').text()).toContain('2026-08-15 ERROR timeout')
  })

  it('switches to code path tab with task path and repos', async () => {
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.includes('/assets')) {
        return { data: assetsResponse }
      }
      if (url.endsWith('/tasks/task-1')) {
        return { data: { project_path: 'G:/repo/.sdd/diag-task-1' } }
      }
      if (url.endsWith('/workspaces/ws-1')) {
        return { data: { repositories: [
          { repo_name: 'backend', branch_name: 'main', repo_url: 'https://g/backend.git', state: 'READY' },
        ] } }
      }
      return { data: {} }
    })

    const wrapper = mountDrawer()
    await flushPromises()

    const codeTab = wrapper.findAll('.diag-tab').find((tab) => tab.text().includes('diagnosis.code_path_tab'))
    await codeTab!.trigger('click')

    expect(wrapper.find('.diag-code-path').text()).toContain('G:/repo/.sdd/diag-task-1')
    expect(wrapper.text()).toContain('backend')
  })

  it('hides nothing when closed (renders nothing)', () => {
    const wrapper = mount(DiagnosisDocsDrawer, {
      props: { open: false, wsId: 'ws-1', taskId: 'task-1' },
    })
    expect(wrapper.find('.diag-drawer').exists()).toBe(false)
  })
})
