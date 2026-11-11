import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import WorkspaceLayout from '@/views/layouts/WorkspaceLayout.vue'
import zh from '@/locales/zh.json'
import en from '@/locales/en.json'

const env = vi.hoisted(() => ({ desktop: false }))
vi.mock('@/utils/runtime', () => ({
  isDesktop: () => env.desktop,
  getSddDesktop: () => null,
}))

const workspace = {
  id: 'ws-1',
  name: 'Demo Workspace',
  git_repo_url: 'https://github.com/acme/demo.git',
}
const workspaceStore = vi.hoisted(() => ({
  currentWorkspace: null as typeof workspace | null,
  restoreCurrent: vi.fn(),
}))
vi.mock('@/stores/workspace', () => ({
  useWorkspaceStore: () => workspaceStore,
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { id: 'user-1' }, token: 'token' }),
}))
vi.mock('@/stores/taskRail', () => ({
  useTaskRailStore: () => ({ setContext: vi.fn() }),
}))

const i18n = createI18n({
  legacy: false,
  locale: 'zh',
  fallbackLocale: 'en',
  messages: { zh, en },
})

const mountLayout = async () => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/workspaces/:wsId/dashboard', name: 'dashboard', component: { template: '<div />' } },
    ],
  })
  await router.push('/workspaces/ws-1/dashboard')
  await router.isReady()
  const wrapper = mount(WorkspaceLayout, {
    global: {
      plugins: [i18n, router],
      stubs: {
        AppSidebar: { template: '<div><slot name="context-chat" /><slot name="footer-extra" /></div>' },
        TaskHostRail: true,
        NotificationBell: true,
      },
    },
  })
  await flushPromises()
  return wrapper
}

const setupKey = () => `local-resource-setup:${location.origin}:user-1:ws-1`

describe('WorkspaceLayout local repo setup prompt', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    env.desktop = false
    workspaceStore.currentWorkspace = workspace
    workspaceStore.restoreCurrent.mockClear()
  })

  it('does not prompt for local repo setup in a plain browser', async () => {
    const wrapper = await mountLayout()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  })

  it('prompts for local repo setup in the desktop client', async () => {
    env.desktop = true
    const wrapper = await mountLayout()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
  })

  it('keeps the desktop prompt dismissed after the user skips it', async () => {
    env.desktop = true
    localStorage.setItem(setupKey(), 'dismissed')
    const wrapper = await mountLayout()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  })
})
