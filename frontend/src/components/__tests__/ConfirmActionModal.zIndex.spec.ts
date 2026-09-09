import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ConfirmActionModal from '../ConfirmActionModal.vue'

describe('ConfirmActionModal z-index', () => {
  const baseProps = {
    title: 't',
    message: 'm',
    cancelText: 'c',
    confirmText: 'ok',
  }

  it('defaults to 120', () => {
    const wrapper = mount(ConfirmActionModal, {
      props: { ...baseProps, show: true },
      global: { stubs: { teleport: true } },
    })
    const overlay = wrapper.find('.modal-overlay')
    expect(overlay.attributes('style')).toContain('z-index: 120')
  })

  it('can be raised above a parent dialog overlay (e.g. 300)', () => {
    const wrapper = mount(ConfirmActionModal, {
      props: { ...baseProps, show: true, zIndex: 300 },
      global: { stubs: { teleport: true } },
    })
    const overlay = wrapper.find('.modal-overlay')
    expect(overlay.attributes('style')).toContain('z-index: 300')
  })

  it('renders in place (no teleport) when teleport is disabled', () => {
    const wrapper = mount(ConfirmActionModal, {
      props: { ...baseProps, show: true, teleport: false, zIndex: 400 },
    })
    // 关闭 teleport 后 overlay 渲染在组件原位置（可直接在 wrapper 内找到），
    // 作为宿主弹窗子元素天然叠在宿主内容之上
    const overlay = wrapper.find('.modal-overlay')
    expect(overlay.exists()).toBe(true)
    expect(overlay.attributes('style')).toContain('z-index: 400')
  })
})
