import { describe, expect, it } from 'vitest'
import { mount, RouterLinkStub } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import ElementPlus from 'element-plus'
import RequirementDetailContent from '../RequirementDetailContent.vue'
import RequirementDetailPanel from '../RequirementDetailPanel.vue'
import RequirementImportDialog from '../RequirementImportDialog.vue'
import RequirementRepositoryPanel from '../RequirementRepositoryPanel.vue'
import RequirementSpecificationBlock from '../RequirementSpecificationBlock.vue'
import RequirementTableWorkbench from '../RequirementTableWorkbench.vue'
import en from '@/locales/en.json'
import zh from '@/locales/zh.json'
import type { RequirementDetail, RequirementSummary, TaskSummary } from '@/types/workspaceAssets'

function i18nPlugin(locale = 'en') {
  return createI18n({
    legacy: false,
    locale,
    messages: { en, zh },
  })
}

function requirement(overrides: Partial<RequirementSummary> = {}): RequirementSummary {
  return {
    id: 'req-1',
    workspace_id: 'ws-1',
    title: 'Validate payment state',
    body: 'Checkout requires a valid payment state.',
    status: 'READY',
    acceptance_criteria: ['Reject invalid payment state'],
    priority: 'P1',
    parent_requirement_id: null,
    parent_title: null,
    child_count: 0,
    children: [],
    can_link_task: true,
    import_batch_id: null,
    source_kind: 'document',
    source_uri: null,
    source_ref: 'PRD-1',
    source_metadata: null,
    coverage_summary: {
      coverage_status: 'waiting_evidence',
      coverage_reason: 'Derived from real Task process assets.',
      related_task_count: 1,
      evidence_count: 0,
      human_review_count: 0,
      human_delta_count: 0,
    },
    change_history_count: 1,
    related_task_count: 1,
    linked_tasks: [],
    created_at: null,
    updated_at: null,
    ...overrides,
  }
}

function task(): TaskSummary {
  return {
    id: 'task-1',
    workspace_id: 'ws-1',
    name: 'Implement checkout validation',
    description: null,
    status: 'PLANNING',
    current_phase: 'spec',
    requirement_count: 1,
    spec_count: 0,
    plan_count: 0,
    ai_run_count: 0,
    human_review_count: 0,
    human_delta_count: 0,
    evidence_count: 0,
    decision_count: 0,
    clarification_count: 0,
    coverage_status: 'waiting_evidence',
    created_at: null,
    updated_at: null,
  }
}

