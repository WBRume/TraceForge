import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import ChatMessageContent from '../ChatMessageContent.vue'
import ChatMessageBubble from '../ChatMessageBubble.vue'
import TerminalTimeline from '../terminal/TerminalTimeline.vue'
import { mergeTerminalTimeline } from '@/utils/chat-terminal/mergeTerminalTimeline'
import { confirmationHistoryRecord } from '@/composables/chat/message/confirmationHistory'
import zh from '@/locales/zh.json'

const fields = [
  { key: 'q0', type: 'string', title: '项目类型', description: '你希望创建哪种类型的 Python 项目？', options: [{ value: 'ml', label: 'AI / 机器学习项目' }] },
  { key: 'q1', type: 'multiselect', title: '开发工具', description: '需要配置哪些开发工具？', options: [{ value: 'lint', label: 'Ruff' }] },
  { key: 'q2', type: 'boolean', title: '启用部署' },
  { key: 'q3', type: 'integer', title: '重试次数' },
]
const question = { id: 'question', role: 'assistant', content: 'Questions\n项目类型\n开发工具', session_generation: 1,
  metadata: { confirmation: { interaction_id: 'i1', kind: 'form', fields } } }
const answer = { id: 'answer', role: 'user', content: '{"q0":"ml","q1":[],"q2":false,"q3":0}', session_generation: 1,
  metadata: { interaction_id: 'i1', reply_to_message_id: 'question' } }
const resolution = { id: 'resolution', role: 'assistant', content: '提问已回答：raw JSON', session_generation: 1,
  metadata: { confirmation_resolution: { interaction_id: 'i1', status: 'answered', answer: JSON.parse(answer.content) } } }
const i18n = () => createI18n({ legacy: false, locale: 'zh', messages: { zh } })
const render = (msg: any, relatedMessages: any[] = []) => mount(ChatMessageContent, {
  props: { msg, relatedMessages, authorLabel: '张三', timeLabel: '20:03' }, global: { plugins: [i18n()] },
})

