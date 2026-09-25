import { describe, expect, it } from 'vitest'
import { buildTaskCreatePayload, validateTaskDraft } from '../lib/taskPayload'
import type { TaskDraftSnapshot, WorkspaceRepo } from '../types'

const draft = (overrides: Partial<TaskDraftSnapshot> = {}): TaskDraftSnapshot => ({
  taskType: 'DEVELOPMENT',
  name: '研发任务',
  description: '做点什么',
  phenomenon: '',
  priority: 'P2',
  sopAutoRun: false,
  requirementDurationHours: 8,
  specFile: null,
  diagnosisFiles: [],
  ...overrides,
})

const repos: WorkspaceRepo[] = [
  { repository_id: 'repo-1', repo_name: 'frontend', repo_url: '' },
  { repository_id: 'repo-2', repo_name: 'backend', repo_url: '' },
]

const payloadCtx = (overrides: Partial<Parameters<typeof buildTaskCreatePayload>[1]> = {}) => ({
  repos,
  selectedRepoIds: [] as string[],
  branchOverrides: {} as Record<string, string>,
  skillIds: [] as string[],
  ...overrides,
})

describe('validateTaskDraft', () => {
  it('requires a phenomenon for diagnosis tasks', () => {
    expect(
      validateTaskDraft(draft({ taskType: 'DIAGNOSIS', phenomenon: ' ' }), { reposTotal: 0, selectedRepoCount: 0 }),
    ).toEqual({ key: 'diagnosis.phenomenon_required', severity: 'error' })
  })

  it('requires at least one selected repo when the workspace has repos', () => {
    expect(validateTaskDraft(draft(), { reposTotal: 2, selectedRepoCount: 0 })).toEqual({
      key: 'dashboard.task_repo_required',
      severity: 'warning',
    })
  })

  it('passes a complete diagnosis draft with repos selected', () => {
    expect(
      validateTaskDraft(draft({ taskType: 'DIAGNOSIS', phenomenon: '超时' }), { reposTotal: 2, selectedRepoCount: 1 }),
    ).toBeNull()
  })

  it('passes a development draft without repos', () => {
    expect(validateTaskDraft(draft(), { reposTotal: 0, selectedRepoCount: 0 })).toBeNull()
  })
})

describe('buildTaskCreatePayload', () => {
  it('preserves the selected local resource revision for server validation', () => {
    const execution = { location: 'LOCAL' as const, resource_id: 'mine', profile_revision: 3 }
    expect(buildTaskCreatePayload(draft({ execution }), payloadCtx()).execution).toEqual(execution)
    expect(buildTaskCreatePayload(draft({ execution: { location: 'SERVER' } }), payloadCtx())).not.toHaveProperty('execution')
  })
  it('builds a development payload with duration and skills', () => {
    const payload = buildTaskCreatePayload(
      draft(),
      payloadCtx({ selectedRepoIds: ['repo-1', 'repo-2'], skillIds: ['skill-1'] }),
    )
    expect(payload).toEqual({
      name: '研发任务',
      task_type: 'DEVELOPMENT',
      description: '做点什么',
      requirement_duration_hours: 8,
      skill_ids: ['skill-1'],
    })
  })

  it('builds a diagnosis payload without description', () => {
    const payload = buildTaskCreatePayload(
      draft({ taskType: 'DIAGNOSIS', phenomenon: '接口偶发超时', priority: 'P1' }),
      payloadCtx(),
    )
    expect(payload).toEqual({
      name: '研发任务',
      task_type: 'DIAGNOSIS',
      phenomenon: '接口偶发超时',
      priority: 'P1',
      skill_ids: [],
    })
    expect(payload.description).toBeUndefined()
  })

  it('sends sop_auto_run only for diagnosis tasks when the main switch is on', () => {
    const on = buildTaskCreatePayload(
      draft({ taskType: 'DIAGNOSIS', phenomenon: '接口偶发超时', sopAutoRun: true }),
      payloadCtx(),
    )
    expect(on.sop_auto_run).toBe(true)
    const off = buildTaskCreatePayload(
      draft({ taskType: 'DIAGNOSIS', phenomenon: '接口偶发超时' }),
      payloadCtx(),
    )
    expect(off).not.toHaveProperty('sop_auto_run')
    const development = buildTaskCreatePayload(draft({ sopAutoRun: true }), payloadCtx())
    expect(development).not.toHaveProperty('sop_auto_run')
  })

  it('omits repository_ids when the selection equals all repos', () => {
    const payload = buildTaskCreatePayload(draft(), payloadCtx({ selectedRepoIds: ['repo-1', 'repo-2'] }))
    expect(payload.repository_ids).toBeUndefined()
  })

  it('omits repository_ids when nothing is selected', () => {
    const payload = buildTaskCreatePayload(draft(), payloadCtx())
    expect(payload.repository_ids).toBeUndefined()
  })

  it('sends repository_ids only for a proper subset', () => {
    const payload = buildTaskCreatePayload(draft(), payloadCtx({ selectedRepoIds: ['repo-2'] }))
    expect(payload.repository_ids).toEqual(['repo-2'])
  })

  it('sends trimmed branch overrides for selected repos only', () => {
    const payload = buildTaskCreatePayload(
      draft(),
      payloadCtx({
        selectedRepoIds: ['repo-1', 'repo-2'],
        branchOverrides: { 'repo-1': ' hotfix/a ', 'repo-3': 'ignored' },
      }),
    )
    expect(payload.repository_branches).toEqual([{ repository_id: 'repo-1', branch_name: 'hotfix/a' }])
  })
})