describe('Requirement panels', () => {
  it('renders a real requirement repository without fake records', async () => {
    const wrapper = mount(RequirementRepositoryPanel, {
      props: {
        items: [requirement()],
        selectedId: 'req-1',
      },
      global: {
        plugins: [i18nPlugin()],
      },
    })

    expect(wrapper.text()).toContain('Validate payment state')
    expect(wrapper.text()).toContain('Coverage is read-only')
    expect(wrapper.text()).toContain('New Requirement')
    expect(wrapper.text()).not.toContain('Import Requirements')
    await wrapper.get('button.primary-action').trigger('click')
    expect(wrapper.emitted('create')).toHaveLength(1)
  })

  it('renders the table workbench as the main Requirements entry', async () => {
    const wrapper = mount(RequirementTableWorkbench, {
      props: {
        items: [
          requirement({
            id: 'req-parent',
            title: 'Checkout parent',
            child_count: 1,
            children: [
              requirement({
                id: 'req-child',
                title: 'Payment validation child',
                parent_requirement_id: 'req-parent',
                parent_title: 'Checkout parent',
              }),
            ],
            can_link_task: false,
          }),
        ],
        total: 1,
        page: 1,
        pageSize: 20,
        scope: 'tree',
      },
      global: {
        plugins: [i18nPlugin('zh'), ElementPlus],
      },
    })

    expect(wrapper.text()).toContain('需求资产表格')
    expect(wrapper.html()).toContain('el-table')
    expect(wrapper.text()).toContain('新建需求')
    await wrapper.get('.table-toolbar .el-button--primary').trigger('click')
    expect(wrapper.emitted('create')).toHaveLength(1)
  })

  it('shows a single Chinese create entry with multiple creation methods inside the dialog', async () => {
    const repository = mount(RequirementRepositoryPanel, {
      props: {
        items: [],
        selectedId: null,
      },
      global: {
        plugins: [i18nPlugin('zh')],
      },
    })

    expect(repository.text()).toContain('新建需求')
    expect(repository.findAll('button.primary-action')).toHaveLength(1)

    const dialog = mount(RequirementImportDialog, {
      props: {
        open: true,
        mode: 'create',
        batch: null,
      },
      global: {
        plugins: [i18nPlugin('zh')],
        stubs: {
          Teleport: true,
        },
      },
    })

    expect(dialog.text()).toContain('手工创建')
    expect(dialog.text()).toContain('导入单文件')
    expect(dialog.text()).toContain('来源链接')
    expect(dialog.findAll('.method-card')).toHaveLength(3)
    expect(dialog.text()).not.toContain('暂无 Preview')
    await dialog.findAll('.method-card')[1].trigger('click')
    expect(dialog.text()).toContain('直接导入为单条需求')
    expect(dialog.text()).toContain('生成 AI Preview')
    expect(dialog.text()).not.toContain('来源链接')
    expect(dialog.text()).not.toContain('来源引用')
    const fileInput = dialog.find('input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', {
      value: [new File(['Requirement text'], 'requirement.md', { type: 'text/markdown' })],
      configurable: true,
    })
    await fileInput.trigger('change')
    expect(dialog.findAll('.secondary-action').some((button) => button.attributes('disabled') === undefined)).toBe(true)
    await dialog.findAll('.ghost-action')[0].trigger('click')
    await dialog.findAll('.method-card')[2].trigger('click')
    expect(dialog.text()).toContain('记录来源链接')
    expect(dialog.text()).toContain('来源链接')
    expect(dialog.text()).toContain('来源引用')
  })

  it('renders editable AI preview items with task prompts before confirmation', () => {
    const wrapper = mount(RequirementImportDialog, {
      props: {
        open: true,
        mode: 'create',
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
              priority: 'P1',
              task_prompt: 'Implement payment state validation.',
              order_index: 0,
              status: 'PENDING',
            },
          ],
        },
      },
      global: {
        plugins: [i18nPlugin()],
        stubs: {
          Teleport: true,
        },
      },
    })

    expect(wrapper.text()).toContain('Preview Items')
    expect((
      wrapper.find(
        'textarea[placeholder="Prompt for a future Task; this does not create a Task automatically"]',
      ).element as HTMLTextAreaElement
    ).value).toBe(
      'Implement payment state validation.',
    )
    expect(wrapper.text()).toContain('Do not apply Preview')
  })

  it('shows background AI preview progress before preview items are available', () => {
    const wrapper = mount(RequirementImportDialog, {
      props: {
        open: true,
        mode: 'create',
        batch: null,
        previewJob: {
          job_id: 'job-1',
          workspace_id: 'ws-1',
          status: 'RUNNING',
          progress: 28,
          message: 'Running Claude Code CLI requirement preview',
          batch: null,
        },
      },
      global: {
        plugins: [i18nPlugin('zh')],
        stubs: {
          Teleport: true,
        },
      },
    })

    expect(wrapper.text()).toContain('AI Preview 生成中')
    expect(wrapper.text()).toContain('28%')
    expect(wrapper.text()).toContain('Running Claude Code CLI requirement preview')
    expect(wrapper.text()).not.toContain('Preview 项')
  })

  it('shows linked task, derived coverage and audit history without AI process details', () => {
    const detail: RequirementDetail = {
      requirement: requirement({
        linked_tasks: [
          {
            link_id: 'link-1',
            task_id: 'task-1',
            task_name: 'Implement checkout validation',
            task_status: 'PLANNING',
            current_phase: 'spec',
            relation_type: 'COVERS',
            coverage_status: 'waiting_evidence',
            created_at: null,
          },
        ],
      }),
      linked_tasks: [
        {
          link_id: 'link-1',
          task_id: 'task-1',
          task_name: 'Implement checkout validation',
          task_status: 'PLANNING',
          current_phase: 'spec',
          relation_type: 'COVERS',
          coverage_status: 'waiting_evidence',
          created_at: null,
        },
      ],
      children: [],
      audit_logs: [
        {
          id: 'audit-1',
          workspace_id: 'ws-1',
          requirement_id: 'req-1',
          action: 'CREATED',
          reason: 'Initial capture',
          created_at: '2026-05-08T00:00:00Z',
        },
      ],
    }
    const wrapper = mount(RequirementDetailPanel, {
      props: {
        workspaceId: 'ws-1',
        requirement: detail.requirement,
        detail,
        tasks: [task()],
      },
      global: {
        plugins: [i18nPlugin()],
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })

    expect(wrapper.text()).toContain('Related Tasks')
    expect(wrapper.text()).toContain('Implement checkout validation')
    expect(wrapper.text()).toContain('waiting_evidence')
    expect(wrapper.text()).toContain('CREATED')
    expect(wrapper.text()).not.toContain('AI output summary')
    expect(wrapper.text()).not.toContain('Coverage editor')
  })

  it('formats requirement specification content into headings and lists', () => {
    const wrapper = mount(RequirementSpecificationBlock, {
      props: {
        body: '# Scope\n\n- Validate payment state\n- Reject invalid transitions\n\nPlain follow-up note.',
      },
      global: {
        plugins: [i18nPlugin(), ElementPlus],
      },
    })

    expect(wrapper.find('h2').text()).toBe('Scope')
    expect(wrapper.findAll('li')).toHaveLength(2)
    expect(wrapper.text()).toContain('Plain follow-up note.')
  })

  it('uses child requirements as the specification view for split parents to avoid duplicate content', () => {
    const child = requirement({
      id: 'req-child',
      title: 'Payment validation child',
      body: 'Validate payment state without repeating the full parent source.',
      parent_requirement_id: 'req-parent',
      parent_title: 'Checkout parent',
    })
    const detail: RequirementDetail = {
      requirement: requirement({
        id: 'req-parent',
        title: 'Checkout parent',
        body: 'Parent source body that repeats child requirement content.',
        child_count: 1,
        children: [child],
        can_link_task: false,
      }),
      linked_tasks: [],
      children: [child],
      audit_logs: [],
    }
    const wrapper = mount(RequirementDetailContent, {
      props: {
        workspaceId: 'ws-1',
        requirement: detail.requirement,
        detail,
        tasks: [],
      },
      global: {
        plugins: [i18nPlugin(), ElementPlus],
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })

    expect(wrapper.text()).toContain('Payment validation child')
    expect(wrapper.text()).toContain('Validate payment state without repeating')
    expect(wrapper.text()).not.toContain('Parent source body that repeats child requirement content.')
  })
})
