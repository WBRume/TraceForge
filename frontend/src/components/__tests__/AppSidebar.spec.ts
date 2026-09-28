import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AppSidebar from '../AppSidebar.vue'

describe('AppSidebar', () => {
  const dummyNavItems = [
    { key: 'dashboard', label: '仪表盘' },
    { key: 'chat', label: 'SDD 会话', active: true },
  ]
  const dummyFooterItems = [
    { key: 'settings', label: '设置' },
  ]

  it('renders correctly with default expanded state when defaultCollapsed is false', () => {
    const wrapper = mount(AppSidebar, {
      props: {
        title: '测试工作区',
        navItems: dummyNavItems,
        footerItems: dummyFooterItems,
        defaultCollapsed: false,
      },
      global: {
        stubs: {
          RouterLink: {
            template: '<a :href="to"><slot /></a>',
            props: ['to'],
          },
        },
      },
    })

    const aside = wrapper.find('aside.sidebar')
    expect(aside.exists()).toBe(true)
    expect(aside.classes()).not.toContain('is-collapsed')
    expect(wrapper.text()).toContain('测试工作区')
    expect(wrapper.text()).toContain('仪表盘')
    expect(wrapper.text()).toContain('SDD 会话')
    expect(wrapper.text()).toContain('设置')
  })

  it('toggles collapse state when toggle button is clicked', async () => {
    const wrapper = mount(AppSidebar, {
      props: {
        title: '测试工作区',
        navItems: dummyNavItems,
        defaultCollapsed: true,
      },
      global: {
        stubs: {
          RouterLink: true,
        },
      },
    })

    const aside = wrapper.find('aside.sidebar')
    expect(aside.classes()).toContain('is-collapsed')

    const toggleBtn = wrapper.find('.toggle-btn')
    expect(toggleBtn.exists()).toBe(true)
    await toggleBtn.trigger('click')

    expect(aside.classes()).not.toContain('is-collapsed')
  })

  it('emits back event when back button is clicked', async () => {
    const wrapper = mount(AppSidebar, {
      props: {
        title: '测试工作区',
        navItems: dummyNavItems,
        showBack: true,
      },
      global: {
        stubs: {
          RouterLink: true,
        },
      },
    })

    const backBtn = wrapper.find('.back-btn')
    expect(backBtn.exists()).toBe(true)
    await backBtn.trigger('click')

    expect(wrapper.emitted('back')).toBeTruthy()
    expect(wrapper.emitted('back')!.length).toBe(1)
  })
})
