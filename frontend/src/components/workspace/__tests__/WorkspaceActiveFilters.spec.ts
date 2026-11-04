import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import zh from '@/locales/zh.json'
import en from '@/locales/en.json'
import WorkspaceActiveFilters from '@/components/workspace/WorkspaceActiveFilters.vue'
import type { ActiveWorkspaceFilter } from '@/composables/useWorkspaceFilters'

const i18n = createI18n({ legacy: false, locale: 'zh', fallbackLocale: 'en', messages: { zh, en } })

const options = {
  projectOptions: [{ label: '支付平台', value: 'p-1' }],
  productOptions: [{ label: '网关 (v2)', value: 'prod-1' }],
  repositoryOptions: [{ label: 'pay-gateway', value: 'pay-gateway' }],
  ownerOptions: [{ label: '林可', value: 'u-1' }],
}

const mountChips = (activeFilters: ActiveWorkspaceFilter[]) => mount(WorkspaceActiveFilters, {
  props: { activeFilters, ...options },
  global: { plugins: [i18n] },
})

describe('WorkspaceActiveFilters', () => {
  it('describes every active dimension with its display label', () => {
    const wrapper = mountChips([
      { key: 'project', value: 'p-1' },
      { key: 'product', value: 'prod-1' },
      { key: 'repository', value: 'pay-gateway' },
      { key: 'repository', value: 'search-api' },
      { key: 'owner', value: 'u-1' },
      { key: 'createdWithin', value: '7D' },
      { key: 'onlyMine', value: 'true' },
    ])
    const fields = wrapper.findAll('.ws-active-chip').map((chip) => chip.find('.ws-active-chip-field').exists() ? chip.get('.ws-active-chip-field').text() : '')
    const labels = wrapper.findAll('.ws-active-chip-label').map((chip) => chip.text())

    expect(fields).toEqual(['项目', '产品', '仓库', '仓库', '创建人', '创建时间', ''])
    expect(labels).toEqual([
      '支付平台',
      '网关 (v2)',
      'pay-gateway',
      'search-api',
      '林可',
      '近 7 天',
      '只看我创建的',
    ])
  })

  it('removes a single condition, including one repository, and resets all of them', async () => {
    const wrapper = mountChips([
      { key: 'repository', value: 'pay-gateway' },
      { key: 'repository', value: 'search-api' },
      { key: 'createdWithin', value: '30D' },
    ])

    await wrapper.findAll('.ws-active-chip')[1]!.trigger('click')
    expect(wrapper.emitted('clear')).toEqual([['repository', 'search-api']])

    await wrapper.findAll('.ws-active-chip')[2]!.trigger('click')
    expect(wrapper.emitted('clear')?.at(-1)).toEqual(['createdWithin', '30D'])

    await wrapper.get('.ws-active-reset').trigger('click')
    expect(wrapper.emitted('reset')).toHaveLength(1)
  })

  it('falls back to the raw value when the referenced option disappeared', () => {
    const wrapper = mountChips([{ key: 'owner', value: 'u-gone' }])
    expect(wrapper.get('.ws-active-chip-field').text()).toBe('创建人')
    expect(wrapper.get('.ws-active-chip-label').text()).toBe('u-gone')
  })
})
