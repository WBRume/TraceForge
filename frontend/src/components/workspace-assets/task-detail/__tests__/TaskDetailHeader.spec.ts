import { describe, expect, it } from 'vitest'
import { mount, RouterLinkStub } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import zh from '@/locales/zh.json'
import en from '@/locales/en.json'
import type { TaskDetailSummaryResponse } from '@/types/workspaceAssets'
import TaskDetailHeader from '../TaskDetailHeader.vue'

function createTestI18n() {
  return createI18n({
    legacy: false,
    locale: 'zh',
    fallbackLocale: 'en',
    messages: { zh, en },
  })
}

describe('TaskDetailHeader', () => {
  const baseDetail: TaskDetailSummaryResponse = {
    task: {
      id: 'task-123',
      workspace_id: 'ws-456',
      name: '测试任务',
      description: null,
      status: 'IN_PROGRESS',
      current_phase: 'AI_SOLUTION',
      requirement_count: 0,
      spec_count: 0,
      plan_count: 0,
      ai_run_count: 0,
      human_review_count: 0,
      human_delta_count: 0,
      evidence_count: 0,
      decision_count: 0,
      clarification_count: 0,
      coverage_status: 'waiting_evidence',
      creator_display_name: 'xfc',
    },
    requirement_links: [],
    process_summary: {
      spec_status: 'not_available',
      plan_status: 'not_available',
      ai_run_status: 'not_available',
      human_review_status: 'not_available',
      human_delta_status: 'not_available',
      evidence_status: 'available',
      coverage_status: 'waiting_evidence',
      risk_status: 'not_available',
    },
    connection_status: [],
  }

  it('当任务没有提示词时，不显示描述段落，也不显示默认说明文案', () => {
    const wrapper = mount(TaskDetailHeader, {
      props: {
        detail: {
          ...baseDetail,
          task: {
            ...baseDetail.task,
            description: null,
          },
        },
        workspaceId: 'ws-456',
        taskId: 'task-123',
      },
      global: {
        plugins: [createTestI18n()],
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })

    expect(wrapper.find('.task-desc').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Task Detail 是 Spec')
  })

  it('当任务提示词全为空白字符时，不显示描述段落', () => {
    const wrapper = mount(TaskDetailHeader, {
      props: {
        detail: {
          ...baseDetail,
          task: {
            ...baseDetail.task,
            description: '   ',
          },
        },
        workspaceId: 'ws-456',
        taskId: 'task-123',
      },
      global: {
        plugins: [createTestI18n()],
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })

    expect(wrapper.find('.task-desc').exists()).toBe(false)
  })

  it('当任务有提示词时，显示提示词内容', () => {
    const promptText = '请实现用户订单导出为 Excel 功能并支持多选'
    const wrapper = mount(TaskDetailHeader, {
      props: {
        detail: {
          ...baseDetail,
          task: {
            ...baseDetail.task,
            description: promptText,
          },
        },
        workspaceId: 'ws-456',
        taskId: 'task-123',
      },
      global: {
        plugins: [createTestI18n()],
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })

    const desc = wrapper.find('.task-desc')
    expect(desc.exists()).toBe(true)
    expect(desc.text()).toBe(promptText)
    expect(wrapper.text()).not.toContain('Task Detail 是 Spec')
  })
})
