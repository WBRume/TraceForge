import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import VerificationActions from '@/components/chat/sections/VerificationActions.vue'
import zh from '@/locales/zh.json'
import en from '@/locales/en.json'

const i18n = createI18n({
  legacy: false,
  locale: 'zh',
  fallbackLocale: 'en',
  messages: { zh, en },
})

const createMockVm = (overrides: Record<string, any> = {}) => ({
  messages: [{ id: 'm1', content: 'hello', role: 'user' }],
  isChatLocked: false,
  isDiagnosisTask: false,
  engineRunning: false,
  hidePatchWorkflows: false,
  statusCards: [],
  resultsSummary: {
    visible: true,
    totalDurationMs: 96500,
    totalCostUsd: 0.9329,
    history: [{ id: 'h1', duration_ms: 96500, cost_usd: 0.9329, success: true, result: 'done', created_at: '', timestamp: '12:00:00' }],
    expanded: false,
  },
  sendVerification: vi.fn(),
  generateDiagnosisSummary: vi.fn(),
  diagnosisChatBusy: false,
  diagnosisSummarizing: false,
  isDiagnosisAdopted: false,
  diagnosisSummarizingLabel: '总结案例',
  ...overrides,
})

describe('VerificationActions & RunSummaryCard Integration', () => {
  it('renders architecture buttons on the left and status distribution summary on the right', () => {
    const vm = createMockVm()
    const wrapper = mount(VerificationActions, {
      props: { vm: vm as any },
      global: { plugins: [i18n] },
    })

    expect(wrapper.find('.actions-left').exists()).toBe(true)
    expect(wrapper.text()).toContain('架构图')
    expect(wrapper.text()).toContain('UI')
    expect(wrapper.text()).toContain('API')
    expect(wrapper.text()).toContain('E2E')

    expect(wrapper.find('.actions-right').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('任务状态分布')
    expect(wrapper.text()).toContain('96.5s')
    expect(wrapper.text()).toContain('$0.9329')

    // 确保没有下拉展开按钮与分阶段明细面板
    expect(wrapper.find('.run-summary-toggle').exists()).toBe(false)
    expect(wrapper.find('.card-body').exists()).toBe(false)
  })

  it('renders status card information when active status cards exist', () => {
    const vm = createMockVm({
      statusCards: [
        {
          id: 'sc-1',
          type: 'status',
          status: 'RUNNING',
          message: '代码生成中',
          model: 'claude-3-5-sonnet',
          provider: 'anthropic',
          phase: 'codegen',
          created_at: new Date().toISOString(),
        },
      ],
      resultsSummary: {
        visible: true,
        totalDurationMs: 12400,
        totalCostUsd: 0.052,
        history: [],
        expanded: false,
      },
    })

    const wrapper = mount(VerificationActions, {
      props: { vm: vm as any },
      global: { plugins: [i18n] },
    })

    expect(wrapper.find('.actions-right').exists()).toBe(true)
    expect(wrapper.text()).toContain('代码生成中')
    expect(wrapper.text()).toContain('claude-3-5-sonnet')
    expect(wrapper.text()).toContain('12.4s')
    expect(wrapper.text()).toContain('$0.0520')
  })

  it('shows right status summary even when engine is running (left action buttons hidden)', () => {
    const vm = createMockVm({
      engineRunning: true,
      statusCards: [],
      resultsSummary: {
        visible: true,
        totalDurationMs: 5000,
        totalCostUsd: 0.01,
        history: [],
        expanded: false,
      },
    })

    const wrapper = mount(VerificationActions, {
      props: { vm: vm as any },
      global: { plugins: [i18n] },
    })

    // 左侧按钮在 engineRunning 研发态任务下不展示
    expect(wrapper.find('.actions-left').exists()).toBe(false)
    // 右侧状态摘要依然展示在红框右侧
    expect(wrapper.find('.actions-right').exists()).toBe(true)
    expect(wrapper.text()).toContain('5.0s')
  })

  it('renders nothing if there are neither actions nor status summaries', () => {
    const vm = createMockVm({
      messages: [],
      statusCards: [],
      resultsSummary: {
        visible: false,
        totalDurationMs: 0,
        totalCostUsd: 0,
        history: [],
        expanded: false,
      },
    })

    const wrapper = mount(VerificationActions, {
      props: { vm: vm as any },
      global: { plugins: [i18n] },
    })

    expect(wrapper.find('.verification-actions').exists()).toBe(false)
  })
})
