import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import DiagnosisResultCard from '@/components/chat/DiagnosisResultCard.vue'
import type { DiagnosisResultPayload } from '@/types/diagnosis'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

const payload = (overrides: Partial<DiagnosisResultPayload> = {}): DiagnosisResultPayload => ({
  summary: '连接池在高峰期被耗尽',
  root_cause: '连接池配置过小',
  evidence_chain: '日志显示获取连接超时',
  fix_suggestion: '扩容连接池并增加熔断',
  fix_code: 'pool.maxActive = 200',
  code_context: [
    { file_path: 'src/pool.py', start_line: 12, end_line: 34, snippet: 'pool = Pool(maxActive=50)', note: '连接池配置' },
  ],
  similar_cases: [{ title: '连接池耗尽排查', similarity: '高', reference: 'case-1' }],
  call_chain: [{ seq: 1, module: 'Gateway', function: 'handleRequest', description: '入口' }],
  confidence: 85,
  ...overrides,
})

const mountCard = (props: Partial<Record<string, unknown>> = {}) =>
  mount(DiagnosisResultCard, {
    props: {
      payload: payload(),
      status: 'DRAFT',
      extractedFromAi: true,
      caseLink: '',
      saving: false,
      caseCreating: false,
      ...props,
    },
    global: {
      stubs: { 'el-slider': true },
    },
  })

const buttonByText = (wrapper: ReturnType<typeof mountCard>, text: string) =>
  wrapper.findAll('button').find((btn) => btn.text().includes(text))

describe('DiagnosisResultCard', () => {
  it('renders all structured sections from the AI-filled payload', () => {
    const wrapper = mountCard()

    expect(wrapper.text()).toContain('diagnosis.panel_title')
    expect(wrapper.text()).toContain('diagnosis.ai_filled')
    expect(wrapper.text()).toContain('连接池在高峰期被耗尽')
    expect(wrapper.text()).toContain('连接池配置过小')
    expect(wrapper.text()).toContain('日志显示获取连接超时')
    expect(wrapper.text()).toContain('src/pool.py:12-34')
    expect(wrapper.text()).toContain('pool.maxActive = 200')
    expect(wrapper.text()).toContain('连接池耗尽排查')
    expect(wrapper.text()).toContain('Gateway.handleRequest')
    expect(wrapper.text()).toContain('85%')
  })

  it('switches to edit mode, saves the edited payload and exits edit mode', async () => {
    const wrapper = mountCard()

    expect(wrapper.findAll('textarea')).toHaveLength(0)

    await buttonByText(wrapper, 'diagnosis.edit')!.trigger('click')
    expect(wrapper.findAll('textarea').length).toBeGreaterThan(0)

    const rootCauseTextarea = wrapper.findAll('textarea').find((el) => (el.element as HTMLTextAreaElement).value.includes('连接池配置过小'))
    expect(rootCauseTextarea).toBeTruthy()
    await rootCauseTextarea!.setValue('连接池被限流打满')

    await buttonByText(wrapper, 'diagnosis.save_draft')!.trigger('click')

    const saveEvents = wrapper.emitted('save')
    expect(saveEvents).toHaveLength(1)
    const saved = saveEvents![0][0] as DiagnosisResultPayload
    expect(saved.root_cause).toBe('连接池被限流打满')
    expect(saved.confidence).toBe(85)
    expect(saved.code_context[0].file_path).toBe('src/pool.py')

    // 保存后退出编辑态
    expect(wrapper.findAll('textarea')).toHaveLength(0)
  })

  it('cancel edit restores the original payload', async () => {
    const wrapper = mountCard()

    await buttonByText(wrapper, 'diagnosis.edit')!.trigger('click')
    const textarea = wrapper.findAll('textarea').find((el) => (el.element as HTMLTextAreaElement).value.includes('连接池配置过小'))!
    await textarea.setValue('被改坏了')

    await buttonByText(wrapper, 'diagnosis.cancel_edit')!.trigger('click')

    expect(wrapper.text()).toContain('连接池配置过小')
    expect(wrapper.emitted('save')).toBeUndefined()
  })

  it('hides edit and confirm actions when the result is CONFIRMED', () => {
    const wrapper = mountCard({ status: 'CONFIRMED', caseLink: 'case-9' })

    expect(buttonByText(wrapper, 'diagnosis.edit')).toBeUndefined()
    expect(buttonByText(wrapper, 'diagnosis.confirm_create_case')).toBeUndefined()
    expect(wrapper.text()).toContain('diagnosis.result_confirmed')
    expect(wrapper.text()).toContain('diagnosis.view_case')
  })

  it('has no redundant submit-review button and no card hint', () => {
    const wrapper = mountCard({ caseLink: 'case-7' })

    expect(buttonByText(wrapper, 'diagnosis.create_and_submit')).toBeUndefined()
    expect(wrapper.text()).not.toContain('diagnosis.card_hint')
  })

  it('emits confirm and openCase actions', async () => {
    const wrapper = mountCard({ caseLink: 'case-7' })

    await buttonByText(wrapper, 'diagnosis.confirm_create_case')!.trigger('click')
    await buttonByText(wrapper, 'diagnosis.view_case')!.trigger('click')

    expect(wrapper.emitted('confirm')).toHaveLength(1)
    expect(wrapper.emitted('confirmAndSubmit')).toBeUndefined()
    expect(wrapper.emitted('openCase')![0]).toEqual(['case-7'])
  })

  it('emits export and regenerate actions', async () => {
    const wrapper = mountCard({ caseLink: 'case-7' })

    await buttonByText(wrapper, 'diagnosis.export_markdown')!.trigger('click')
    await buttonByText(wrapper, 'diagnosis.regenerate')!.trigger('click')

    const exportEvents = wrapper.emitted('export')!
    expect(exportEvents).toHaveLength(1)
    expect((exportEvents[0][0] as DiagnosisResultPayload).root_cause).toBe('连接池配置过小')
    expect(wrapper.emitted('regenerate')).toHaveLength(1)
  })

  it('keeps export available on a CONFIRMED result and hides regenerate', () => {
    const wrapper = mountCard({ status: 'CONFIRMED', caseLink: 'case-9' })

    expect(buttonByText(wrapper, 'diagnosis.export_markdown')).toBeTruthy()
    expect(buttonByText(wrapper, 'diagnosis.regenerate')).toBeUndefined()
    expect(wrapper.text()).toContain('diagnosis.view_case')
  })

  it('adds and removes editable list items', async () => {
    const wrapper = mountCard()

    await buttonByText(wrapper, 'diagnosis.edit')!.trigger('click')

    await buttonByText(wrapper, 'diagnosis.add_code_context')!.trigger('click')
    await buttonByText(wrapper, 'diagnosis.add_similar_case')!.trigger('click')
    await buttonByText(wrapper, 'diagnosis.add_call_chain')!.trigger('click')

    const codeInputs = wrapper.findAll('input').filter((el) => (el.element as HTMLInputElement).placeholder === 'diagnosis.file_path_placeholder')
    expect(codeInputs.length).toBeGreaterThanOrEqual(2)

    await buttonByText(wrapper, 'diagnosis.save_draft')!.trigger('click')
    const events = wrapper.emitted('save')!
    const saved = events[events.length - 1][0] as DiagnosisResultPayload
    expect(saved.code_context.length).toBe(2)
    expect(saved.similar_cases.length).toBe(2)
    expect(saved.call_chain.length).toBe(2)
  })

  it('clamps out-of-range confidence from a loose payload', () => {
    const wrapper = mountCard({ payload: payload({ confidence: 150 }) })
    expect(wrapper.text()).toContain('100%')
  })
})
