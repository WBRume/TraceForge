import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import zh from '@/locales/zh.json'
import en from '@/locales/en.json'
import { useWorkspaceStore } from '@/stores/workspace'
import { WORKSPACE_HOME } from '@/types/workspaceWindows'
import DesktopWorkspacePicker from '../DesktopWorkspacePicker.vue'
import DesktopNewTabButton from '../DesktopNewTabButton.vue'
import DesktopTabStrip from '../DesktopTabStrip.vue'
import { describeDesktopTab } from '../desktopTabLabels'

const i18n = createI18n({ legacy: false, locale: 'zh', fallbackLocale: 'en', messages: { zh, en } })

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', redirect: '/workspaces' },
      { path: '/workspaces', name: 'workspaces', component: { template: '<div />' } },
      { path: '/workspaces/:wsId/dashboard', name: 'dashboard', component: { template: '<div />' } },
      { path: '/workspaces/:wsId/chat', name: 'taskChat', component: { template: '<div />' } },
      { path: '/workspaces/:wsId/assets/requirements', name: 'workspaceAssetsRequirements', component: { template: '<div />' } },
      { path: '/workspaces/:wsId/api-mock', name: 'apiMock', component: { template: '<div />' } },
      { path: '/workspaces/:wsId/workload', name: 'workspaceMemberWorkload', component: { template: '<div />' } },
      { path: '/workspaces/:wsId/settings', name: 'settings', component: { template: '<div />' } },
    ],
  })
}

const mounted: ReturnType<typeof mount>[] = []
const settle = async () => {
  await nextTick()
  await nextTick()
}

function makeWorkspaces(count: number) {
  return Array.from({ length: count }, (_, index) => ({
    id: `ws-${index + 1}`,
    name: `工作区-${index + 1}`,
    project: { name: index === 0 ? '核心平台' : `项目-${index + 1}` },
    repositories: index === 0 ? [{ repo_name: 'traceforge-web' }, { repo_name: 'traceforge-api' }] : [],
  }))
}

describe('DesktopWorkspacePicker', () => {
  let pinia: ReturnType<typeof createPinia>

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
  })

  afterEach(() => {
    mounted.splice(0).forEach(wrapper => wrapper.unmount())
    document.body.innerHTML = ''
    vi.restoreAllMocks()
  })

  function mountPicker(workspaceId = 'ws-1') {
    const wrapper = mount(DesktopWorkspacePicker, {
      attachTo: document.body,
      props: { workspaceId },
      global: { plugins: [pinia, i18n] },
    })
    mounted.push(wrapper)
    return wrapper
  }

  it('opens workspace popover with metadata, search filtering and footer overview action', async () => {
    const store = useWorkspaceStore()
    store.workspaces = makeWorkspaces(7)
    store.currentWorkspace = store.workspaces[0]
    vi.spyOn(store, 'fetchWorkspaces').mockResolvedValue(store.workspaces)

    const wrapper = mountPicker('ws-1')
    const trigger = wrapper.get('button.workspace-picker')
    expect(trigger.attributes('aria-expanded')).toBe('false')

    await trigger.trigger('click')
    await settle()

    expect(trigger.attributes('aria-expanded')).toBe('true')
    expect(store.fetchWorkspaces).toHaveBeenCalledWith(false)

    const panel = document.body.querySelector('.workspace-popover') as HTMLElement
    expect(panel).toBeTruthy()
    expect(panel.querySelector('.desktop-popover-count')?.textContent).toBe('7 个')
    expect(panel.querySelectorAll('.workspace-popover-item')).toHaveLength(7)

    const currentItem = panel.querySelector('.workspace-popover-item.is-current') as HTMLElement
    expect(currentItem.textContent).toContain('工作区-1')
    expect(currentItem.textContent).toContain('核心平台 · 2 个仓库')
    expect(currentItem.textContent).toContain('当前')

    const searchInput = panel.querySelector<HTMLInputElement>('.workspace-popover-search-input')!
    expect(searchInput).toBeTruthy()
    searchInput.value = '核心平台'
    searchInput.dispatchEvent(new Event('input'))
    await settle()

    expect(panel.querySelectorAll('.workspace-popover-item')).toHaveLength(1)
    searchInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await settle()

    expect(wrapper.emitted('select')).toEqual([['ws-1']])
    expect(document.body.querySelector('.workspace-popover')).toBeNull()

    await trigger.trigger('click')
    await settle()
    const footerBtn = document.body.querySelector<HTMLButtonElement>('.workspace-popover .desktop-popover-footer-btn')!
    footerBtn.click()
    await settle()
    expect(wrapper.emitted('select')?.[1]).toEqual([''])
  })

  it('closes on Escape and restores focus to trigger, and shows retry on empty load error', async () => {
    const store = useWorkspaceStore()
    vi.spyOn(store, 'fetchWorkspaces').mockRejectedValueOnce(new Error('network'))

    const wrapper = mountPicker('')
    const trigger = wrapper.get('button.workspace-picker')
    await trigger.trigger('click')
    await settle()

    const retry = document.body.querySelector<HTMLButtonElement>('.desktop-popover-retry')!
    expect(retry).toBeTruthy()

    vi.spyOn(store, 'fetchWorkspaces').mockImplementation(async () => {
      store.workspaces = makeWorkspaces(2)
      return store.workspaces
    })
    retry.click()
    await settle()
    expect(document.body.querySelectorAll('.workspace-popover-item')).toHaveLength(2)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await settle()
    expect(document.body.querySelector('.workspace-popover')).toBeNull()
    expect(document.activeElement).toBe(trigger.element)
  })
})

