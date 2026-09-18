import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import ShareSuggestionPanel from '@/components/chat/ShareSuggestionPanel.vue'
import zh from '@/locales/zh.json'
import en from '@/locales/en.json'

const i18n = createI18n({
  legacy: false,
  locale: 'zh',
  fallbackLocale: 'en',
  messages: { zh, en },
})

const baseSuggestion = {
  id: 'sg-1',
  task_id: 'task-1',
  session_generation: 1,
  visitor_id: 'visitor-a',
  sender_user_id: null,
  display_name: '小张',
  original_content: '原始建议内容',
  edited_content: null,
  status: 'PENDING',
  version: 1,
  created_at: '2026-09-18T10:00:00Z',
  updated_at: null,
  adopted_at: null,
  effective_content: '原始建议内容',
}

const mountPanel = (props: Record<string, unknown> = {}) => mount(ShareSuggestionPanel, {
  props: {
    suggestions: [baseSuggestion],
    pendingCount: 1,
    loading: false,
    actingIds: new Set<string>(),
    hasDraft: false,
    ...props,
  },
  global: {
    plugins: [i18n],
  },
})

describe('ShareSuggestionPanel', () => {
  it('shows pending count badge and suggestion with source name', () => {
    const wrapper = mountPanel()
    expect(wrapper.find('.suggestion-count-badge').text()).toBe('1')
    expect(wrapper.find('.suggestion-source').text()).toBe('小张')
    expect(wrapper.find('.suggestion-content').text()).toBe('原始建议内容')
  })

  it('falls back to anonymous label when display name is missing', () => {
    const wrapper = mountPanel({
      suggestions: [{ ...baseSuggestion, display_name: null }],
    })
    expect(wrapper.find('.suggestion-source').text()).toBe('匿名访客')
  })

  it('emits adopt when the adopt button is clicked', async () => {
    const wrapper = mountPanel()
    const adoptBtn = wrapper
      .findAll('.suggestion-item-actions .btn-micro')
      .find((n) => n.text().includes('采纳'))!
    await adoptBtn.trigger('click')
    expect(wrapper.emitted('adopt')).toEqual([[baseSuggestion]])
  })

  it('shows replace-choice label on adopt when a draft exists', () => {
    const wrapper = mountPanel({ hasDraft: true })
    const adoptBtn = wrapper
      .findAll('.suggestion-item-actions .btn-micro')
      .find((n) => n.text().includes('采纳'))!
    expect(adoptBtn.text()).toContain('…')
  })

  it('toggles inline edit and emits edit with new content', async () => {
    const wrapper = mountPanel()
    const editBtn = wrapper
      .findAll('.suggestion-item-actions .btn-micro')
      .find((n) => n.text().includes('编辑'))!
    await editBtn.trigger('click')

    const textarea = wrapper.find('.suggestion-edit-input')
    expect(textarea.exists()).toBe(true)
    await textarea.setValue('编辑后的内容')

    const confirmBtn = wrapper
      .findAll('.suggestion-edit-actions .btn-micro')
      .find((n) => n.text().includes('确定'))!
    await confirmBtn.trigger('click')

    expect(wrapper.emitted('edit')).toEqual([[baseSuggestion, '编辑后的内容']])
    expect(wrapper.find('.suggestion-edit-input').exists()).toBe(false)
  })

  it('emits dismiss and copy from their buttons', async () => {
    const wrapper = mountPanel()
    const dismissBtn = wrapper
      .findAll('.suggestion-item-actions .btn-micro')
      .find((n) => n.text().includes('忽略'))!
    await dismissBtn.trigger('click')
    expect(wrapper.emitted('dismiss')).toEqual([[baseSuggestion]])

    const copyBtn = wrapper
      .findAll('.suggestion-item-actions .btn-micro')
      .find((n) => n.text().includes('复制'))!
    await copyBtn.trigger('click')
    expect(wrapper.emitted('copy')).toEqual([[baseSuggestion]])
  })

  it('shows edited content with the original struck through', () => {
    const wrapper = mountPanel({
      suggestions: [{
        ...baseSuggestion,
        edited_content: '编辑后的内容',
        effective_content: '编辑后的内容',
      }],
    })
    expect(wrapper.find('.suggestion-original-text').text()).toBe('原始建议内容')
    expect(wrapper.find('.suggestion-content').text()).toBe('编辑后的内容')
  })

  it('shows empty state when there are no suggestions', () => {
    const wrapper = mountPanel({ suggestions: [], pendingCount: 0 })
    expect(wrapper.find('.suggestion-empty').exists()).toBe(true)
  })
})
