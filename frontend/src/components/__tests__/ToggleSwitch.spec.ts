import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import ToggleSwitch from '../ToggleSwitch.vue'

describe('controlled toggle switch', () => {
  it('reflects accepted v-model updates in both directions', async () => {
    const wrapper = mount(defineComponent({
      components: { ToggleSwitch }, setup: () => ({ enabled: ref(false) }),
      template: '<ToggleSwitch v-model="enabled" aria-label="Feature" />',
    }))
    const input = wrapper.get('input')
    await input.setValue(true)
    expect((input.element as HTMLInputElement).checked).toBe(true)
    await input.setValue(false)
    expect((input.element as HTMLInputElement).checked).toBe(false)
    wrapper.unmount()
  })
  it('waits for the parent to accept an asynchronous change', async () => {
    const wrapper = mount(ToggleSwitch, { props: { modelValue: false } })
    const input = wrapper.get('input')
    await input.setValue(true)
    expect(wrapper.emitted('update:modelValue')).toEqual([[true]])
    expect((input.element as HTMLInputElement).checked).toBe(false)
    await wrapper.setProps({ modelValue: true })
    expect((input.element as HTMLInputElement).checked).toBe(true)
    wrapper.unmount()
  })
})
