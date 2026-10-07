import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import FeatureConfigForm from '../FeatureConfigForm.vue'
import type { FeatureConfig, FeatureField } from '@/services/featureConfigApi'
import zh from '@/locales/zh.json'

const i18n = createI18n({ legacy: false, locale: 'zh', messages: { zh } })

const booleanField = (key: string, label: string, value: boolean, hint = ''): FeatureField => ({
  key, label, kind: 'boolean', value, has_value: value, source: 'environment', options: [], minimum: 0, maximum: 4096, hint,
})

const configuration: FeatureConfig = {
  feature: 'search',
  title: '全局搜索',
  revision: 0,
  configured: false,
  fields: [
    booleanField('enabled', '启用搜索', false),
    booleanField('workers_enabled', '内置索引工作进程', true, '需先启用全局搜索'),
  ],
}

const render = () => mount(FeatureConfigForm, {
  props: { config: configuration },
  global: {
    plugins: [i18n],
    stubs: { 'el-tooltip': { props: ['content'], template: '<span class="tip-stub"><slot /></span>' } },
  },
})

describe('feature configuration boolean fields', () => {
  it('renders boolean fields as switches instead of plain checkboxes', () => {
    const wrapper = render()
    const switches = wrapper.findAll('.switch-field input[role="switch"]')
    expect(switches).toHaveLength(2)
    expect(wrapper.find('.check-field').exists()).toBe(false)
    expect(wrapper.find('.link-badge').exists()).toBe(false)
  })

  it('reflects the switch state in the status text', async () => {
    const wrapper = render()
    const enabled = wrapper.get('#feature-search-enabled')
    expect(enabled.attributes('role')).toBe('switch')
    expect(wrapper.findAll('.switch-state')[0]!.text()).toBe('已停用')

    await enabled.setValue(true)
    expect(wrapper.findAll('.switch-state')[0]!.text()).toBe('已启用')
  })
})
