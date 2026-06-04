import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import ElementPlus from 'element-plus'
import zh from '@/locales/zh.json'
import en from '@/locales/en.json'
import BaselineStep from '../BaselineStep.vue'
import ClarificationThreadStep from '../ClarificationThreadStep.vue'
import ExpertReviewStep from '../ExpertReviewStep.vue'
import FinalWorkflowStepper from '../FinalWorkflowStepper.vue'
import ReviewTargetPreviewDrawer from '../ReviewTargetPreviewDrawer.vue'
import ReviewTargetPicker from '../ReviewTargetPicker.vue'
import WorkflowChecklist from '../WorkflowChecklist.vue'
import type { BaselineCheckItem, HumanReview, ReviewTarget, ReviewTargetPreviewResponse, ReviewTargetType, TaskFinalWorkflowStep } from '@/types/workspaceAssets'

function i18nPlugin(locale = 'zh') {
  return createI18n({
    legacy: false,
    locale,
    fallbackLocale: 'en',
    messages: { zh, en },
  })
}

const global = {
  plugins: [ElementPlus, i18nPlugin()],
}

function steps(): TaskFinalWorkflowStep[] {
  return [
    { key: 'expert_review', title: '专家审查', status: 'complete', detail: '1 review', blocking_count: 0 },
    { key: 'clarification', title: '澄清问题', status: 'complete', detail: '0 blockers', blocking_count: 0 },
    { key: 'final_summary', title: '最终摘要', status: 'ready', detail: 'Ready', blocking_count: 0 },
    { key: 'baseline', title: '基线冻结', status: 'blocked', detail: 'Waiting', blocking_count: 1 },
  ]
}

function checklist(): BaselineCheckItem[] {
  return [
    { key: 'evidence', label: 'Confirmed evidence exists', status: 'pass', blocking: false },
    { key: 'clarifications', label: 'Blocking clarifications resolved', status: 'block', blocking: true },
  ]
}

function review(overrides: Partial<HumanReview> = {}): HumanReview {
  return {
    id: 'review-1',
    workspace_id: 'ws-1',
    task_id: 'task-1',
    status: 'OPEN',
    outcome: null,
    derived_status: 'CLEAR',
    title: 'Expert final-state review',
    body: 'Check evidence and final state.',
    review_type: 'EXPERT_FINAL_REVIEW',
    priority: 'NORMAL',
    target_refs: [{ target_type: 'EVIDENCE', target_id: 'evidence-1', label: 'Manual confirmation' }],
    linked_clarification_ids: [],
    comments: [],
    ...overrides,
  }
}

function reviewTargets(): Record<ReviewTargetType, ReviewTarget[]> {
  return {
    SPEC: [{ target_type: 'SPEC', target_id: 'spec-1', label: 'Owner spec', status: 'ACTIVE' }],
    PLAN: [],
    AI_CHANGE: [],
    HUMAN_DELTA: [{ target_type: 'HUMAN_DELTA', target_id: 'delta-1', label: 'Human patch', status: 'READY' }],
    EVIDENCE: [{ target_type: 'EVIDENCE', target_id: 'evidence-1', label: 'Manual confirmation' }],
    DECISION: [],
    TASK_FILE: [],
  }
}

function buttonByText(wrapper: ReturnType<typeof mount>, text: string) {
  return wrapper.findAll('button').find((button) => button.text().includes(text))
}

