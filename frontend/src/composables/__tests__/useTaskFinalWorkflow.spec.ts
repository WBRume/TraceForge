import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
}))

vi.mock('@/utils/api', () => ({
  default: apiMock,
}))

function workflowResponse(overrides = {}) {
  return {
    task: {
      id: 'task-1',
      workspace_id: 'ws-1',
      name: 'Final workflow task',
      status: 'DONE',
      requirement_count: 1,
      spec_count: 0,
      plan_count: 0,
      ai_run_count: 0,
      human_review_count: 1,
      human_delta_count: 0,
      evidence_count: 1,
      decision_count: 0,
      clarification_count: 0,
      coverage_status: 'verified',
      baseline_version: 0,
    },
    steps: [
      { key: 'expert_review', title: 'Expert Review', status: 'complete', blocking_count: 0 },
      { key: 'clarification', title: 'Clarification', status: 'complete', blocking_count: 0 },
      { key: 'final_summary', title: 'Final Summary', status: 'ready', blocking_count: 0 },
      { key: 'baseline', title: 'Baseline', status: 'blocked', blocking_count: 1 },
    ],
    reviews: [],
    review_targets: {
      SPEC: [],
      PLAN: [],
      AI_CHANGE: [],
      HUMAN_DELTA: [],
      EVIDENCE: [],
      DECISION: [],
      TASK_FILE: [],
    },
    clarifications: [],
    clarification_threads: {},
    final_summary: null,
    baseline: null,
    checklist: [],
    available_actions: [],
    readonly: false,
    can_write_final_workflow: true,
    can_resolve_clarification: true,
    ...overrides,
  }
}

describe('useTaskFinalWorkflow', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    apiMock.put.mockReset()
  })

  it('loads the aggregate final workflow state', async () => {
    const { useTaskFinalWorkflow } = await import('@/composables/useTaskFinalWorkflow')
    apiMock.get.mockResolvedValueOnce({ data: workflowResponse() })

    const workflow = useTaskFinalWorkflow()
    const result = await workflow.load('ws-1', 'task-1')

    expect(apiMock.get).toHaveBeenCalledWith('/workspaces/ws-1/workspace-assets/tasks/task-1/final-workflow')
    expect(result?.steps.map((step) => step.key)).toEqual([
      'expert_review',
      'clarification',
      'final_summary',
      'baseline',
    ])
    expect(workflow.readonlyState.value).toBe(false)
  })

  it('creates review items and refreshes the aggregate payload', async () => {
    const { useTaskFinalWorkflow } = await import('@/composables/useTaskFinalWorkflow')
    apiMock.post.mockResolvedValueOnce({
      data: workflowResponse({ reviews: [{ id: 'review-1', status: 'RESOLVED', target_refs: [] }] }),
    })

    const workflow = useTaskFinalWorkflow()
    const result = await workflow.createReview('ws-1', 'task-1', {
      title: 'Evidence review',
      body: 'Looks good.',
      target_refs: [{ target_type: 'EVIDENCE', target_id: 'evidence-1', label: 'Manual evidence' }],
    })

    expect(apiMock.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/workspace-assets/tasks/task-1/final-workflow/reviews',
      {
        title: 'Evidence review',
        body: 'Looks good.',
        target_refs: [{ target_type: 'EVIDENCE', target_id: 'evidence-1', label: 'Manual evidence' }],
      },
    )
    expect(result?.reviews[0].status).toBe('RESOLVED')
  })

  it('sends clarification messages through the message API', async () => {
    const { useTaskFinalWorkflow } = await import('@/composables/useTaskFinalWorkflow')
    apiMock.post.mockResolvedValueOnce({
      data: workflowResponse({ clarifications: [{ id: 'clarification-1', status: 'ANSWERED' }] }),
    })

    const workflow = useTaskFinalWorkflow()
    const result = await workflow.addClarificationMessage('ws-1', 'task-1', 'clarification-1', {
      entry_type: 'ANSWER',
      body: 'Confirmed scope.',
    })

    expect(apiMock.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/workspace-assets/tasks/task-1/final-workflow/clarifications/clarification-1/messages',
      { entry_type: 'ANSWER', body: 'Confirmed scope.' },
    )
    expect(result?.clarifications[0].status).toBe('ANSWERED')
  })

  it('sets readonly state when the task is baselined', async () => {
    const { useTaskFinalWorkflow } = await import('@/composables/useTaskFinalWorkflow')
    apiMock.post.mockResolvedValueOnce({
      data: workflowResponse({
        task: {
          ...workflowResponse().task,
          status: 'BASELINED',
          baseline_version: 1,
        },
        baseline: { id: 'baseline-1', workspace_id: 'ws-1', task_id: 'task-1', version: 1, is_rollback: false },
        readonly: true,
      }),
    })

    const workflow = useTaskFinalWorkflow()
    await workflow.baseline('ws-1', 'task-1')

    expect(apiMock.post).toHaveBeenCalledWith('/workspaces/ws-1/workspace-assets/tasks/task-1/final-workflow/baseline')
    expect(workflow.readonlyState.value).toBe(true)
    expect(workflow.lockMessage.value).toBe('Task is baselined and read-only.')
  })
})
