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
