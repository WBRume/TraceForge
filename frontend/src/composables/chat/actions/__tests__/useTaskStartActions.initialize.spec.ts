import { describe, expect, it, vi } from 'vitest'
import { useTaskStartActions } from '../useTaskStartActions'
const api = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn() }))
vi.mock('@/utils/api', () => ({ default: api }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('element-plus', () => ({ ElMessage: { error: vi.fn(), warning: vi.fn() } }))
vi.mock('@/utils/taskAwarenessIntent', () => ({ noteTaskRunInitiated: vi.fn() }))
function setup(reset: (command: any) => Promise<unknown>) {
  const task = { id: 'task', description: 'new round', skill_ids: [] }
  const noop = vi.fn(), done = vi.fn().mockResolvedValue(undefined)
  const actions = useTaskStartActions({
    getCurrentTask: () => task, getWorkspaceId: () => 'workspace',
    isTaskPreStart: { value: false }, isTaskProvisioning: { value: false }, canStartTask: { value: true },
    canManageTaskStatus: { value: true }, engineRunning: { value: false }, submissionsClear: noop,
    loadHistory: done, refreshActiveJobs: vi.fn().mockResolvedValue(false), resetConversationView: noop,
    applyTaskSessionPayload: noop, patchTask: noop, specDrawerClose: noop, scrollIfNotAnchored: noop,
    skills: { taskRuntimeSkills: { value: [] }, taskRuntimeSkillsLoading: { value: false }, showTaskSkillsDrawer: { value: false }, loadTaskRuntimeSkills: vi.fn().mockResolvedValue(true) },
    resolveActionError: () => 'error', initializationIdentity: vi.fn().mockResolvedValue({ client_id: 'desktop' }),
    resetForInitialization: reset, finishInitialization: done,
  })
  return actions
}
describe('local collaboration initialization', () => {
  it('waits for the native dual-repository receipt before starting the new round', async () => {
    api.post.mockReset().mockResolvedValueOnce({ data: { local_reset: { task_id: 'task', operation_id: 'operation' } } }).mockResolvedValueOnce({ data: { job: { id: 'job' } } })
    let complete!: (receipt: unknown) => void
    const reset = vi.fn(() => new Promise(resolve => { complete = resolve }))
    const actions = setup(reset)
    const pending = actions.initializeTaskWithReason()
    await vi.waitFor(() => expect(reset).toHaveBeenCalledOnce())
    expect(api.post).toHaveBeenCalledTimes(1)
    complete({ repositories: ['both-clean'] })
    expect(await pending).toBe(true)
    expect(api.post.mock.calls[1][1].local_reset_receipt).toEqual({ repositories: ['both-clean'] })
    expect(api.post.mock.calls[1][1].operation_id).toBe(api.post.mock.calls[0][1].operation_id)
  })
  it('keeps the operation after a native interruption and does not send an incomplete receipt', async () => {
    api.post.mockReset().mockResolvedValue({ data: { local_reset: { task_id: 'task' } } })
    const reset = vi.fn().mockRejectedValueOnce(new Error('Git lock')).mockResolvedValueOnce({ repositories: ['clean'] })
    const actions = setup(reset)
    expect(await actions.initializeTaskWithReason()).toBe(false)
    expect(api.post).toHaveBeenCalledTimes(1)
    const original = api.post.mock.calls[0][1].operation_id
    api.post.mockResolvedValueOnce({ data: { local_reset: { task_id: 'task' } } }).mockResolvedValueOnce({ data: { job: { id: 'job' } } })
    expect(await actions.initializeTaskWithReason()).toBe(true)
    expect(api.post.mock.calls[2][1].operation_id).toBe(original)
  })
})
