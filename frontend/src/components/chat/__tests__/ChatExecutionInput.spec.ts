import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import zh from '@/locales/zh.json'
import en from '@/locales/en.json'
import ChatExecutionInput from '@/components/chat/ChatExecutionInput.vue'

const cancelSpeech = vi.fn()

const i18n = createI18n({
  legacy: false,
  locale: 'zh',
  fallbackLocale: 'en',
  messages: { zh, en },
})

const mountInput = (props: Record<string, unknown> = {}) => mount(ChatExecutionInput, {
  props: {
    modelValue: 'hello',
    disabled: false,
    running: false,
    canInterrupt: true,
    interrupting: false,
    placeholder: 'placeholder',
    sendTitle: 'send',
    interruptTitle: 'stop',
    ...props,
  },
  global: {
    plugins: [i18n],
    stubs: { SpeechInputButton: {
      name: 'SpeechInputButton', template: '<div />', emits: ['transcript', 'busy'], methods: { cancel: cancelSpeech },
    } },
  },
})

const pressEnter = (wrapper: ReturnType<typeof mountInput>) => (
  wrapper.find('textarea').trigger('keydown', { key: 'Enter' })
)

describe('ChatExecutionInput', () => {
  afterEach(() => { vi.unstubAllEnvs() })

  it('inserts interim text at the cursor and revises it without duplicating the final result', async () => {
    vi.stubEnv('VITE_SPEECH_MODE', 'api')
    const wrapper = mountInput({ modelValue: '前文后文' }); await flushPromises()
    const input = wrapper.get('textarea')
    input.element.setSelectionRange(2, 2)
    const speech = wrapper.findComponent({ name: 'SpeechInputButton' })
    speech.vm.$emit('busy', true)
    speech.vm.$emit('transcript', '你')
    expect(input.element.value).toBe('前文你后文')
    await wrapper.setProps({ modelValue: '前文你后文' })
    speech.vm.$emit('transcript', '你好。')
    expect(input.element.value).toBe('前文你好。后文')
    await wrapper.setProps({ modelValue: '前文你好。后文' })
    speech.vm.$emit('transcript', '你好。')
    expect(wrapper.emitted('update:modelValue')).toEqual([['前文你后文'], ['前文你好。后文']])
    await pressEnter(wrapper)
    expect(wrapper.emitted('submit')).toBeUndefined()
    speech.vm.$emit('busy', false)
    expect(input.element.value).toBe('前文你好。后文')
    wrapper.unmount()
  })

  it('does not erase a selection on an empty sentence-begin event', async () => {
    vi.stubEnv('VITE_SPEECH_MODE', 'api')
    const wrapper = mountInput(); await flushPromises()
    wrapper.get('textarea').element.setSelectionRange(0, 5)
    const speech = wrapper.findComponent({ name: 'SpeechInputButton' })
    speech.vm.$emit('busy', true); speech.vm.$emit('transcript', '')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    speech.vm.$emit('transcript', '你好')
    expect(wrapper.emitted('update:modelValue')).toEqual([['你好']])
    wrapper.unmount()
  })

  it('preserves a manual correction and stops updating that dictation range', async () => {
    vi.stubEnv('VITE_SPEECH_MODE', 'api')
    const wrapper = mountInput({ modelValue: '' }); await flushPromises()
    const speech = wrapper.findComponent({ name: 'SpeechInputButton' })
    speech.vm.$emit('busy', true); speech.vm.$emit('transcript', '你好')
    await wrapper.setProps({ modelValue: '你好' })
    await wrapper.get('textarea').setValue('您好')
    expect(cancelSpeech).toHaveBeenCalledOnce()
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['您好'])
    wrapper.unmount()
  })

  it('shows the current model and emits a change from the selector next to send', async () => {
    const wrapper = mountInput({ showModelSelector: true, selectedModel: 'private/a', modelOptions: [
      { value: 'private/a', label: 'Model A' }, { value: 'private/b', label: 'Model B' },
    ] })
    expect(wrapper.find('.agent-model-select').text()).toContain('Model A')
    await wrapper.find('.agent-model-select .select-trigger').trigger('click')
    expect(wrapper.emitted('reload-models')).toHaveLength(1)
    await wrapper.findAll('.agent-model-select .option-item')[1]!.trigger('click')
    expect(wrapper.emitted('update:selectedModel')).toEqual([['private/b']])
    expect(wrapper.find('.agent-model-select').element.compareDocumentPosition(wrapper.find('.send-btn').element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    wrapper.unmount()
  })
  it('submits on Enter when the engine is idle', async () => {
    const wrapper = mountInput()

    await pressEnter(wrapper)

    expect(wrapper.emitted('submit')).toHaveLength(1)
  })

  it('does not submit on Enter while the engine is running', async () => {
    const wrapper = mountInput({ running: true })

    await pressEnter(wrapper)

    expect(wrapper.emitted('submit')).toBeUndefined()
    expect(wrapper.find('.stop-btn').exists()).toBe(true)
  })

  it('does not start the pre input collection on Enter while the engine is running', async () => {
    const wrapper = mountInput({
      running: true,
      preInputMode: true,
      canStartPreInput: true,
    })

    await pressEnter(wrapper)

    expect(wrapper.emitted('submit')).toBeUndefined()
    expect(wrapper.emitted('start-pre-input')).toBeUndefined()
  })

  it('disables the pre input toggle while the engine is running', () => {
    const wrapper = mountInput({ running: true })

    expect(wrapper.find('.tool-toggle').attributes('disabled')).toBeDefined()
  })

  it('does not submit on Enter when the input is disabled', async () => {
    const wrapper = mountInput({ disabled: true })

    await pressEnter(wrapper)

    expect(wrapper.emitted('submit')).toBeUndefined()
  })
})