describe('DesktopNewTabButton & DesktopTabStrip', () => {
  afterEach(() => {
    mounted.splice(0).forEach(wrapper => wrapper.unmount())
    document.body.innerHTML = ''
    vi.restoreAllMocks()
  })

  it('opens 2-column new-tab popover without subtitles and supports grid keyboard navigation', async () => {
    const router = createTestRouter()
    const wrapper = mount(DesktopNewTabButton, {
      attachTo: document.body,
      props: { workspaceId: 'ws-1', disabled: false },
      global: { plugins: [router, i18n] },
    })
    mounted.push(wrapper)

    ;(wrapper.vm as { open: () => void }).open()
    await settle()

    const panel = document.body.querySelector('.newtab-popover') as HTMLElement
    expect(panel).toBeTruthy()
    expect(panel.querySelector('.newtab-popover-grid')).toBeTruthy()
    expect(panel.querySelectorAll('.newtab-popover-item')).toHaveLength(6)
    expect(panel.querySelector('.newtab-popover-desc')).toBeNull()
    expect(panel.querySelector('.desktop-popover-footer-desc')).toBeNull()
    expect(panel.querySelector('.desktop-popover-footer-btn')?.textContent).toContain('我的工作区')

    const items = panel.querySelectorAll<HTMLButtonElement>('[data-menu-item]')
    expect(document.activeElement).toBe(items[0])

    panel.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    expect(document.activeElement).toBe(items[1])

    panel.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
    expect(document.activeElement).toBe(items[3])

    panel.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }))
    expect(document.activeElement).toBe(items[1])

    items[1]!.click()
    await settle()
    expect(wrapper.emitted('open')).toEqual([['/workspaces/ws-1/chat']])
    expect(document.body.querySelector('.newtab-popover')).toBeNull()
  })

  it('opens WORKSPACE_HOME directly when workspaceId is empty', async () => {
    const router = createTestRouter()
    const wrapper = mount(DesktopNewTabButton, {
      attachTo: document.body,
      props: { workspaceId: '', disabled: false },
      global: { plugins: [router, i18n] },
    })
    mounted.push(wrapper)

    await wrapper.get('button.new-tab').trigger('click')
    expect(wrapper.emitted('open')).toEqual([[WORKSPACE_HOME]])
    expect(document.body.querySelector('.newtab-popover')).toBeNull()
  })

  it('renders tabs in DesktopTabStrip and delegates select, close and new tab trigger', async () => {
    const router = createTestRouter()
    const tabs = [
      describeDesktopTab({ id: 't1', path: '/workspaces/ws-1/dashboard' }, router, key => String(i18n.global.t(key))),
      describeDesktopTab({ id: 't2', path: '/workspaces/ws-1/api-mock' }, router, key => String(i18n.global.t(key))),
    ]
    const api = {
      isPrimary: true,
      drag: vi.fn(),
      moveWindow: vi.fn(),
      setStrip: vi.fn().mockResolvedValue(undefined),
      onDropHint: () => () => {},
      control: vi.fn(),
      command: vi.fn(),
      onUpdate: () => () => {},
    }
    const wrapper = mount(DesktopTabStrip, {
      attachTo: document.body,
      props: { api: api as any, tabs, activeId: 't1', workspaceId: 'ws-1' },
      global: { plugins: [router, i18n] },
    })
    mounted.push(wrapper)

    const tabEls = wrapper.findAll('.desktop-tab')
    expect(tabEls).toHaveLength(2)
    expect(tabEls[0]!.classes()).toContain('is-active')
    expect(tabEls[1]!.classes()).not.toContain('is-active')

    await tabEls[1]!.get('button.tab-label').trigger('click')
    expect(wrapper.emitted('select')).toEqual([['t2']])

    await tabEls[1]!.get('button.tab-close').trigger('click')
    expect(wrapper.emitted('close')).toEqual([['t2']])

    ;(wrapper.vm as { openNewTab: () => void }).openNewTab()
    await settle()
    expect(document.body.querySelector('.newtab-popover')).toBeTruthy()
  })
})
