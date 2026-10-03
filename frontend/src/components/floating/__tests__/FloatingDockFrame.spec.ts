import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import FloatingDockFrame from '../FloatingDockFrame.vue'

const geometry = { minimized: true, position: { x: 100, y: 100 }, size: { width: 350, height: 300 }, dockTop: 180 }
const pointer = (target: EventTarget, type: string, x: number, y: number) => {
  const event = new MouseEvent(type, { bubbles: true, clientX: x, clientY: y, button: 0 })
  Object.defineProperty(event, 'pointerId', { value: 1 }); target.dispatchEvent(event)
}
describe('shared floating frame gestures', () => {
  it('distinguishes a light tap from an edge drag', () => {
    const wrapper = mount(FloatingDockFrame, { props: { geometry, title: 'Task A' } })
    pointer(wrapper.element, 'pointerdown', 900, 180); pointer(window, 'pointerup', 900, 180)
    expect(wrapper.emitted('open')).toHaveLength(1)
    pointer(wrapper.element, 'pointerdown', 900, 180); pointer(window, 'pointermove', 900, 230); pointer(window, 'pointerup', 900, 230)
    expect(wrapper.emitted('dockTop')?.at(-1)).toEqual([230]); expect(wrapper.emitted('open')).toHaveLength(1)
    pointer(wrapper.element, 'pointerdown', 900, 180); pointer(window, 'pointerup', 900, 200)
    expect(wrapper.emitted('open')).toHaveLength(1)
    wrapper.unmount()
  })
  it('close and keyboard activation do not start a drag', async () => {
    const wrapper = mount(FloatingDockFrame, { props: { geometry, title: 'Task A' } })
    await wrapper.find('button').trigger('keydown', { key: 'Enter' }); expect(wrapper.emitted('open')).toBeUndefined()
    await wrapper.find('button').trigger('click'); expect(wrapper.emitted('close')).toHaveLength(1)
    await wrapper.trigger('keydown', { key: 'Enter' }); expect(wrapper.emitted('open')).toHaveLength(1)
    wrapper.unmount()
  })
  it('moves the panel and supports horizontal and corner resize independently', () => {
    const wrapper = mount(FloatingDockFrame, { props: { geometry: { ...geometry, minimized: false }, title: 'Task A' } })
    pointer(wrapper.find('header').element, 'pointerdown', 110, 110); pointer(window, 'pointermove', 160, 150); pointer(window, 'pointerup', 160, 150)
    expect(wrapper.emitted('position')?.at(-1)).toEqual([{ x: 150, y: 140 }])
    pointer(wrapper.find('.resize-handle-right').element, 'pointerdown', 450, 200); pointer(window, 'pointermove', 490, 250); pointer(window, 'pointerup', 490, 250)
    expect(wrapper.emitted('size')?.at(-1)).toEqual([{ width: 390, height: 300 }])
    pointer(wrapper.find('.resize-handle-corner').element, 'pointerdown', 450, 400); pointer(window, 'pointermove', 470, 430); pointer(window, 'pointerup', 470, 430)
    expect(wrapper.emitted('size')?.at(-1)).toEqual([{ width: 370, height: 330 }])
    wrapper.unmount()
  })
  it('pointer cancellation and unmount clear global gesture listeners', () => {
    const wrapper = mount(FloatingDockFrame, { props: { geometry, title: 'Task A' } })
    pointer(wrapper.element, 'pointerdown', 900, 180); pointer(window, 'pointercancel', 900, 180); pointer(window, 'pointerup', 900, 180)
    expect(wrapper.emitted('open')).toBeUndefined()
    pointer(wrapper.element, 'pointerdown', 900, 180); wrapper.unmount(); pointer(window, 'pointermove', 900, 250)
    expect(wrapper.emitted('dockTop')).toBeUndefined()
  })
})
