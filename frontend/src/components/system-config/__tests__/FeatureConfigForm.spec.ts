import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
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