describe('Task final workflow components', () => {
  it('renders the four-step workflow stepper', async () => {
    const wrapper = mount(FinalWorkflowStepper, {
      props: { steps: steps(), activeKey: 'expert_review' },
      global,
    })

    expect(wrapper.findAll('.step-item')).toHaveLength(4)
    expect(wrapper.text()).toContain('专家审查')
    expect(wrapper.text()).toContain('基线冻结')

    await wrapper.findAll('.step-item')[1].trigger('click')
    expect(wrapper.emitted('select')?.[0]).toEqual(['clarification'])
  })

  it('highlights blocking checklist items', () => {
    const wrapper = mount(WorkflowChecklist, {
      props: { items: checklist() },
      global,
    })

    expect(wrapper.find('.checklist-item.is-blocking').exists()).toBe(true)
    expect(wrapper.text()).toContain('阻塞澄清已解决')
  })

  it('renders review target chips without old status buttons', async () => {
    const wrapper = mount(ExpertReviewStep, {
      props: { reviews: [review()], reviewTargets: reviewTargets(), readonly: false, saving: false },
      global,
    })

    expect(wrapper.text()).toContain('Manual confirmation')
    expect(wrapper.text()).not.toContain('Start')
    expect(wrapper.text()).not.toContain('Need clarification')
    expect(wrapper.text()).not.toContain('Need evidence')
    expect(wrapper.text()).not.toContain('Reject')
    expect(wrapper.text()).not.toContain('Scope')
    expect(wrapper.text()).not.toContain('新建关联澄清')
  })

  it('hides review write actions in readonly mode', () => {
    const wrapper = mount(ExpertReviewStep, {
      props: { reviews: [review()], reviewTargets: reviewTargets(), readonly: true, saving: false },
      global,
    })

    expect(wrapper.text()).not.toContain('新建审查项')
    expect(wrapper.text()).not.toContain('编辑审查项')
    expect(wrapper.text()).not.toContain('新建关联澄清')
  })

  it('lets the target picker select review targets across groups', async () => {
    const wrapper = mount(ReviewTargetPicker, {
      props: { modelValue: [], targets: reviewTargets() },
      global,
    })

    expect(wrapper.text()).toContain('Owner spec')
    expect(wrapper.text()).not.toContain('Manual confirmation')
    await buttonByText(wrapper, 'Evidence')?.trigger('click')
    expect(wrapper.text()).toContain('Manual confirmation')
    await wrapper.find('.candidate-item').trigger('click')
    expect(wrapper.emitted('update:modelValue')?.[0][0]).toMatchObject([
      { target_type: 'EVIDENCE', target_id: 'evidence-1' },
    ])
  })

  it('renders clarification as a chat flow and sends composer messages', async () => {
    const wrapper = mount(ClarificationThreadStep, {
      props: {
        clarifications: [
          {
            id: 'clarification-1',
            workspace_id: 'ws-1',
            task_id: 'task-1',
            status: 'OPEN',
            blocking_level: 'BLOCKING',
            question: 'Clarify final state?',
            source_review_id: 'review-1',
            promote_candidate: false,
          },
        ],
        threads: {
          'clarification-1': [
            {
              id: 'message-1',
              workspace_id: 'ws-1',
              task_id: 'task-1',
              clarification_id: 'clarification-1',
              entry_type: 'QUESTION',
              body: 'Clarify final state?',
              is_answer: false,
            },
          ],
        },
        reviews: [review()],
        reviewTargets: reviewTargets(),
        readonly: false,
        canResolveClarification: true,
        saving: false,
      },
      global,
    })

    expect(wrapper.text()).toContain('Clarify final state?')
    expect(wrapper.text()).not.toContain('Reject answer')
    expect(wrapper.find('.intent-select').exists()).toBe(false)
    await buttonByText(wrapper, '追问')?.trigger('click')
    await wrapper.find('textarea').setValue('Follow-up details')
    await buttonByText(wrapper, '发送')?.trigger('click')
    expect(wrapper.emitted('addMessage')?.[0]).toEqual([
      'clarification-1',
      { body: 'Follow-up details', entry_type: 'FOLLOW_UP' },
    ])
  })

  it('renders clarification target context and emits preview selection', async () => {
    const wrapper = mount(ClarificationThreadStep, {
      props: {
        clarifications: [
          {
            id: 'clarification-1',
            workspace_id: 'ws-1',
            task_id: 'task-1',
            status: 'OPEN',
            blocking_level: 'BLOCKING',
            question: 'Clarify manual delta?',
            source_review_id: 'review-1',
            target_ref: {
              targets: [{ target_type: 'HUMAN_DELTA', target_id: 'delta-1', label: 'Human patch' }],
            },
            promote_candidate: false,
          },
        ],
        threads: {},
        reviews: [review()],
        reviewTargets: reviewTargets(),
        readonly: true,
        canResolveClarification: true,
        saving: false,
      },
      global,
    })

    expect(wrapper.text()).toContain('待澄清内容')
    expect(wrapper.text()).toContain('Human patch')
    await buttonByText(wrapper, '查看内容')?.trigger('click')
    expect(wrapper.emitted('previewTarget')?.[0][0]).toMatchObject({
      target_type: 'HUMAN_DELTA',
      target_id: 'delta-1',
    })
  })

  it('shows expert resolution actions outside the composer', async () => {
    const wrapper = mount(ClarificationThreadStep, {
      props: {
        clarifications: [
          {
            id: 'clarification-1',
            workspace_id: 'ws-1',
            task_id: 'task-1',
            status: 'ANSWERED',
            blocking_level: 'BLOCKING',
            question: 'Clarify final state?',
            source_review_id: 'review-1',
            promote_candidate: false,
          },
        ],
        threads: {},
        reviews: [review()],
        reviewTargets: reviewTargets(),
        readonly: false,
        canResolveClarification: true,
        saving: false,
      },
      global,
    })

    expect(wrapper.text()).toContain('确认解决')
    await buttonByText(wrapper, '确认解决')?.trigger('click')
    expect(wrapper.emitted('addMessage')?.[0]).toEqual([
      'clarification-1',
      { body: '专家确认该澄清已解决。', entry_type: 'CONFIRM_RESOLUTION' },
    ])
  })

  it('renders review target preview drawer with localized labels and file diffs', () => {
    const preview: ReviewTargetPreviewResponse = {
      target: { target_type: 'HUMAN_DELTA', target_id: 'delta-1', label: 'Human patch' },
      title: 'Human patch',
      status: 'READY',
      subtitle: '1 file',
      source_ref: { source_kind: 'human_delta' },
      metadata: [{ key: 'changed_files', label: 'Changed files', value: '1' }],
      blocks: [
        {
          key: 'summary',
          title: 'Summary',
          kind: 'text',
          content: 'Owner adjusted checkout validation.',
          items: [],
          file_diffs: [],
          delta_regions: [],
        },
        {
          key: 'file_diffs',
          title: 'Changed files',
          kind: 'file_diffs',
          items: [],
          file_diffs: [
            {
              file_path: 'src/checkout.ts',
              change_type: 'modified',
              insertions: 2,
              deletions: 1,
              hunks: [],
              comparison_type: 'human_only',
            },
          ],
          delta_regions: [],
          diff_text: 'diff --git a/src/checkout.ts b/src/checkout.ts',
        },
      ],
    }

    const wrapper = mount(ReviewTargetPreviewDrawer, {
      props: {
        visible: true,
        target: { target_type: 'HUMAN_DELTA', target_id: 'delta-1', label: 'Human patch' },
        preview,
        loading: false,
        error: null,
      },
      global: {
        plugins: [ElementPlus, i18nPlugin()],
        stubs: {
          ElDrawer: { template: '<section class="drawer-stub"><slot /></section>' },
          DeltaFileNav: { template: '<div class="file-nav-stub">src/checkout.ts</div>' },
          HumanPatchCompare: { template: '<div class="patch-compare-stub">patch compare</div>' },
        },
      },
    })

    expect(wrapper.text()).toContain('Human patch')
    expect(wrapper.text()).toContain('变更文件')
    expect(wrapper.text()).toContain('Owner adjusted checkout validation.')
    expect(wrapper.text()).toContain('src/checkout.ts')
  })

  it('shows only the baseline snapshot once the task is frozen', () => {
    const wrapper = mount(BaselineStep, {
      props: {
        baseline: {
          id: 'baseline-1',
          workspace_id: 'ws-1',
          task_id: 'task-1',
          version: 1,
          snapshot: { counts: { reviews: 1, clarifications: 0, evidence: 1, decisions: 0 } },
          is_rollback: false,
        },
        checklist: checklist(),
        readonly: true,
        saving: false,
      },
      global,
    })

    expect(wrapper.text()).toContain('Baseline v1')
    expect(wrapper.text()).not.toContain('Freeze baseline')
    expect(wrapper.text()).not.toContain('冻结 baseline')
  })
})
