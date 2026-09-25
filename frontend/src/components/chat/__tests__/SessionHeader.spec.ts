import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import SessionHeader from '@/components/chat/sections/SessionHeader.vue'
import zh from '@/locales/zh.json'
import en from '@/locales/en.json'

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
  currentTask: { id: 't1', name: '你是什么大模型', status: 'CODING' },
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
  hidePatchWorkflows: false,
  chatWorkbenchMode: 'platform',
  showSpecEntryButton: false,
  canDeleteTask: true,
  canExportTask: true,
  canShareTaskSession: true,
  contextWindowDrawerOpen: false,
  ...overrides,
})

describe('SessionHeader local resource badge', () => {
  it('does not render local resource badge for cloud/server tasks', () => {
    const wrapper = mount(SessionHeader, {
      props: { vm: createMockVm({ isLocalTask: false }) },
      global: { plugins: [i18n] },
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
      global: { plugins: [i18n] },
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
        }),
      },
      global: { plugins: [i18n] },
    })

    const badge = wrapper.find('.local-resource-badge')
    expect(badge.exists()).toBe(true)
    expect(badge.classes()).toContain('is-offline')
    expect(badge.text()).toContain('本地资源离线')
    expect(badge.attributes('title')).toBe('恢复在线后才能发送、撤回或操作本地资源')
  })
})
