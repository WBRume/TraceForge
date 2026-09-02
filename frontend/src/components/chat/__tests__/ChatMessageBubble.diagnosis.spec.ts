import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatMessageBubble from '@/components/chat/ChatMessageBubble.vue'
import type { DiagnosisResultPayload } from '@/types/diagnosis'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

const diagnosisMetadata: DiagnosisResultPayload = {
  summary: '连接池耗尽',
  root_cause: '连接池配置过小',
  evidence_chain: '',
  fix_suggestion: '',
  fix_code: '',
  code_context: [],
  similar_cases: [],
  call_chain: [],
  confidence: 80,
}

const makeVm = (overrides: Record<string, unknown> = {}) => ({
  isMessageFromCurrentUser: () => false,
  isMessageWorkspaceExpert: () => false,
  highlightedMessageId: '',
  formatMessageTime: () => '10:00:00',
  messageAuthorLabel: () => 'Claude',
  canMarkMessageAsDecision: () => false,
  chatDecisionSaving: false,
  submitMessageDecision: vi.fn(),
  diagnosisResult: { status: 'DRAFT', extracted_from_ai: true },
  diagnosisCaseLink: '',
  diagnosisResultSaving: false,
  diagnosisCaseCreating: false,
  saveDiagnosisResult: vi.fn(),
  createDiagnosisCase: vi.fn(),
  route: { params: { wsId: 'ws-1' } },
  router: { push: vi.fn() },
  ...overrides,
})

const mountBubble = (msg: Record<string, any>, vm: Record<string, unknown> = {}) =>
  mount(ChatMessageBubble, {
    props: { msg, vm: makeVm(vm) },
    global: {
      mocks: { $t: (key: string) => key },
      stubs: { 'el-slider': true },
    },
  })

describe('ChatMessageBubble diagnosis_result rendering', () => {
  it('renders the diagnosis result card inside the conversation for diagnosis_result messages', () => {
    const wrapper = mountBubble({
      id: 'msg-diag-1',
      role: 'assistant',
      content: '连接池耗尽',
      message_type: 'diagnosis_result',
      metadata: diagnosisMetadata,
      created_at: '2026-08-07T10:00:00Z',
    })

    expect(wrapper.find('.diagnosis-card').exists()).toBe(true)
    expect(wrapper.classes()).toContain('is-diagnosis-result')
    expect(wrapper.text()).toContain('diagnosis.panel_title')
    expect(wrapper.text()).toContain('连接池配置过小')
    expect(wrapper.find('.message-bubble').exists()).toBe(false)
  })

  it('renders a plain text bubble for regular messages', () => {
    const wrapper = mountBubble({
      id: 'msg-1',
      role: 'assistant',
      content: '你好',
      message_type: 'text',
      created_at: '2026-08-07T10:00:00Z',
    })

    expect(wrapper.find('.diagnosis-card').exists()).toBe(false)
    expect(wrapper.find('.message-bubble').exists()).toBe(true)
    expect(wrapper.text()).toContain('你好')
  })

  it('keeps the undo action visible and shows progress while the request is running', () => {
    const wrapper = mountBubble(
      {
        id: 'msg-undo-1',
        role: 'user',
        content: '请撤回这条消息',
        message_type: 'text',
        session_turn_id: 'turn-1',
        session_generation: 1,
        created_at: '2026-08-07T10:00:00Z',
      },
      {
        canUndoMessage: () => true,
        isUndoing: true,
        undoingMessageId: 'msg-undo-1',
      },
    )

    const undoButton = wrapper.find('.message-undo-btn')
    expect(undoButton.exists()).toBe(true)
    expect(undoButton.classes()).toContain('message-action-btn')
    expect(undoButton.classes()).toContain('is-loading')
    expect(undoButton.attributes('disabled')).toBeDefined()
    expect(undoButton.attributes('aria-busy')).toBe('true')
    expect(undoButton.find('.undo-spin').exists()).toBe(true)
  })

  it('requires confirmation before starting an undo', async () => {
    const wrapper = mountBubble(
      {
        id: 'msg-undo-confirm-1',
        role: 'user',
        content: '需要确认撤回',
        message_type: 'text',
        session_turn_id: 'turn-confirm-1',
        session_generation: 1,
        created_at: '2026-08-07T10:00:00Z',
      },
      {
        canUndoMessage: () => true,
        isUndoing: false,
        undoingMessageId: '',
      },
    )

    await wrapper.find('.message-undo-btn').trigger('click')
    expect(wrapper.emitted('undo-request')).toHaveLength(1)
    expect(wrapper.emitted('undo-request')?.[0]?.[0]).toMatchObject({
      id: 'msg-undo-confirm-1',
      content: '需要确认撤回',
    })
  })

  it('falls back to message content when metadata is missing', () => {
    const wrapper = mountBubble({
      id: 'msg-diag-2',
      role: 'assistant',
      content: '仅有摘要的定位结果',
      message_type: 'diagnosis_result',
      metadata: null,
      created_at: '2026-08-07T10:00:00Z',
    })

    expect(wrapper.find('.diagnosis-card').exists()).toBe(true)
    expect(wrapper.text()).toContain('仅有摘要的定位结果')
  })

  it('routes card save through the view model with the message id', async () => {
    const vm = makeVm()
    const wrapper = mountBubble(
      {
        id: 'msg-diag-3',
        role: 'assistant',
        content: '连接池耗尽',
        message_type: 'diagnosis_result',
        metadata: diagnosisMetadata,
        created_at: '2026-08-07T10:00:00Z',
      },
      vm,
    )

    const editButton = wrapper.findAll('button').find((btn) => btn.text().includes('diagnosis.edit'))
    await editButton!.trigger('click')

    const textarea = wrapper.findAll('textarea').find((el) => (el.element as HTMLTextAreaElement).value.includes('连接池配置过小'))!
    await textarea.setValue('根因已修改')

    const saveButton = wrapper.findAll('button').find((btn) => btn.text().includes('diagnosis.save_draft'))
    await saveButton!.trigger('click')

    expect(vm.saveDiagnosisResult).toHaveBeenCalledTimes(1)
    const [payload, messageId] = (vm.saveDiagnosisResult as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(messageId).toBe('msg-diag-3')
    expect((payload as DiagnosisResultPayload).root_cause).toBe('根因已修改')
  })

  it('hides confirm actions when the result is confirmed', () => {
    const wrapper = mountBubble(
      {
        id: 'msg-diag-4',
        role: 'assistant',
        content: '连接池耗尽',
        message_type: 'diagnosis_result',
        metadata: diagnosisMetadata,
        created_at: '2026-08-07T10:00:00Z',
      },
      { diagnosisResult: { status: 'CONFIRMED', extracted_from_ai: true } },
    )

    const confirmButton = wrapper.findAll('button').find((btn) => btn.text().includes('diagnosis.confirm_create_case'))
    expect(confirmButton).toBeUndefined()
    expect(wrapper.text()).toContain('diagnosis.result_confirmed')
  })
})