describe('confirmation history', () => {
  it('shows the full questions, choices, identity and distinct question marker', () => {
    const wrapper = render(question)
    expect(wrapper.get('[aria-label="提问"]').text()).toContain('4 个问题')
    expect(wrapper.text()).toContain('你希望创建哪种类型的 Python 项目？')
    expect(wrapper.text()).toContain('AI / 机器学习项目')
    expect(wrapper.text()).toContain('张三')
    expect(wrapper.text()).not.toContain('Questions')
    expect(wrapper.findAll('input,select,button')).toHaveLength(0)
  })

  it('maps answer keys and option values, preserving empty selections, false and zero', () => {
    const wrapper = render(answer, [question, answer])
    expect(wrapper.get('[aria-label="回答"]').text()).toContain('项目类型')
    expect(wrapper.text()).toContain('AI / 机器学习项目')
    expect(wrapper.text()).toContain('未选择')
    expect(wrapper.findAll('.question-answer').map(item => item.text())).toEqual(['AI / 机器学习项目', '未选择', '否', '0'])
    expect(wrapper.text()).not.toContain('q0')
  })

  it('hides the entire duplicate receipt and keeps external answers visible', async () => {
    const wrapper = render(resolution, [question, answer, resolution])
    expect(wrapper.find('.message-wrapper').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
    await wrapper.setProps({ relatedMessages: [question, resolution] })
    expect(wrapper.findAll('.question-answer')).toHaveLength(4)
    for (const delivery_status of ['pending', 'failed']) {
      await wrapper.setProps({ relatedMessages: [question, { ...answer, delivery_status }, resolution] })
      expect(wrapper.findAll('.question-answer')).toHaveLength(4)
    }
    await wrapper.setProps({ relatedMessages: [question, { ...answer, session_generation: 0 }, resolution] })
    expect(wrapper.findAll('.question-answer')).toHaveLength(4)
    await wrapper.setProps({ relatedMessages: [question, { ...answer, delivery_status: 'sent' }, resolution] })
    expect(wrapper.find('.message-wrapper').exists()).toBe(false)
  })

  it('supports answers fetched on another history page using server context', () => {
    const wrapper = render({ ...answer, metadata: { ...answer.metadata, confirmation_context: { fields } } })
    expect(wrapper.text()).toContain('项目类型')
    expect(wrapper.text()).not.toContain('q0')
    const receipt = render({ ...resolution, metadata: { ...resolution.metadata, confirmation_context: { fields, answer_message_id: 'answer' } } })
    expect(receipt.find('.message-wrapper').exists()).toBe(false)
  })

  it('never treats ordinary JSON as a confirmation or borrows questions from another generation', () => {
    expect(confirmationHistoryRecord({ role: 'user', content: answer.content })).toBeNull()
    const wrapper = render(answer, [{ ...question, session_generation: 0 }])
    expect(wrapper.text()).not.toContain('项目类型')
  })

  it('preserves custom explanations while translating the selected option label', () => {
    const wrapper = render({ ...answer, content: JSON.stringify({ q0: 'ml\n使用现有模型' }) }, [question])
    expect(wrapper.get('.question-answer').text()).toBe('AI / 机器学习项目\n使用现有模型')
  })

  it('keeps plain confirmation prompts readable and permission receipts free of protocol values', () => {
    const prompt = { ...question, content: '是否继续执行？', metadata: { confirmation: { interaction_id: 'i1', kind: 'boolean' } } }
    const wrapper = render(prompt)
    expect(wrapper.text()).toContain('是否继续执行？')
    expect(wrapper.findAll('.history-row')).toHaveLength(0)
    const receipt = render({ ...resolution, metadata: { confirmation_resolution: { interaction_id: 'i1', status: 'approved', answer: 'once' } } }, [prompt])
    expect(receipt.text()).toContain('请求已批准')
    expect(receipt.text()).not.toContain('once')
  })

  it.each(['cancelled', 'rejected', 'closed'])('renders %s without inventing an answer', status => {
    const wrapper = render({ ...resolution, metadata: { confirmation_resolution: { interaction_id: 'i1', status } } }, [question, answer])
    expect(wrapper.text()).toContain(zh.chat.confirmation_history[status as 'cancelled'])
    expect(wrapper.findAll('.question-answer')).toHaveLength(0)
  })

  it('uses the same readable records in the terminal', () => {
    const locale = i18n()
    const entries = mergeTerminalTimeline({ messages: [question, answer, resolution], terminalLogs: [], localEchoes: [], statusCards: [], hitlCards: [], resultHistory: [] })
    const wrapper = mount(TerminalTimeline, { props: { entries, loadingMore: false, hasMore: false, formatTime: () => '20:03', formatToolInput: String, t: locale.global.t }, global: { plugins: [locale] } })
    expect(wrapper.text()).toContain('你希望创建哪种类型的 Python 项目？')
    expect(entries.map(entry => entry.id)).toEqual(['msg-question', 'msg-answer'])
    expect(wrapper.findAll('.kind-message')).toHaveLength(2)
    expect(wrapper.text()).not.toContain('提问已回答')
    expect(wrapper.text()).not.toContain('q0')
    const external = mergeTerminalTimeline({ messages: [question, resolution], terminalLogs: [], localEchoes: [], statusCards: [], hitlCards: [], resultHistory: [] })
    expect(external.map(entry => entry.id)).toEqual(['msg-question', 'msg-resolution'])
  })

  it('copies readable answers with question titles instead of transport keys', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    const wrapper = mount(ChatMessageBubble, { props: { msg: answer, vm: { messages: [question, answer], messageAuthorLabel: () => '张三', formatMessageTime: () => '20:03', isMessageWorkspaceExpert: () => false, isMessageFromCurrentUser: () => true, canMarkMessageAsDecision: () => false } }, global: { plugins: [i18n()], stubs: { DecisionMarkPopover: true } } })
    await wrapper.get('.message-copy-btn').trigger('click')
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('项目类型'))
    expect(writeText.mock.calls[0]![0]).not.toContain('q0')
    wrapper.unmount()
  })
})
