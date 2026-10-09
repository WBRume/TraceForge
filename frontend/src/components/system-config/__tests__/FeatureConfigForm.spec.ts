import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import BaseSelect from '@/components/BaseSelect.vue'
import FeatureConfigForm from '../FeatureConfigForm.vue'
import type { FeatureConfig, FeatureField } from '@/services/featureConfigApi'
import zh from '@/locales/zh.json'

const i18n = createI18n({ legacy: false, locale: 'zh', messages: { zh } })

const field = (key: string, label: string, hint: string, value = ''): FeatureField => ({
  key, label, kind: 'text', value, has_value: !!value, source: 'environment', options: [], minimum: 0, maximum: 4096, hint,
})

const configuration: FeatureConfig = {
  feature: 'speech',
  title: '语音输入',
  revision: 0,
  configured: false,
  fields: [
    field('mode', '识别模式', '在线识别使用云端服务，离线模式在本机完成。', 'api'),
    field('region', '服务地域', ''),
  ],
}

const render = () => mount(FeatureConfigForm, {
  props: { config: configuration },
  global: {
    plugins: [i18n],
    stubs: {
      'el-tooltip': { props: ['content'], template: '<span class="tip-stub"><slot /></span>' },
    },
  },
})

describe('feature configuration field tips', () => {
  it('renders a tips button only for fields with an explanation', () => {
    const wrapper = render()
    const tips = wrapper.findAll('.field-tip')
    expect(tips).toHaveLength(1)
    expect(tips[0]!.attributes('aria-label')).toBe('识别模式：在线识别使用云端服务，离线模式在本机完成。')
    expect(wrapper.text()).toContain('服务地域')
  })

  it('does not render a tips button for simple fields without a hint', () => {
    const wrapper = render()
    const titles = wrapper.findAll('.field-title')
    expect(titles).toHaveLength(2)
    const simple = titles.find(item => item.text().includes('服务地域'))
    expect(simple!.find('.field-tip').exists()).toBe(false)
  })
})


it('renders plugin fields and only the selected provider recognition methods', async () => {
  const config: FeatureConfig = { ...configuration,
    providers: [
      { id: 'bailian', label: '百炼', transports: ['websocket'], default_transport: 'websocket' },
      { id: 'openai_compatible', label: 'OpenAI 兼容', transports: ['http'], default_transport: 'http' },
    ],
    fields: [
      field('mode', '模式', '', 'api'),
      { ...field('provider', '供应商', '', 'bailian'), kind: 'select', options: ['bailian', 'openai_compatible'] },
      { ...field('transport', '识别方式', '', 'websocket'), kind: 'select', options: ['auto', 'http', 'websocket'] },
      { ...field('region', '服务地域', '', 'beijing'), group: 'recognition', visible_when: { provider: ['bailian'] } },
      { ...field('endpoint', '转写地址', '', 'https://voice.example/asr'), group: 'recognition', visible_when: { provider: ['openai_compatible'] } },
    ],
  }
  const wrapper = mount(FeatureConfigForm, { props: { config }, global: { plugins: [i18n], stubs: { 'el-tooltip': { template: '<span><slot /></span>' } } } })
  const selects = wrapper.findAllComponents(BaseSelect)
  expect(wrapper.find('#feature-speech-region').exists()).toBe(true)
  expect(wrapper.find('#feature-speech-endpoint').exists()).toBe(false)
  expect(selects[1]!.props('options').map(option => option.value)).toEqual(['auto', 'websocket'])
  selects[0]!.vm.$emit('update:modelValue', 'openai_compatible')
  await wrapper.vm.$nextTick()
  expect(wrapper.find('#feature-speech-region').exists()).toBe(false)
  expect(wrapper.find('#feature-speech-endpoint').exists()).toBe(true)
  expect(selects[1]!.props('options').map(option => option.value)).toEqual(['auto', 'http'])
  expect(selects[1]!.props('modelValue')).toBe('auto')
  wrapper.unmount()
})
