import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import type { AssetThread } from '@/composables/asset-discussion/types'
import zh from '@/locales/zh.json'
import ReviewAnnotationPopover from '../ReviewAnnotationPopover.vue'

function review(id: string, creator: string, created_at: string, content: string): AssetThread {
  return {
    id, asset_id: 'spec', version_id: 'v1', task_id: 'task', workspace_id: 'workspace', block_id: 'source-text',
    status: id === 'earliest' ? 'resolved' : 'open', creator_id: creator, creator_display_name: creator, created_at,
    selected_text: '审计策略', proposals: [],
    messages: [{ id: `msg-${id}`, thread_id: id, role: 'user', content, created_at }],
  }
}

it('opens on the earliest initiator and lets each author’s discussions be selected individually', async () => {
  const threads = [
    review('newer', '陈雨', '2026-11-20T01:30:00Z', '补充审计字段'),
    review('follow-up', '林晓', '2026-11-20T02:00:00Z', '补充保留期限'),
    review('earliest', '林晓', '2026-11-19T06:00:00Z', '记录拒绝事件'),
    review('other-quote', '周安', '2026-11-19T05:00:00Z', '另一段的讨论'),
  ]
  const wrapper = mount(ReviewAnnotationPopover, {
    props: {
      threads,
      target: { threadIds: ['newer', 'follow-up', 'earliest'], top: 50, left: 150 },
      selectedThreadId: '',
    },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh', messages: { zh } })],
      stubs: { teleport: true, UserAvatar: true },
    },
  })
  try {
    expect(wrapper.get('[role="dialog"]').attributes('aria-label')).toBe('此处有 3 个讨论串')
    expect(wrapper.get('[aria-pressed="true"]').attributes('aria-label')).toBe('林晓')
    expect(wrapper.text()).toContain('最早发起')
    const rows = wrapper.findAll('.review-popover-list button')
    expect(rows[0]!.text()).toContain('记录拒绝事件')
    expect(rows[1]!.text()).toContain('补充保留期限')
    expect(wrapper.find('button[aria-label="周安"]').exists()).toBe(false)
    await rows[1]!.trigger('click')
    await wrapper.get('button[aria-label="陈雨"]').trigger('click')
    await wrapper.get('.review-popover-list button').trigger('click')
    expect(wrapper.emitted('open-thread')).toEqual([['follow-up'], ['newer']])
  } finally {
    wrapper.unmount()
  }
})
