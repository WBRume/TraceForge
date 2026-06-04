import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { SpecCoverageMatrixRow } from '@/types/workspaceAssets'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('@/utils/api', () => ({
  default: apiMock,
}))

describe('useWorkspaceAssets', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    apiMock.patch.mockReset()
    apiMock.delete.mockReset()
  })

  it('maps empty requirement responses into shared empty and connection state', async () => {
    const { useWorkspaceAssets } = await import('@/composables/useWorkspaceAssets')
    apiMock.get.mockResolvedValueOnce({
      data: {
        workspace_id: 'ws-1',
        items: [],
        total: 0,
        state: { empty: true, message: 'Waiting for requirement source connection.' },
        connection_status: [
          {
            key: 'requirement_source',
            label: 'Requirement source',
            state: 'NOT_CONNECTED',
            detail: 'Waiting for requirement source connection.',
          },
        ],
      },
    })

    const assets = useWorkspaceAssets()
    const result = await assets.loadRequirements('ws-1')

    expect(apiMock.get).toHaveBeenCalledWith('/workspaces/ws-1/workspace-assets/requirements')
    expect(result?.state.empty).toBe(true)
    expect(assets.requirements.value?.total).toBe(0)
    expect(assets.connectionStatus.value[0].state).toBe('NOT_CONNECTED')
    expect(assets.isEmpty.value).toBe(true)
  })

  it('keeps real requirement linked tasks in the read-only response', async () => {
    const { useWorkspaceAssets } = await import('@/composables/useWorkspaceAssets')
    apiMock.get.mockResolvedValueOnce({
      data: {
        workspace_id: 'ws-1',
        items: [
          {
            id: 'req-1',
            workspace_id: 'ws-1',
            title: 'Checkout must validate payment state',
            status: 'ACTIVE',
            related_task_count: 1,
            linked_tasks: [
              {
                link_id: 'link-1',
                task_id: 'task-1',
                task_name: 'Implement checkout',
                task_status: 'PLANNING',
                current_phase: 'spec',
                relation_type: 'COVERS',
                coverage_status: 'waiting_human_confirmation',
              },
            ],
          },
        ],
        total: 1,
        state: { empty: false },
        connection_status: [
          {
            key: 'requirement_source',
            label: 'Requirement source',
            state: 'AVAILABLE',
          },
        ],
      },
    })

    const assets = useWorkspaceAssets()
    const result = await assets.loadRequirements('ws-1')

    expect(result?.items[0].linked_tasks?.[0].task_id).toBe('task-1')
    expect(result?.items[0].linked_tasks?.[0].relation_type).toBe('COVERS')
    expect(assets.isEmpty.value).toBe(false)
  })

  it('passes requirement table query parameters to the read endpoint', async () => {
    const { useWorkspaceAssets } = await import('@/composables/useWorkspaceAssets')
    apiMock.get.mockResolvedValueOnce({
      data: {
        workspace_id: 'ws-1',
        items: [],
        total: 0,
        page: 2,
        page_size: 20,
        scope: 'children',
        state: { empty: true },
        connection_status: [],
      },
    })

    const assets = useWorkspaceAssets()
    await assets.loadRequirements('ws-1', {
      q: 'payment',
      scope: 'children',
      sort_by: 'updated_at',
      sort_order: 'desc',
      page: 2,
      page_size: 20,
    })

    expect(apiMock.get).toHaveBeenCalledWith(
      '/workspaces/ws-1/workspace-assets/requirements',
      {
        params: {
          q: 'payment',
          scope: 'children',
          sort_by: 'updated_at',
          sort_order: 'desc',
          page: 2,
          page_size: 20,
        },
      },
    )
  })

  it('maps task detail process asset fields without fabricating adoption', async () => {
    const { useWorkspaceAssets } = await import('@/composables/useWorkspaceAssets')
    apiMock.get.mockResolvedValueOnce({
      data: {
        task: {
          id: 'task-1',
          workspace_id: 'ws-1',
          name: 'Implement checkout',
          status: 'PLANNING',
          requirement_count: 1,
          spec_count: 1,
          plan_count: 1,
          ai_run_count: 1,
          human_review_count: 0,
          human_delta_count: 0,
          evidence_count: 0,
          decision_count: 0,
          clarification_count: 0,
          coverage_status: 'waiting_evidence',
        },
        requirement_links: [],
        specs: [
          {
            id: 'spec-1',
            asset_type: 'SPEC',
            title: 'Checkout spec',
            status: 'AVAILABLE',
            content_text: 'Validate payment state.',
            content_json: { requirement_understanding: 'Payment state must be valid.' },
          },
        ],
        plans: [
          {
            id: 'plan-1',
            asset_type: 'PLAN',
            title: 'Checkout plan',
            status: 'AVAILABLE',
            content_json: { implementation_steps: ['Update checkout service.'] },
          },
        ],
        plan_nodes: [],
        ai_runs: [
          {
            id: 'job-1',
            channel: 'TASK_CHAT',
            status: 'SUCCESS',
            progress: 100,
            input_summary: 'Implement checkout validation.',
            output_summary: 'Proposed validation patch.',
            adoption_status: 'not_available',
          },
        ],
        ai_outputs: [],
        human_reviews: [],
        human_deltas: [],
        evidence: [],
        decisions: [],
        clarifications: [],
        process_summary: {
          spec_status: 'available',
          plan_status: 'available',
          ai_run_status: 'available',
          human_review_status: 'empty',
          human_delta_status: 'empty',
          evidence_status: 'empty',
          coverage_status: 'waiting_evidence',
          risk_status: 'not_available',
        },
        connection_status: [],
      },
    })

    const assets = useWorkspaceAssets()
    const result = await assets.loadTaskDetail('ws-1', 'task-1')

    expect(apiMock.get).toHaveBeenCalledWith('/workspaces/ws-1/workspace-assets/tasks/task-1')
    expect(result?.specs[0].content_json?.requirement_understanding).toBe('Payment state must be valid.')
    expect(result?.plans[0].content_json?.implementation_steps).toEqual(['Update checkout service.'])
    expect(result?.ai_runs[0].input_summary).toBe('Implement checkout validation.')
    expect(result?.ai_runs[0].output_summary).toBe('Proposed validation patch.')
    expect(result?.ai_runs[0].adoption_status).toBe('not_available')
  })

  it('keeps Spec Coverage Matrix rows as derived traceability data', async () => {
    const { useWorkspaceAssets } = await import('@/composables/useWorkspaceAssets')
    apiMock.get.mockResolvedValueOnce({
      data: {
        workspace_id: 'ws-1',
        views: [
          {
            key: 'spec_coverage_matrix',
            title: 'Spec Coverage Matrix',
            view_type: 'derived_matrix',
            total: 1,
            state: { empty: false },
            items: [
              {
                id: 'req-1:task-1',
                requirement_id: 'req-1',
                requirement_title: 'Checkout must validate payment state',
                task_id: 'task-1',
                task_name: 'Implement checkout',
                relation_type: 'COVERS',
                spec_status: 'available',
                plan_status: 'available',
                ai_run_status: 'available',
                human_review_status: 'empty',
                human_delta_status: 'available',
                evidence_status: 'empty',
                coverage_status: 'human_modified',
                coverage_reason: 'Human Delta exists and can be traced from this Task.',
                trace_refs: {
                  spec_ids: ['spec-1'],
                  plan_ids: ['plan-1'],
                  ai_run_ids: ['job-1'],
                  human_review_ids: [],
                  human_delta_ids: ['delta-1'],
                  evidence_ids: [],
                  decision_ids: [],
                  clarification_ids: [],
                },
              },
            ],
          },
        ],
        connection_status: [
          {
            key: 'traceable_assets',
            label: 'Traceable assets',
            state: 'AVAILABLE',
          },
        ],
      },
    })

    const assets = useWorkspaceAssets()
    const result = await assets.loadTraceability('ws-1')
    const row = result?.views[0].items[0] as SpecCoverageMatrixRow | undefined

    expect(apiMock.get).toHaveBeenCalledWith('/workspaces/ws-1/workspace-assets/traceability')
    expect(row?.requirement_id).toBe('req-1')
    expect(row?.coverage_status).toBe('human_modified')
    expect(row?.trace_refs.human_delta_ids).toEqual(['delta-1'])
  })

  it('keeps the task detail skeleton route local without calling the API', async () => {
    const {
      WORKSPACE_ASSET_TASK_DETAIL_SKELETON_ID,
      useWorkspaceAssets,
    } = await import('@/composables/useWorkspaceAssets')

    const assets = useWorkspaceAssets()
    const result = await assets.loadTaskDetail('ws-1', WORKSPACE_ASSET_TASK_DETAIL_SKELETON_ID)

    expect(result).toBeNull()
    expect(apiMock.get).not.toHaveBeenCalled()
    expect(assets.taskDetail.value).toBeNull()
    expect(assets.error.value).toBeNull()
  })

  it('calls requirement write endpoints without treating coverage as editable data', async () => {
    const { useWorkspaceAssets } = await import('@/composables/useWorkspaceAssets')
    apiMock.post.mockResolvedValueOnce({
      data: {
        requirement: {
          id: 'req-1',
          workspace_id: 'ws-1',
          title: 'Checkout requirement',
          status: 'READY',
          acceptance_criteria: [],
          coverage_summary: {
            coverage_status: 'not_available',
            coverage_reason: 'Coverage is derived.',
            related_task_count: 0,
            evidence_count: 0,
            human_review_count: 0,
            human_delta_count: 0,
          },
          change_history_count: 1,
          related_task_count: 0,
          linked_tasks: [],
        },
        linked_tasks: [],
        audit_logs: [],
      },
    })

    const assets = useWorkspaceAssets()
    const result = await assets.createRequirement('ws-1', {
      title: 'Checkout requirement',
      status: 'READY',
      change_reason: 'Manual capture',
    })

    expect(apiMock.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/workspace-assets/requirements',
      {
        title: 'Checkout requirement',
        status: 'READY',
        change_reason: 'Manual capture',
      },
    )
    expect(result?.requirement.coverage_summary.coverage_status).toBe('not_available')
  })

  it('creates AI preview through the async job response and preserves task prompts', async () => {
    const { useWorkspaceAssets } = await import('@/composables/useWorkspaceAssets')
    apiMock.post.mockResolvedValueOnce({
      data: {
        job_id: 'job-preview-1',
        workspace_id: 'ws-1',
        status: 'SUCCESS',
        progress: 100,
        message: 'Requirement AI preview created',
        batch: {
          id: 'batch-1',
          workspace_id: 'ws-1',
          status: 'PREVIEW',
          item_count: 1,
          confirmed_count: 0,
          items: [
            {
              id: 'item-1',
              title: 'Payment validation',
              body: 'Validate payment state.',
              acceptance_criteria: ['Reject invalid payment state'],
              task_prompt: 'Implement payment validation task.',
              order_index: 0,
              status: 'PENDING',
            },
          ],
        },
      },
    })

    const assets = useWorkspaceAssets()
    const result = await assets.createRequirementImportPreview('ws-1', {
      text: '# Payment validation',
      source_kind: 'document',
    })

    expect(apiMock.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/workspace-assets/requirements/imports',
      expect.any(FormData),
    )
    expect(result?.items[0].task_prompt).toBe('Implement payment validation task.')
    expect(apiMock.get).not.toHaveBeenCalled()
  })

  it('directly imports a single Requirement without using preview confirmation', async () => {
    const { useWorkspaceAssets } = await import('@/composables/useWorkspaceAssets')
    apiMock.post.mockResolvedValueOnce({
      data: {
        requirement: {
          id: 'req-direct',
          workspace_id: 'ws-1',
          title: 'Imported file',
          status: 'DRAFT',
          acceptance_criteria: [],
          coverage_summary: {
            coverage_status: 'not_available',
            coverage_reason: 'Coverage is derived.',
            related_task_count: 0,
            evidence_count: 0,
            human_review_count: 0,
            human_delta_count: 0,
          },
          change_history_count: 1,
          related_task_count: 0,
          linked_tasks: [],
        },
        linked_tasks: [],
        audit_logs: [],
      },
    })

    const assets = useWorkspaceAssets()
    const result = await assets.directImportRequirement('ws-1', {
      text: '# Imported file',
      source_kind: 'document',
      change_reason: 'Import as one Requirement',
    })

    expect(apiMock.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/workspace-assets/requirements/imports/direct',
      expect.any(FormData),
    )
    expect(result?.requirement.id).toBe('req-direct')
  })
})
