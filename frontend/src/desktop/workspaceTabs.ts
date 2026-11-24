import { computed, inject, shallowRef, watch } from 'vue'
import type { InjectionKey } from 'vue'
import { isNavigationFailure, NavigationFailureType } from 'vue-router'
import type { Router } from 'vue-router'
import type { useAuthStore } from '@/stores/auth'
import { getApiServerUrl, setApiServerUrl } from '@/utils/api'
import { isWorkspaceTabPath, WORKSPACE_HOME, WORKSPACE_TAB_LIMIT } from '@/types/workspaceWindows'
import type { DesktopWorkspaceWindowsApi, TabDestination, WindowCommand, WorkspaceWindowState } from '@/types/workspaceWindows'

export const desktopTabsKey: InjectionKey<ReturnType<typeof createDesktopTabs>> = Symbol('desktop-workspace-tabs')
export const useDesktopTabs = () => inject(desktopTabsKey, null)

export function useWorkspaceTabTitle(title: () => string | undefined) {
  const tabs = useDesktopTabs()
  if (tabs) watch(() => [tabs.active.value?.id, tabs.active.value?.path, title()] as const, ([, , name]) => {
    if (name) tabs.setTitle(name)
  }, { immediate: true, flush: 'post' })
}

export function createDesktopTabs(api: DesktopWorkspaceWindowsApi, router: Router, auth: ReturnType<typeof useAuthStore>) {
  const state = shallowRef<WorkspaceWindowState | null>(null)
  const failed = shallowRef(0)
  const server = shallowRef(getApiServerUrl())
  const active = computed(() => state.value?.tabs.find(tab => tab.id === state.value?.activeTabId))
  const enabled = computed(() => !!state.value && isWorkspaceTabPath(router.currentRoute.value.fullPath) && !!router.currentRoute.value.meta.requiresAuth)
  const scope = computed(() => auth.token && auth.user?.id ? JSON.stringify([server.value, auth.user.id]) : null)
  let tail = Promise.resolve()
  let routing = false
  let disposed = false
  let connectedScope: string | null | undefined

  function accept(snapshot: WorkspaceWindowState | null) {
    if (!snapshot || !scope.value || snapshot.scope !== scope.value) return
    if (!state.value || snapshot.revision >= state.value.revision) state.value = snapshot
  }

  function report(error: unknown) {
    if (disposed) return
    console.error('Workspace window operation failed', error)
    failed.value++
  }

  function enqueue(operation: () => Promise<void>) {
    const result = tail.then(() => disposed ? undefined : operation())
    tail = result.catch(report)
    return tail
  }

  function routable(path: string) {
    return isWorkspaceTabPath(path) && !!router.resolve(path).meta.requiresAuth
  }

  async function routeTo(path: string) {
    const failure = await router.replace(routable(path) ? path : WORKSPACE_HOME)
    return !failure || isNavigationFailure(failure, NavigationFailureType.duplicated)
  }

  async function syncRoute() {
    const path = router.currentRoute.value.fullPath
    const tab = active.value
    if (!tab || tab.path === path || !routable(path)) return
    accept(await api.command({ type: 'navigate', tabId: tab.id, path }))
  }

  async function connect(nextScope: string | null) {
    if (nextScope !== scope.value || nextScope === connectedScope) return
    const path = router.currentRoute.value.fullPath
    const snapshot = await api.command({ type: 'connect', scope: nextScope, path: routable(path) ? path : WORKSPACE_HOME })
    if (disposed || nextScope !== scope.value) return
    connectedScope = nextScope
    if (!snapshot) return
    accept(snapshot)
    if (!active.value) return
    routing = true
    try {
      await routeTo(active.value.path)
      await syncRoute()
    } finally {
      routing = false
    }
  }

  async function change(command: WindowCommand, path?: string) {
    const previous = router.currentRoute.value.fullPath
    const owner = scope.value
    routing = true
    try {
      if (path && !await routeTo(path)) return
      if (scope.value !== owner || !state.value) return
      accept(await api.command(command))
      await syncRoute()
    } catch (error) {
      if (path && scope.value === owner && router.currentRoute.value.fullPath !== previous) await router.replace(previous)
      throw error
    } finally {
      routing = false
    }
  }

  function select(id: string) {
    return enqueue(async () => {
      const tab = state.value?.tabs.find(tab => tab.id === id)
      if (tab && (active.value?.id !== id || !enabled.value)) await change({ type: 'select', tabId: id }, tab.path)
    })
  }

  function open(path: string) {
    return enqueue(async () => {
      if (!state.value || state.value.tabs.length >= WORKSPACE_TAB_LIMIT) return
      if (routable(path)) await change({ type: 'open', path }, path)
    })
  }

  function remove(id: string, destination?: TabDestination) {
    return enqueue(async () => {
      const window = state.value
      if (!window) return
      const index = window.tabs.findIndex(tab => tab.id === id)
      if (index === -1) return
      const reorder = destination && 'windowId' in destination && destination.windowId === window.id
      const replacement = !reorder && window.activeTabId === id ? (window.tabs[index + 1] ?? window.tabs[index - 1])?.path ?? WORKSPACE_HOME : undefined
      const action: WindowCommand = destination ? { type: 'move', tabId: id, destination } : { type: 'close', tabId: id }
      await change(action, replacement)
    })
  }

  const stopUpdate = api.onUpdate(({ state: snapshot, receivedTabId }) => {
    accept(snapshot)
    if (receivedTabId && snapshot.scope === scope.value) void select(receivedTabId)
  })
  const stopScope = watch(scope, nextScope => {
    state.value = null
    connectedScope = undefined
    void enqueue(() => connect(nextScope))
  })
  const stopRoute = router.afterEach((_to, _from, failure) => {
    if (!failure && !routing) void syncRoute().catch(report)
  })
  const onServerChange = () => { server.value = getApiServerUrl() }
  const onStorage = (event: StorageEvent) => {
    if (event.key === 'sdd_server_url' && event.newValue && event.newValue !== getApiServerUrl()) setApiServerUrl(event.newValue, false)
    if (event.key !== 'sdd_token' || auth.token === event.newValue) return
    auth.adoptToken(event.newValue)
    if (auth.token) void auth.fetchCurrentUser()
    else void router.replace('/').catch(report)
  }
  window.addEventListener('sdd-server-changed', onServerChange)
  window.addEventListener('storage', onStorage)

  return {
    api, state: computed(() => state.value), active, enabled, failed, select, open, remove,
    async start() {
      if (auth.token && !auth.user) await auth.fetchCurrentUser()
      await enqueue(() => connect(scope.value))
    },
    setTitle(title: string) {
      const tab = active.value
      const path = router.currentRoute.value.fullPath
      if (tab?.path === path && tab.title !== title && scope.value) {
        void api.command({ type: 'title', tabId: tab.id, path, title }).then(accept).catch(report)
      }
    },
    stop() {
      disposed = true
      stopUpdate()
      stopScope()
      stopRoute()
      window.removeEventListener('sdd-server-changed', onServerChange)
      window.removeEventListener('storage', onStorage)
    },
  }
}
