import { mount, RouterLinkStub } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import SpecCoverageMatrix from '../SpecCoverageMatrix.vue'
import type { SpecCoverageMatrixRow } from '@/types/workspaceAssets'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}))

const baseRow: SpecCoverageMatrixRow = {
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
  human_delta_status: 'empty',
  evidence_status: 'empty',
  coverage_status: 'evidence_missing',
  coverage_reason: 'Process records exist, but no real Evidence reference is attached.',
  trace_refs: {
    spec_ids: ['spec-1'],
    plan_ids: ['plan-1'],
    ai_run_ids: ['job-1'],
    human_review_ids: [],
    human_delta_ids: [],
    evidence_ids: [],
    decision_ids: [],
    clarification_ids: [],
  },
}

describe('SpecCoverageMatrix', () => {
  it('renders matrix columns, row content, and drill-down links', () => {
    const wrapper = mount(SpecCoverageMatrix, {
      props: {
        rows: [baseRow],
        workspaceId: 'ws-1',
      },
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })

    expect(wrapper.text()).toContain('workspace_assets.traceability.matrix.columns.requirement')
    expect(wrapper.text()).toContain('workspace_assets.traceability.matrix.columns.related_task')
    expect(wrapper.text()).toContain('workspace_assets.traceability.matrix.columns.coverage_status')
    expect(wrapper.text()).toContain('Checkout must validate payment state')
    expect(wrapper.text()).toContain('Implement checkout')
    expect(wrapper.text()).toContain('Process records exist, but no real Evidence reference is attached.')

    const links = wrapper.findAllComponents(RouterLinkStub)
    expect(links.some((link) => {
      const to = link.props('to')
      return typeof to === 'object' && to.name === 'workspaceAssetsRequirementDetail' && to.params?.requirementId === 'req-1'
    })).toBe(true)
    expect(links.some((link) => link.props('to') === '/ws/ws-1/assets/tasks/task-1')).toBe(true)
  })

  it('shows an empty state when no real matrix rows are derived', () => {
    const wrapper = mount(SpecCoverageMatrix, {
      props: {
        rows: [],
        workspaceId: 'ws-1',
      },
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })

    expect(wrapper.text()).toContain('workspace_assets.traceability.matrix.empty_title')
    expect(wrapper.text()).toContain('workspace_assets.traceability.matrix.empty_body')
  })

  it('does not present a non-verified row as verified or evidence-complete', () => {
    const wrapper = mount(SpecCoverageMatrix, {
      props: {
        rows: [baseRow],
        workspaceId: 'ws-1',
      },
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })

    const rowText = wrapper.find('tbody tr').text()
    expect(rowText).toContain('workspace_assets.traceability.matrix.status.evidence_missing')
    expect(rowText).not.toContain('workspace_assets.traceability.matrix.status.verified')
    expect(rowText).not.toContain('Evidence Complete')
  })
})
