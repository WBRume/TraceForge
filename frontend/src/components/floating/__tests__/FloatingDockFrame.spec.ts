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
  it.each([true, false])('hands off an eligible panel while crossing the edge (detachable=%s)', detachable => {
    const wrapper = mount(FloatingDockFrame, {
      props: { geometry: { ...geometry, minimized: false }, title: 'Task A', detachable },
    })
    const header = wrapper.find('header').element
    const outside = window.innerWidth - geometry.size.width + 30
    pointer(header, 'pointerdown', 110, 110)
    pointer(window, 'pointermove', outside, 110)
    const position = { x: outside - 10, y: 100 }
    expect(wrapper.emitted('panelDrag')).toEqual(detachable ? [[{ type: 'start' }], [{ type: 'move', position }]] : undefined)
    pointer(window, 'pointerup', outside, 110)
    expect(wrapper.emitted('panelDrag')?.at(-1)).toEqual(detachable ? [{ type: 'end', position }] : undefined)

    pointer(wrapper.find('.resize-handle-right').element, 'pointerdown', 450, 200)
    pointer(window, 'pointerup', outside, 200)
    expect(wrapper.emitted('panelDrag') ?? []).toHaveLength(detachable ? 3 : 0)
    wrapper.unmount()
  })
  it('allows a drag to come back into the client before release', () => {
    const wrapper = mount(FloatingDockFrame, {
      props: { geometry: { ...geometry, minimized: false }, title: 'Task A', detachable: true },
    })
    pointer(wrapper.find('header').element, 'pointerdown', 110, 110)
    pointer(window, 'pointermove', window.innerWidth + 30, 110)
    pointer(window, 'pointermove', 180, 140)
    expect(wrapper.emitted('panelDrag')?.at(-1)).toEqual([{ type: 'move', position: null }])
    pointer(window, 'pointerup', 180, 140)
    expect(wrapper.emitted('panelDrag')?.at(-1)).toEqual([{ type: 'end', position: null }])
    expect(wrapper.emitted('position')?.at(-1)).toEqual([{ x: 170, y: 130 }])
    wrapper.unmount()
  })
  it('holds a quick drop at the release position while the native window is preparing', async () => {
    const wrapper = mount(FloatingDockFrame, {
      props: { geometry: { ...geometry, minimized: false }, title: 'Task A', detachable: true, desktopDragActive: true },
    })
    pointer(wrapper.find('header').element, 'pointerdown', 110, 110)
    pointer(window, 'pointerup', window.innerWidth + 30, 110)
    await wrapper.vm.$nextTick()
    expect((wrapper.element as HTMLElement).style.translate).toBe(`${window.innerWidth - 80}px 0px`)
    await wrapper.setProps({ desktopDragActive: false })
    expect((wrapper.element as HTMLElement).style.translate).toBe('')
    wrapper.unmount()
  })
  it('keeps the same client frame mounted while its desktop window is visible', async () => {
    const wrapper = mount(FloatingDockFrame, {
      props: { geometry: { ...geometry, minimized: false }, title: 'Task A' },
      slots: { default: '<p>Conversation preview</p>' },
    })
    const panel = wrapper.element
    const content = wrapper.get('p').element
    await wrapper.setProps({ desktopPreview: true, desktopDetached: true })
    expect(wrapper.attributes('aria-hidden')).toBe('true')
    expect(wrapper.attributes()).toHaveProperty('inert')
    await wrapper.setProps({ desktopPreview: false, desktopDetached: false })
    expect(wrapper.element).toBe(panel)
    expect(wrapper.get('p').element).toBe(content)
    expect(wrapper.attributes('aria-hidden')).toBeUndefined()
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
