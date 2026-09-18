import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import TaskSessionShareDialog from '@/components/chat/TaskSessionShareDialog.vue'
import zh from '@/locales/zh.json'
import en from '@/locales/en.json'

const i18n = createI18n({
  legacy: false,
  locale: 'zh',
  fallbackLocale: 'en',
  messages: { zh, en },
})

const baseShare = {
  id: 'share-1',
  mode: 'READ',
  instruction_text: null,
  session_generation: 1,
  expires_at: '2026-09-25T00:00:00Z',
  revoked_at: null,
  revoke_reason: null,
  created_at: '2026-09-18T00:00:00Z',
  status: 'ACTIVE',
  token: 'raw-token-1',
  share_url: '/share/session#token=raw-token-1',
}

const mountDialog = (props: Record<string, unknown> = {}) => mount(TaskSessionShareDialog, {
  props: {
    show: true,
    taskId: 'task-1',
    taskName: '我的任务',
    shares: [baseShare],
    loading: false,
    creating: false,
    revokingIds: new Set<string>(),
    canShare: true,
    justCreated: null,
    ...props,
  },
  global: {
    plugins: [i18n],
    stubs: { teleport: true },
  },
})

describe('TaskSessionShareDialog', () => {
  it('shows the create form and existing links with full URL', () => {
    const wrapper = mountDialog()
    expect(wrapper.find('.share-form').exists()).toBe(true)
    const items = wrapper.findAll('.share-list-item')
    expect(items).toHaveLength(1)
    expect(wrapper.find('.share-list-status').text()).toBe('有效')
    // 每条链接回显完整 URL（含明文令牌），随时可复制
    expect(wrapper.find('.share-list-url').text()).toContain('/share/session#token=raw-token-1')
    expect(wrapper.find('.share-copy-btn').exists()).toBe(true)
  })

  it('hides the create form without share permission but keeps the list', () => {
    const wrapper = mountDialog({ canShare: false })
    expect(wrapper.find('.share-form').exists()).toBe(false)
    expect(wrapper.find('.share-no-permission').exists()).toBe(true)
    expect(wrapper.find('.share-list-item').exists()).toBe(true)
  })

  it('emits create with READ mode and expiry days', async () => {
    const wrapper = mountDialog()
    await wrapper.find('.share-create-btn').trigger('click')
    const events = wrapper.emitted('create')
    expect(events).toHaveLength(1)
    expect(events![0][0]).toEqual({ mode: 'READ', expires_in_days: 7, instruction_text: undefined })
  })

  it('emits revoke when the revoke button is clicked on an active share', async () => {
    const wrapper = mountDialog()
    await wrapper.find('.share-revoke-btn').trigger('click')
    expect(wrapper.emitted('revoke')).toEqual([['share-1']])
  })

  it('hides URL / copy / revoke for inactive or token-less shares', () => {
    const wrapper = mountDialog({
      shares: [
        { ...baseShare, id: 'share-old', status: 'REVOKED', revoked_at: '2026-09-19T00:00:00Z', token: null, share_url: null },
        { ...baseShare, id: 'share-gone', status: 'SESSION_INVALID' },
      ],
    })
    const items = wrapper.findAll('.share-list-item')
    expect(items).toHaveLength(2)
    // 已撤销且无明文令牌：不显示 URL 与复制按钮
    expect(items[0].find('.share-list-url').exists()).toBe(false)
    expect(items[0].find('.share-copy-btn').exists()).toBe(false)
    // 任何非 ACTIVE 状态都不显示撤销按钮
    expect(items[0].find('.share-revoke-btn').exists()).toBe(false)
    expect(items[1].find('.share-revoke-btn').exists()).toBe(false)
    expect(items[0].find('.share-list-status').text()).toBe('已撤销')
    expect(items[1].find('.share-list-status').text()).toBe('会话已失效')
  })

  it('highlights the just-created row', () => {
    const wrapper = mountDialog({
      justCreated: {
        id: 'share-1',
        mode: 'READ',
        expires_at: '2026-09-25T00:00:00Z',
        instruction_text: null,
        session_generation: 1,
        share_token: 'raw-token-1',
        share_url: '/share/session#token=raw-token-1',
      },
    })
    expect(wrapper.find('.share-list-item.is-just-created').exists()).toBe(true)
  })
})
