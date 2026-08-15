import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { useDiagnosisDocs } from '@/composables/useDiagnosisDocs'

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
  ],
  total: 1,
}

const setup = () =>
  useDiagnosisDocs({
    wsId: () => 'ws-1',
    taskId: () => 'task-1',
  })

describe('useDiagnosisDocs', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
  })

  it('loads diagnosis document assets with the task filter', async () => {
    apiMock.get.mockResolvedValue({ data: assetsResponse })
    const model = setup()

    await model.loadDocs()

    expect(apiMock.get).toHaveBeenCalledWith('/workspaces/ws-1/assets', expect.objectContaining({
      params: expect.objectContaining({ task_id: 'task-1', asset_type: 'DIAGNOSIS_DOC' }),
    }))
    expect(model.docs.value).toHaveLength(1)
    expect(model.docs.value[0].name).toBe('issue.log')
  })

  it('fetches and stores document content on selection', async () => {
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.includes('/assets/asset-1')) {
        return { data: { id: 'asset-1', content_text: '2026-08-15 ERROR timeout' } }
      }
      return { data: assetsResponse }
    })
    const model = setup()
    await model.loadDocs()

    await model.selectDoc(model.docs.value[0])

    expect(apiMock.get).toHaveBeenCalledWith('/workspaces/ws-1/assets/asset-1')
    expect(model.activeDoc.value?.content_text).toContain('ERROR timeout')
  })

  it('uploads a diagnosis doc and refreshes the list', async () => {
    apiMock.get.mockResolvedValue({ data: assetsResponse })
    apiMock.post.mockResolvedValue({ data: { status: 'success', asset_id: 'asset-2' } })
    const model = setup()
    await model.loadDocs()
    expect(model.docs.value).toHaveLength(1)

    await model.uploadDoc(new File(['log'], 'issue2.log', { type: 'text/plain' }))

    expect(apiMock.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/tasks/task-1/upload-diagnosis-doc',
      expect.any(FormData),
      expect.objectContaining({ headers: expect.objectContaining({ 'Content-Type': 'multipart/form-data' }) }),
    )
  })

  it('loads code path and repositories', async () => {
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.endsWith('/tasks/task-1')) {
        return { data: { project_path: 'G:/repo/.sdd/task-1' } }
      }
      if (url.endsWith('/workspaces/ws-1')) {
        return { data: { repositories: [{ repo_name: 'backend', branch_name: 'main', state: 'READY' }] } }
      }
      return { data: assetsResponse }
    })
    const model = setup()

    await model.loadCodePath()
    await nextTick()

    expect(model.codePath.value).toBe('G:/repo/.sdd/task-1')
    expect(model.repos.value).toHaveLength(1)
    expect(model.repos.value[0].repo_name).toBe('backend')
  })
})
