import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { useProjectContext } from '../useProjectContext'
import { useWorkspaceContext } from '../useWorkspaceContext'
import { useProjectEditing } from '../useProjectEditing'
import { useProjectJobs } from '../useProjectJobs'
import type { ProjectCollaboration } from '../useProjectCollaboration'
import type { WorkbenchNotifications } from '../notifications'

const mocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn() }))
vi.mock('@/utils/api', () => ({ default: mocks }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
function deferred() {
  let resolve!: (value: unknown) => void
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}
const unmounts: Array<() => void> = []
beforeEach(() => { mocks.get.mockReset(); mocks.put.mockReset(); mocks.post.mockReset() })
afterEach(() => { unmounts.splice(0).forEach(unmount => unmount()) })
function setup() {
  const wsId = ref('workspace')
  const taskId = ref('task')
  let project!: ReturnType<typeof useProjectContext>
  let workspace!: ReturnType<typeof useWorkspaceContext>
  let editing!: ReturnType<typeof useProjectEditing>
  const refresh = vi.fn()
  const sendCollabEvent = vi.fn()
  const notifySuccess = vi.fn()
  const notifications = {
    notifyError: vi.fn(), notifySuccess, notifyProjectSwaggerLocked: vi.fn(), notifyCurrentEndpointCreateLocked: vi.fn(),
    isAutoMockProjectLockError: () => false, isAutoMockEndpointLockError: () => false, isConflictError: () => false,
  } as unknown as WorkbenchNotifications
  const wrapper = mount(defineComponent({ setup() {
    project = useProjectContext(wsId, taskId, notifications)
    workspace = useWorkspaceContext(wsId)
    const jobs = useProjectJobs(project, notifications)
    editing = useProjectEditing(project, notifications, jobs, { sendCollabEvent } as unknown as ProjectCollaboration, refresh)
    return () => null
  } }))
  unmounts.push(() => wrapper.unmount())
  return { project, workspace, wsId, taskId, editing, refresh, sendCollabEvent, notifySuccess }
}

describe('workbench request ownership', () => {
  it('does not apply a case response belonging to the previously selected endpoint', async () => {
    const slow = deferred()
    mocks.get.mockReturnValueOnce(slow.promise).mockResolvedValueOnce({ data: { items: [{ id: 'new-case' }] } })
    const { project } = setup()
    project.selectedEndpointId.value = 'old'
    const oldRequest = project.loadMockCases()
    project.selectedEndpointId.value = 'new'
    await project.loadMockCases({ fallbackToFirst: true })
    slow.resolve({ data: { items: [{ id: 'old-case' }] } })
    await oldRequest
    expect(project.mockCases.value.map(item => item.id)).toEqual(['new-case'])
    expect(project.selectedMockCaseId.value).toBe('new-case')
  })

  it('keeps the newest endpoint search when responses arrive out of order', async () => {
    const slow = deferred()
    mocks.get.mockReturnValueOnce(slow.promise).mockResolvedValueOnce({ data: { items: [{ id: 'new' }] } })
    const { project } = setup()
    const oldRequest = project.loadEndpoints()
    await project.loadEndpoints()
    slow.resolve({ data: { items: [{ id: 'old' }] } })
    await oldRequest
    expect(project.endpoints.value.map(item => item.id)).toEqual(['new'])
  })

  it('discards a task response after its context was reset', async () => {
    const slow = deferred()
    mocks.get.mockReturnValue(slow.promise)
    const { project, taskId } = setup()
    const request = project.loadProject()
    taskId.value = 'other'
    project.resetTaskContext()
    slow.resolve({ data: { id: 'old-project' } })
    await request
    expect(project.project.value).toBeNull()
  })

  it('clears old workspace authorization immediately and ignores its late response', async () => {
    const slow = deferred()
    mocks.get.mockReturnValueOnce(slow.promise).mockResolvedValueOnce({ data: { permissions: { view_api_mock: false } } })
    const { workspace, wsId } = setup()
    workspace.permissions.value = { view_api_mock: true }
    const oldRequest = workspace.loadPermissions()
    wsId.value = 'other'
    expect(workspace.canView.value).toBe(false)
    expect(workspace.permissionsReady.value).toBe(false)
    await workspace.loadPermissions()
    slow.resolve({ data: { permissions: { view_api_mock: true } } })
    await oldRequest
    await flushPromises()
    expect(workspace.canView.value).toBe(false)
  })

  it('does not refresh or broadcast a completed document save in a different task', async () => {
    const slow = deferred()
    mocks.get.mockResolvedValueOnce({ data: { id: 'project' } })
    mocks.put.mockReturnValue(slow.promise)
    const { project, editing, taskId, refresh, sendCollabEvent, notifySuccess } = setup()
    await project.loadProject()
    const saving = editing.onSaveDocument({ content: '{}' })
    taskId.value = 'other'
    project.resetTaskContext()
    expect(editing.savingDocument.value).toBe(false)
    slow.resolve({ data: {} })
    await saving
    expect(refresh).not.toHaveBeenCalled()
    expect(sendCollabEvent).not.toHaveBeenCalled()
    expect(notifySuccess).not.toHaveBeenCalled()
  })

  it('does not select a saved case after its endpoint has changed', async () => {
    const slow = deferred()
    mocks.post.mockReturnValue(slow.promise)
    const { project, editing, sendCollabEvent } = setup()
    project.selectedEndpointId.value = 'old'
    const saving = editing.onSaveCase({
      name: 'case', description: null, is_default: false, mode: 'STATIC', status_code: 200, delay_ms: 0, enabled: true,
    })
    project.selectedEndpointId.value = 'new'
    project.selectedMockCaseId.value = 'new-case'
    slow.resolve({ data: { id: 'saved-old-case' } })
    await saving
    expect(project.selectedMockCaseId.value).toBe('new-case')
    expect(mocks.get).not.toHaveBeenCalled()
    expect(sendCollabEvent).not.toHaveBeenCalled()
  })
})
