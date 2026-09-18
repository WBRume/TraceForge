import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'
import ChatMoreActionsMenu from '@/components/chat/ChatMoreActionsMenu.vue'
import { useGlobalSearchStore } from '@/stores/globalSearch'
import { useAuthStore } from '@/stores/auth'
import zh from '@/locales/zh.json'
import en from '@/locales/en.json'

const i18n = createI18n({
  legacy: false,
  locale: 'zh',
  fallbackLocale: 'en',
  messages: { zh, en },
})

const mountMenu = (props: Record<string, unknown> = {}) => {
  setActivePinia(createPinia())
  // 搜索能力默认开启（生产由 loadCapabilities 决定；组件测试直接置状态）
  const authStore = useAuthStore()
  authStore.token = 'test-token'
  const searchStore = useGlobalSearchStore()
  searchStore.capabilities = { enabled: true, ready: true, hybrid_available: false }
  return mount(ChatMoreActionsMenu, {
    attachTo: document.body,
    props: {
      canExport: true,
      canShare: true,
      showAttribution: true,
      attributionActive: false,
      ...props,
    },
    global: {
      plugins: [i18n],
    },
  })
}

/** 面板 Teleport 到 body（header-actions overflow 裁剪），统一从 body 查询。 */
const openMenu = async (wrapper: ReturnType<typeof mountMenu>) => {
  await wrapper.find('.more-actions-trigger').trigger('click')
  return document.body.querySelector('.more-actions-panel')
}

const itemLabels = (panel: Element | null): (string | null)[] =>
  Array.from(panel?.querySelectorAll('.item-label') || []).map((n) => n.textContent)

const findItem = (panel: Element | null, keyword: string): HTMLElement =>
  Array.from(panel?.querySelectorAll('.more-actions-item') || [])
    .find((n) => n.textContent?.includes(keyword)) as HTMLElement

const cleanupBody = () => {
  document.body.querySelectorAll('.more-actions-panel').forEach((n) => n.remove())
}

describe('ChatMoreActionsMenu', () => {
  it('renders trigger and opens the dropdown with all entries', async () => {
    const wrapper = mountMenu()
    expect(document.body.querySelector('.more-actions-panel')).toBeNull()

    const panel = await openMenu(wrapper)
    expect(panel).not.toBeNull()
    const labels = itemLabels(panel)
    expect(labels).toContain('导出会话')
    expect(labels).toContain('上下文窗口 / Token 归因')
    expect(labels).toContain('全局搜索')
    expect(labels).toContain('分享会话')
    wrapper.unmount()
    cleanupBody()
  })

  it('hides attribution entry when showAttribution is false (CLI mode)', async () => {
    const wrapper = mountMenu({ showAttribution: false })
    const panel = await openMenu(wrapper)
    const labels = itemLabels(panel)
    expect(labels).not.toContain('上下文窗口 / Token 归因')
    expect(labels).toContain('导出会话')
    wrapper.unmount()
    cleanupBody()
  })

  it('emits export when the export entry is clicked and closes the menu', async () => {
    const wrapper = mountMenu()
    const panel = await openMenu(wrapper)
    findItem(panel, '导出会话').click()
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('export')).toHaveLength(1)
    expect(document.body.querySelector('.more-actions-panel')).toBeNull()
    wrapper.unmount()
    cleanupBody()
  })

  it('emits open-attribution and share from their entries', async () => {
    const wrapper = mountMenu()
    let panel = await openMenu(wrapper)
    findItem(panel, 'Token 归因').click()
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('open-attribution')).toHaveLength(1)

    // openMenu 自带一次触发器点击（toggle），直接复用即可重新打开
    panel = await openMenu(wrapper)
    expect(panel).not.toBeNull()
    findItem(panel, '分享会话').click()
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('share')).toHaveLength(1)
    wrapper.unmount()
    cleanupBody()
  })

  it('disables export entry when canExport is false', async () => {
    const wrapper = mountMenu({ canExport: false })
    const panel = await openMenu(wrapper)
    const exportItem = findItem(panel, '导出会话')
    expect(exportItem.classList).toContain('is-disabled')

    exportItem.click()
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('export')).toBeUndefined()
    // 菜单保持打开（禁用项不收起）
    expect(document.body.querySelector('.more-actions-panel')).not.toBeNull()
    wrapper.unmount()
    cleanupBody()
  })

  it('marks active attribution with a dot and trigger highlight', async () => {
    const wrapper = mountMenu({ attributionActive: true })
    expect(wrapper.find('.more-actions-trigger').classes()).toContain('has-active')
    const panel = await openMenu(wrapper)
    const attrItem = findItem(panel, 'Token 归因')
    expect(attrItem.classList).toContain('is-active')
    expect(attrItem.querySelector('.item-active-dot')).not.toBeNull()
    wrapper.unmount()
    cleanupBody()
  })

  it('closes the menu on outside pointerdown', async () => {
    const wrapper = mountMenu()
    await openMenu(wrapper)
    expect(document.body.querySelector('.more-actions-panel')).not.toBeNull()

    document.body.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(document.body.querySelector('.more-actions-panel')).toBeNull()
    wrapper.unmount()
    cleanupBody()
  })
})
