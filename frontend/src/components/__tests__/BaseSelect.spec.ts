import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import BaseSelect from '../BaseSelect.vue'

const mounted: ReturnType<typeof mount>[] = []
afterEach(() => { mounted.splice(0).forEach(wrapper => wrapper.unmount()); document.body.innerHTML = ''; vi.restoreAllMocks() })
const options = [{ label: 'Local → Cloud', value: 'local' }, { label: 'Unavailable', value: 'disabled', disabled: true }, { label: 'Input → Cloud', value: 'input' }]
function create(extra = {}) {
  const wrapper = mount(BaseSelect, { attachTo: document.body, props: { modelValue: 'local', options, ariaLabel: 'Comparison source', ...extra } })
  mounted.push(wrapper)
  return wrapper
}

describe('BaseSelect keyboard access', () => {
  it('opens by keyboard, skips disabled options and commits only the active enabled option', async () => {
    const wrapper = create(), trigger = wrapper.get('[role="combobox"]')
    expect(trigger.attributes('tabindex')).toBe('0')
    expect(trigger.attributes('aria-label')).toBe('Comparison source')
    ;(trigger.element as HTMLElement).focus()
    await trigger.trigger('keydown', { key: 'Enter' })
    expect(trigger.attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('[role="listbox"]').attributes('id')).toBe(trigger.attributes('aria-controls'))
    await trigger.trigger('keydown', { key: 'ArrowDown' })
    expect(document.getElementById(trigger.attributes('aria-activedescendant')!)?.textContent).toBe('Input → Cloud')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    await trigger.trigger('keydown', { key: ' ' })
    expect(wrapper.emitted('update:modelValue')).toEqual([['input']])
    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(trigger.element)
  })

  it('Escape cancels the dropdown without closing its parent dialog, and Tab remains native', async () => {
    const parentEscape = vi.fn(), wrapper = create(), trigger = wrapper.get('[role="combobox"]')
    window.addEventListener('keydown', parentEscape)
    await trigger.trigger('keydown', { key: 'ArrowDown' })
    await trigger.trigger('keydown', { key: 'Escape' })
    expect(parentEscape.mock.calls.some(([event]) => event.key === 'Escape')).toBe(false)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    await trigger.trigger('keydown', { key: 'Enter' })
    const tab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    trigger.element.dispatchEvent(tab); await nextTick()
    expect(tab.defaultPrevented).toBe(false)
    expect(trigger.attributes('aria-expanded')).toBe('false')
    window.removeEventListener('keydown', parentEscape)
  })

  it('supports searching then choosing with Enter, with focus returned to its trigger', async () => {
    const wrapper = create({ searchable: true }), trigger = wrapper.get('.select-trigger')
    await trigger.trigger('keydown', { key: ' ' }); await nextTick()
    const search = wrapper.get('input')
    expect(document.activeElement).toBe(search.element)
    await search.setValue('Input')
    expect(wrapper.findAll('[role="option"]')).toHaveLength(1)
    await search.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('update:modelValue')).toEqual([['input']])
    expect(document.activeElement).toBe(trigger.element)
  })

  it('keeps disabled selects out of tab order and prevents opening', async () => {
    const wrapper = create({ disabled: true }), trigger = wrapper.get('[role="combobox"]')
    expect(trigger.attributes('tabindex')).toBe('-1')
    await trigger.trigger('keydown', { key: 'Enter' }); await trigger.trigger('click')
    expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
    expect(wrapper.emitted('open')).toBeUndefined()
  })
})

describe('BaseSelect multiple mode', () => {
  const multi = (modelValue: string[], extra = {}) => {
    const wrapper = mount(BaseSelect, {
      attachTo: document.body,
      props: {
        modelValue,
        options,
        multiple: true,
        searchable: true,
        placeholder: '全部项目',
        selectionText: (count: number) => `已选 ${count} 项`,
        clearText: '清除选择',
        ...extra,
      },
    })
    mounted.push(wrapper)
    return wrapper
  }

  it('summarises the selection and flags the empty state', async () => {
    expect(multi([]).get('.selected-text').text()).toBe('全部项目')
    expect(multi([]).get('.selected-text').classes()).toContain('is-placeholder')
    expect(multi(['input']).get('.selected-text').text()).toBe('Input → Cloud')
    expect(multi(['input']).get('.selected-text').classes()).not.toContain('is-placeholder')

    const many = multi(['input', 'local'])
    expect(many.get('.selected-text').text()).toBe('已选 2 项')
    expect(many.get('.selected-text').classes()).not.toContain('is-placeholder')
  })

  it('toggles options without closing, and marks each row as a checkbox', async () => {
    const wrapper = multi(['local'])
    await wrapper.get('.select-trigger').trigger('click')
    await nextTick()

    const rows = wrapper.findAll('[role="option"]')
    expect(rows).toHaveLength(3)
    expect(rows[0]!.attributes('aria-selected')).toBe('true')
    expect(rows[0]!.get('.option-check').classes()).toContain('is-checked')
    expect(rows[1]!.get('.option-check').classes()).not.toContain('is-checked')

    await rows[2]!.trigger('click')
    expect(wrapper.emitted('update:modelValue')).toEqual([[['local', 'input']]])
    expect(wrapper.get('.select-trigger').attributes('aria-expanded')).toBe('true')

    await wrapper.setProps({ modelValue: ['local', 'input'] })
    await rows[0]!.trigger('click')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([['input']])
    expect(wrapper.get('.select-trigger').attributes('aria-expanded')).toBe('true')
  })

  it('keeps focus in the search box while ticking options', async () => {
    const wrapper = multi([])
    await wrapper.get('.select-trigger').trigger('click')
    await nextTick()

    const search = wrapper.get('input')
    expect(document.activeElement).toBe(search.element)
    const mousedown = new MouseEvent('mousedown', { bubbles: true, cancelable: true })
    wrapper.findAll('[role="option"]')[0]!.element.dispatchEvent(mousedown)
    expect(mousedown.defaultPrevented).toBe(true)

    await search.setValue('Input')
    expect(wrapper.findAll('[role="option"]')).toHaveLength(1)
  })

  it('clears every selected option from the dropdown footer', async () => {
    const wrapper = multi(['local', 'input'])
    await wrapper.get('.select-trigger').trigger('click')
    await nextTick()

    const clear = wrapper.get('.select-clear-all')
    expect(clear.text()).toBe('清除选择')
    await clear.trigger('click')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([[]])
    expect(wrapper.get('.select-trigger').attributes('aria-expanded')).toBe('true')
  })

  it('hides the footer when nothing is selected', async () => {
    const wrapper = multi([])
    await wrapper.get('.select-trigger').trigger('click')
    await nextTick()
    expect(wrapper.find('.select-footer').exists()).toBe(false)
  })

  it('flips upwards when the viewport leaves too little room below', async () => {
    const wrapper = multi([])
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      top: 700, bottom: 732, left: 0, right: 200, width: 200, height: 32, x: 0, y: 700, toJSON: () => ({}),
    } as DOMRect)
    await wrapper.get('.select-trigger').trigger('click')
    await nextTick()
    expect(wrapper.get('.base-select').classes()).toContain('drop-up')

    vi.restoreAllMocks()
    await wrapper.get('.select-trigger').trigger('click')
    await wrapper.get('.select-trigger').trigger('click')
    await nextTick()
    expect(wrapper.get('.base-select').classes()).not.toContain('drop-up')
  })
})
