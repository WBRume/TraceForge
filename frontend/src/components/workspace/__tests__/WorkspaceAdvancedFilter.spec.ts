import { afterEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createI18n } from 'vue-i18n'
import zh from '@/locales/zh.json'
import en from '@/locales/en.json'
import BaseSelect from '@/components/BaseSelect.vue'
import WorkspaceAdvancedFilter from '@/components/workspace/WorkspaceAdvancedFilter.vue'
import type { WorkspaceFilterState } from '@/composables/useWorkspaceFilters'

const i18n = createI18n({ legacy: false, locale: 'zh', fallbackLocale: 'en', messages: { zh, en } })

const filters: WorkspaceFilterState = {
  project: '',
  product: '',
  repositories: [],
  owner: '',
  createdWithin: 'ALL',
  onlyMine: false,
}

const options = {
  projectOptions: [{ label: '支付平台', value: 'p-1' }],
  productOptions: [{ label: '网关 (v2)', value: 'prod-1' }],
  repositoryOptions: [{ label: 'pay-gateway', value: 'pay-gateway' }],
  ownerOptions: [{ label: '林可', value: 'u-1' }],
}

const mounted: ReturnType<typeof mount>[] = []
afterEach(() => {
  mounted.splice(0).forEach((wrapper) => wrapper.unmount())
  document.body.innerHTML = ''
})

function create(overrides: Record<string, unknown> = {}) {
  const wrapper = mount(WorkspaceAdvancedFilter, {
    attachTo: document.body,
    props: { filters, activeCount: 0, matchedCount: 3, ...options, ...overrides },
    global: { plugins: [i18n] },
  })
  mounted.push(wrapper)
  return wrapper
}

const settle = async () => {
  await nextTick()
  await nextTick()
}

describe('WorkspaceAdvancedFilter', () => {
  it('opens from the search bar trigger and exposes the full filter set', async () => {
    const wrapper = create({ activeCount: 2 })
    const trigger = wrapper.get('.ws-filter-trigger')

    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(trigger.attributes('aria-haspopup')).toBe('dialog')
    expect(wrapper.get('.ws-filter-badge').text()).toBe('2')

    await trigger.trigger('click')
    await settle()

    const panel = wrapper.get('.ws-filter-popover')
    expect(trigger.attributes('aria-expanded')).toBe('true')
    expect(trigger.attributes('aria-controls')).toBe(panel.attributes('id'))
    expect(panel.attributes('role')).toBe('dialog')
    expect(wrapper.findAllComponents(BaseSelect)).toHaveLength(5)
    expect(wrapper.get('.ws-filter-matched').text()).toBe('匹配 3 个工作区')
  })

  it('makes every large option list searchable and only the repository one multi-select', async () => {
    const wrapper = create()
    await wrapper.get('.ws-filter-trigger').trigger('click')
    await settle()

    const selects = wrapper.findAllComponents(BaseSelect)
    expect(selects.slice(0, 3).map((select) => select.props('searchable'))).toEqual([true, true, true])
    expect(selects[3]!.props('searchable')).toBe(false)
    expect(selects.map((select) => select.props('multiple'))).toEqual([false, false, false, false, true])
    expect(selects[4]!.props('searchable')).toBe(true)
  })

  it('emits a patch per changed field instead of mutating its props', async () => {
    const wrapper = create()
    await wrapper.get('.ws-filter-trigger').trigger('click')
    await settle()

    const selects = wrapper.findAllComponents(BaseSelect)
    selects[0]!.vm.$emit('update:modelValue', 'p-1')
    selects[1]!.vm.$emit('update:modelValue', 'prod-1')
    selects[2]!.vm.$emit('update:modelValue', 'u-1')
    selects[3]!.vm.$emit('update:modelValue', '7D')
    selects[4]!.vm.$emit('update:modelValue', ['pay-gateway', 'search-api'])

    expect(wrapper.emitted('patch')).toEqual([
      [{ project: 'p-1' }],
      [{ product: 'prod-1' }],
      [{ owner: 'u-1' }],
      [{ createdWithin: '7D' }],
      [{ repositories: ['pay-gateway', 'search-api'] }],
    ])
    expect(filters.project).toBe('')
    expect(filters.repositories).toEqual([])

    await wrapper.get('.ws-filter-toggle input').setValue(true)
    expect(wrapper.emitted('patch')?.at(-1)).toEqual([{ onlyMine: true }])
  })

  it('keeps reset disabled until a condition is active and forwards reset', async () => {
    const wrapper = create()
    await wrapper.get('.ws-filter-trigger').trigger('click')
    await settle()

    const reset = wrapper.get('.ws-filter-text-btn')
    expect(reset.attributes('disabled')).toBeDefined()
    await reset.trigger('click')
    expect(wrapper.emitted('reset')).toBeUndefined()

    await wrapper.setProps({ activeCount: 1 })
    await wrapper.get('.ws-filter-text-btn').trigger('click')
    expect(wrapper.emitted('reset')).toHaveLength(1)
  })

  it('closes on Escape and on outside pointerdown, returning focus to the trigger', async () => {
    const wrapper = create()
    const trigger = wrapper.get('.ws-filter-trigger')
    await trigger.trigger('click')
    await settle()
    expect(wrapper.find('.ws-filter-popover').exists()).toBe(true)

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await settle()
    expect(wrapper.find('.ws-filter-popover').exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)

    await trigger.trigger('click')
    await settle()
    document.body.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
    await settle()
    expect(wrapper.find('.ws-filter-popover').exists()).toBe(false)
  })

  it('stays open while interacting inside the panel', async () => {
    const wrapper = create()
    await wrapper.get('.ws-filter-trigger').trigger('click')
    await settle()

    wrapper.get('.ws-filter-title').element.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
    await settle()
    expect(wrapper.find('.ws-filter-popover').exists()).toBe(true)

    await wrapper.get('.ws-filter-done-btn').trigger('click')
    await settle()
    expect(wrapper.find('.ws-filter-popover').exists()).toBe(false)
  })
})
