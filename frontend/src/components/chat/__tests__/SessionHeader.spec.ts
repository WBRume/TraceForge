import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia } from 'pinia'
import SessionHeader from '@/components/chat/sections/SessionHeader.vue'
import zh from '@/locales/zh.json'
import en from '@/locales/en.json'
import { TASK_STATUSES } from '@/utils/taskStatus'

vi.mock('@/components/DeleteActionButton.vue', () => ({
  default: {
    name: 'DeleteActionButton',
    template: '<button class="delete-btn" />',
  },
}))

vi.mock('@/components/chat/ChatMoreActionsMenu.vue', () => ({
  default: {
    name: 'ChatMoreActionsMenu',
    template: '<div class="more-actions" />',
  },
}))

const i18n = createI18n({
  legacy: false,
  locale: 'zh',
  fallbackLocale: 'en',
  messages: { zh, en },
})

const createMockVm = (overrides: Record<string, any> = {}): any => ({
  route: { params: { wsId: 'w1', taskId: 't1' } },
  currentTask: { id: 't1', name: '你是什么大模型', status: 'RUNNING' },
  isLocalTask: false,
  localResourceStatus: 'online',
  localResourceLabel: '本地资源在线',
  localResourceBlocked: false,
  isStartActionVisible: false,
  canClickStartAction: false,
  isTaskProvisioning: false,
  taskRuntimeSkillCount: 0,
  isDiagnosisTask: false,
  isSpecPanelOpen: false,
  canInitializeAction: false,
  isTerminalStatus: false,
  canManageTaskStatus: true,
  canCloseTask: true,
  hidePatchWorkflows: false,
  chatWorkbenchMode: 'platform',
  showSpecEntryButton: false,
  canDeleteTask: true,
  canExportTask: true,
  canShareTaskSession: true,
  contextWindowDrawerOpen: false,
  ...overrides,
})

describe('collaboration status badges', () => {
  for (const locale of ['zh', 'en'] as const) {
    it.each(TASK_STATUSES)(`${locale}: localizes %s without exposing the enum`, status => {
      const messages = { zh, en }
      const wrapper = mount(SessionHeader, {
        props: { vm: createMockVm({ currentTask: { id: 't1', name: '状态验证', status } }) },
        global: { plugins: [createPinia(), createI18n({ legacy: false, locale, messages })] },
      })
      const badge = wrapper.get('[data-testid="session-task-status"]')
      expect(badge.text()).toBe('')
      expect(badge.attributes('title')).toBe(messages[locale].chat.status[status])
      expect(badge.attributes('aria-label')).toBe(messages[locale].chat.status[status])
      expect(badge.attributes('data-status')).toBe(status)
      expect(badge.find('svg').exists()).toBe(true)
      wrapper.unmount()
    })
  }
})

describe('SessionHeader scroll auto-hide', () => {
  it('marks the toolbar collapsed and inert without adding a toggle button', () => {
    const wrapper = mount(SessionHeader, {
      props: { vm: createMockVm(), collapsed: true },
      global: { plugins: [i18n, createPinia()] },
    })

    const header = wrapper.get('[data-testid="chat-header"]')
    expect(header.classes()).toContain('glass-panel')
    expect(header.classes()).toContain('is-collapsed')
    expect(header.attributes('inert')).toBeDefined()
    expect(header.attributes('aria-hidden')).toBe('true')
    expect(wrapper.findAll('[data-testid="chat-header-toggle"]')).toHaveLength(0)

    wrapper.unmount()
  })

  it('keeps the toolbar interactive when expanded', () => {
    const wrapper = mount(SessionHeader, {
      props: { vm: createMockVm(), collapsed: false },
      global: { plugins: [i18n, createPinia()] },
    })

    const header = wrapper.get('[data-testid="chat-header"]')
    expect(header.classes()).not.toContain('is-collapsed')
    expect(header.attributes('inert')).toBeUndefined()
    expect(header.attributes('aria-hidden')).toBeUndefined()

    wrapper.unmount()
  })
})

