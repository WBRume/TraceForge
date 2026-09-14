import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import zh from '@/locales/zh.json'
import en from '@/locales/en.json'
import ChatExecutionInput from '@/components/chat/ChatExecutionInput.vue'

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
  },
})

const pressEnter = (wrapper: ReturnType<typeof mountInput>) => (
  wrapper.find('textarea').trigger('keydown', { key: 'Enter' })
)

describe('ChatExecutionInput', () => {
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
