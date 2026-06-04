import { describe, expect, it, vi } from 'vitest'
import { mount, RouterLinkStub } from '@vue/test-utils'
import { readonly, shallowRef } from 'vue'
import { createI18n } from 'vue-i18n'
import ElementPlus from 'element-plus'
import zh from '@/locales/zh.json'
import en from '@/locales/en.json'

function i18nPlugin(locale = 'zh') {
  return createI18n({
    legacy: false,
    locale,
    fallbackLocale: 'en',
    messages: { zh, en },
  })
}

describe('TaskFinalWorkflowEntryPanel', () => {
  it('renders a lightweight entry instead of workflow operations', async () => {
    vi.resetModules()
    const load = vi.fn()
    vi.doMock('@/composables/useTaskFinalWorkflow', () => ({
      useTaskFinalWorkflow: () => ({
        workflow: shallowRef({
          task: {
            id: 'task-1',
            workspace_id: 'ws-1',
            name: 'Final workflow task',
            status: 'DONE',
            requirement_count: 1,
            spec_count: 0,
            plan_count: 0,
            ai_run_count: 0,
            human_review_count: 2,
            human_delta_count: 0,
            evidence_count: 1,
            decision_count: 0,
            clarification_count: 1,
            coverage_status: 'verified',
            baseline_version: 0,
            updated_at: '2026-05-30T10:00:00Z',
          },
          steps: [
            { key: 'expert_review', title: '专家审查', status: 'complete', blocking_count: 0 },
            { key: 'clarification', title: '澄清问题', status: 'blocked', blocking_count: 1 },
            { key: 'final_summary', title: '最终摘要', status: 'blocked', blocking_count: 1 },
            { key: 'baseline', title: '基线冻结', status: 'blocked', blocking_count: 1 },
          ],
          reviews: [],
          review_targets: {},
          clarifications: [],
          clarification_threads: {},
          final_summary: null,
          baseline: null,
          checklist: [{ key: 'clarifications', label: 'Blocking', status: 'block', blocking: true }],
          available_actions: [],
          readonly: false,
          can_write_final_workflow: true,
          can_resolve_clarification: true,
        }),
        loading: readonly(shallowRef(false)),
        error: readonly(shallowRef(null)),
        lockMessage: readonly(shallowRef(null)),
        load,
      }),
    }))

    const { default: TaskFinalWorkflowEntryPanel } = await import('../TaskFinalWorkflowEntryPanel.vue')
    const wrapper = mount(TaskFinalWorkflowEntryPanel, {
      props: { workspaceId: 'ws-1', taskId: 'task-1' },
      global: {
        plugins: [ElementPlus, i18nPlugin()],
        stubs: { RouterLink: RouterLinkStub },
      },
    })

    expect(load).toHaveBeenCalledWith('ws-1', 'task-1')
    expect(wrapper.text()).toContain('打开最终状态流程')
    expect(wrapper.text()).toContain('阻塞项')
    expect(wrapper.text()).not.toContain('新建审查项')
    expect(wrapper.findComponent(RouterLinkStub).props('to')).toMatchObject({
      name: 'workspaceAssetsTaskFinalWorkflow',
    })
  })
})