describe('SessionHeader local resource badge', () => {
  it('has no local collaboration or patch entry for diagnosis tasks', () => {
    const wrapper = mount(SessionHeader, {
      props: { vm: createMockVm({ currentTask: { id: 'diagnosis', name: '定位任务', task_type: 'DIAGNOSIS', status: 'RUNNING' }, isDiagnosisTask: true, hidePatchWorkflows: true, collaboration: { supported: { value: false } } }) },
      global: { plugins: [i18n, createPinia()] },
    })
    expect(wrapper.find('.collaboration-entry').exists()).toBe(false)
    expect(wrapper.findAll('button').some(button => ['代码', '生成变更与应用补丁', '本地协同'].includes(button.text()))).toBe(false)
    wrapper.unmount()
  })
  it('offers manual pinning without a task cancellation action for static or interrupted tasks', async () => {
    const wrapper = mount(SessionHeader, {
      props: { vm: createMockVm({ currentTask: { id: 't1', name: '静态任务', status: 'FAILED', business_state: 'TASK_IN_PROGRESS' } }) },
      global: { plugins: [i18n, createPinia()] },
    })
    expect(wrapper.findAll('button').some(button => button.text().includes('钉在窗口中'))).toBe(true)
    expect(wrapper.findAll('button').some(button => button.text() === '取消任务')).toBe(false)
    await wrapper.setProps({ vm: createMockVm({ currentTask: { id: 't1', name: '静态任务', status: 'INTERRUPTED', business_state: 'TASK_IN_PROGRESS' } }) })
    expect(wrapper.get('[data-testid="session-task-status"]').attributes('aria-label')).toBe('已中断')
    expect(wrapper.findAll('button').some(button => button.text() === '取消任务')).toBe(false)
    wrapper.unmount()
  })
  it('offers requirement linking only for completed diagnosis tasks with permission', async () => {
    const wrapper = mount(SessionHeader, {
      props: { vm: createMockVm({ currentTask: { id: 't1', name: '定位任务', status: 'COMPLETED' }, isDiagnosisTask: true }) },
      global: { plugins: [i18n, createPinia()] },
    })
    const entry = wrapper.findAll('button').find(button => button.text() === '关联需求')!
    await entry.trigger('click')
    expect(wrapper.emitted('link-requirement')).toHaveLength(1)
    await wrapper.setProps({ vm: createMockVm({ currentTask: { id: 't1', name: '定位任务', status: 'RUNNING' }, isDiagnosisTask: true }) })
    expect(wrapper.text()).not.toContain('关联需求')
    await wrapper.setProps({ vm: createMockVm({ currentTask: { id: 't1', name: '定位任务', status: 'COMPLETED' }, isDiagnosisTask: false }) })
    expect(wrapper.text()).not.toContain('关联需求')
    await wrapper.setProps({ vm: createMockVm({ currentTask: { id: 't1', name: '定位任务', status: 'COMPLETED' }, isDiagnosisTask: true, canManageTaskStatus: false }) })
    expect(wrapper.text()).not.toContain('关联需求')
    wrapper.unmount()
  })

  it('does not render local resource badge for cloud/server tasks', () => {
    const wrapper = mount(SessionHeader, {
      props: { vm: createMockVm({ isLocalTask: false }) },
      global: { plugins: [i18n, createPinia()] },
    })
    expect(wrapper.find('.local-resource-badge').exists()).toBe(false)
  })

  it('renders styled local resource badge with status dot when task is local', () => {
    const wrapper = mount(SessionHeader, {
      props: {
        vm: createMockVm({
          isLocalTask: true,
          localResourceStatus: 'online',
          localResourceLabel: '本地资源在线',
        }),
      },
      global: { plugins: [i18n, createPinia()] },
    })

    const badge = wrapper.find('.local-resource-badge')
    expect(badge.exists()).toBe(true)
    expect(badge.classes()).toContain('is-online')
    expect(badge.text()).toContain('本地资源在线')
    expect(badge.find('.resource-status-dot').exists()).toBe(true)
  })

  it('reflects offline state in class names', () => {
    const wrapper = mount(SessionHeader, {
      props: {
        vm: createMockVm({
          isLocalTask: true,
          localResourceStatus: 'offline',
          localResourceLabel: '本地资源离线',
          localResourceBlocked: true,
          canManageTaskStatus: false,
        }),
      },
      global: { plugins: [i18n, createPinia()] },
    })

    const badge = wrapper.find('.local-resource-badge')
    expect(badge.exists()).toBe(true)
    expect(badge.classes()).toContain('is-offline')
    expect(badge.text()).toContain('本地资源离线')
    expect(badge.attributes('title')).toBe('恢复在线后才能发送、撤回或操作本地资源')
    expect(wrapper.get('button.danger').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('button.success').attributes('disabled')).toBeUndefined()
  })
})

describe('SessionHeader start task action button', () => {
  it('does not render start task button when isStartActionVisible is false', () => {
    const wrapper = mount(SessionHeader, {
      props: { vm: createMockVm({ isStartActionVisible: false }) },
      global: { plugins: [i18n, createPinia()] },
    })
    expect(wrapper.find('[data-testid="start-task-btn"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('renders styled start task pill button with localized label and play icon when visible', () => {
    const handleStartClick = vi.fn()
    const wrapper = mount(SessionHeader, {
      props: {
        vm: createMockVm({
          isStartActionVisible: true,
          canClickStartAction: true,
          handleStartClick,
        }),
      },
      global: { plugins: [i18n, createPinia()] },
    })

    const btn = wrapper.get('[data-testid="start-task-btn"]')
    expect(btn.classes()).toContain('start-task-btn')
    expect(btn.classes()).toContain('start-btn')
    expect(btn.classes()).toContain('is-ready')
    expect(btn.text()).toContain('启动任务')
    expect(btn.find('.btn-play-icon').exists()).toBe(true)
    expect(btn.attributes('disabled')).toBeUndefined()

    btn.trigger('click')
    expect(handleStartClick).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('reflects disabled provisioning state with hint title', () => {
    const wrapper = mount(SessionHeader, {
      props: {
        vm: createMockVm({
          isStartActionVisible: true,
          canClickStartAction: false,
          isTaskProvisioning: true,
        }),
      },
      global: { plugins: [i18n, createPinia()] },
    })

    const btn = wrapper.get('[data-testid="start-task-btn"]')
    expect(btn.classes()).toContain('is-disabled')
    expect(btn.classes()).not.toContain('is-ready')
    expect(btn.attributes('disabled')).toBeDefined()
    expect(btn.attributes('title')).toBe(zh.chat.task_provisioning_hint)
    wrapper.unmount()
  })

  it('localizes start task button label in English correctly', () => {
    const englishI18n = createI18n({
      legacy: false,
      locale: 'en',
      fallbackLocale: 'en',
      messages: { zh, en },
    })
    const wrapper = mount(SessionHeader, {
      props: {
        vm: createMockVm({
          isStartActionVisible: true,
          canClickStartAction: true,
        }),
      },
      global: { plugins: [englishI18n, createPinia()] },
    })

    const btn = wrapper.get('[data-testid="start-task-btn"]')
    expect(btn.text()).toContain('Start Task')
    wrapper.unmount()
  })
})
