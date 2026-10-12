import { afterEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import AppSideDrawer from '../AppSideDrawer.vue'
import ConfirmActionModal from '../ConfirmActionModal.vue'

const mounted: ReturnType<typeof mount>[] = []
afterEach(() => { mounted.splice(0).forEach(wrapper => wrapper.unmount()); document.body.innerHTML = '' })

describe('AppSideDrawer keyboard access', () => {
  it('names its dialog, contains tab focus, closes on Escape and restores the entry focus', async () => {
    const entry = document.createElement('button'); entry.textContent = 'Code'; document.body.append(entry); entry.focus()
    const wrapper = mount(AppSideDrawer, { attachTo: document.body, props: { show: false, title: '代码协同', hideClose: true }, slots: { default: '<button id="first">Compare</button><button id="last">Restore</button>' }, global: { mocks: { $t: (key: string) => key } } })
    mounted.push(wrapper)
    await wrapper.setProps({ show: true }); await nextTick()
    const panel = wrapper.get('[role="dialog"]')
    expect(panel.attributes('aria-modal')).toBe('true')
    expect(document.getElementById(panel.attributes('aria-labelledby')!)?.textContent).toBe('代码协同')
    expect(document.activeElement?.id).toBe('first')
    document.getElementById('last')!.focus()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', cancelable: true }))
    expect(document.activeElement?.id).toBe('first')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, cancelable: true }))
    expect(document.activeElement?.id).toBe('last')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', cancelable: true }))
    expect(wrapper.emitted('close')).toHaveLength(1)
    await wrapper.setProps({ show: false })
    expect(document.activeElement).toBe(entry)
  })
  it('does not close the underlying drawer when a nested modal has focus', async () => {
    const wrapper = mount(AppSideDrawer, { attachTo: document.body, props: { show: true, title: 'Code' }, global: { mocks: { $t: (key: string) => key } } }); mounted.push(wrapper)
    await nextTick()
    const confirmation = document.createElement('button'); document.body.append(confirmation); confirmation.focus()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', cancelable: true }))
    expect(wrapper.emitted('close')).toBeUndefined()
  })
  it('moves focus into a restoration confirmation and cancels only the top dialog', async () => {
    const drawer = mount(AppSideDrawer, { attachTo: document.body, props: { show: true, title: 'Code', hideClose: true }, slots: { default: '<button id="restore">Restore</button>' }, global: { mocks: { $t: (key: string) => key } } }); mounted.push(drawer)
    await nextTick()
    const dialog = mount(ConfirmActionModal, { attachTo: document.body, props: { show: true, title: 'Restore selected files', message: 'Back up first', cancelText: 'Cancel', confirmText: 'Restore' } }); mounted.push(dialog)
    await nextTick()
    expect(document.activeElement?.textContent).toBe('Cancel')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', cancelable: true }))
    expect(dialog.emitted('cancel')).toHaveLength(1)
    expect(drawer.emitted('close')).toBeUndefined()
    await dialog.setProps({ show: false })
    expect(document.activeElement?.id).toBe('restore')
  })
})
