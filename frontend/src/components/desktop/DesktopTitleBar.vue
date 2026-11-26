<script setup lang="ts">
import { computed, onMounted, onScopeDispose, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Search } from '@/components/icons'
import AppSwitcherDropdown from '@/components/AppSwitcherDropdown.vue'
import UserMenu from '@/components/user/UserMenu.vue'
import { useDesktopTabs } from '@/desktop/workspaceTabs'
import { useAuthStore } from '@/stores/auth'
import { useGlobalSearchStore } from '@/stores/globalSearch'
import { getSddDesktop } from '@/utils/runtime'
import { WORKSPACE_HOME } from '@/types/workspaceWindows'
import DesktopCaptionButtons from './DesktopCaptionButtons.vue'
import DesktopTabStrip from './DesktopTabStrip.vue'
import DesktopWorkspacePicker from './DesktopWorkspacePicker.vue'
import { describeDesktopTab } from './desktopTabLabels'

const desktop = getSddDesktop()
const windows = useDesktopTabs()!
const { state, active, enabled, failed } = windows
const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const auth = useAuthStore()
const search = useGlobalSearchStore()
const tabStrip = shallowRef<InstanceType<typeof DesktopTabStrip>>()
const icon = `${import.meta.env.BASE_URL}favicon.svg`
const workspaceId = computed(() => typeof route.params.wsId === 'string' ? route.params.wsId : '')
const tabs = computed(() => state.value?.tabs.map(tab => describeDesktopTab(tab, router, t)) ?? [])
watch(() => enabled.value && tabs.value.find(tab => tab.id === active.value?.id)?.label, label => {
  document.title = label ? `${label} — TraceForge` : 'TraceForge'
}, { immediate: true })

function error(message?: unknown) {
  if (message) console.error('Workspace title bar operation failed', message)
  ElMessage.error(t('desktop_tabs.operation_failed'))
}

function switchWorkspace(id: string) {
  if (id && id === workspaceId.value) return
  void router.push(id ? { name: 'dashboard', params: { wsId: id } } : WORKSPACE_HOME).catch(error)
}

function shortcut(event: KeyboardEvent) {
  if (!enabled.value || (!event.ctrlKey && !event.metaKey) || event.altKey || event.defaultPrevented || event.isComposing) return
  const key = event.key.toLowerCase()
  if (!['w', 't', 'tab'].includes(key) || (event.shiftKey && key !== 'tab')) return
  event.preventDefault()
  if (key === 't') tabStrip.value?.openNewTab()
  if (key === 'w' && active.value) void windows.remove(active.value.id)
  if (key === 'tab' && tabs.value.length > 1) {
    const current = tabs.value.findIndex(tab => tab.id === active.value?.id)
    const offset = event.shiftKey ? -1 : 1
    const tab = tabs.value[(current + offset + tabs.value.length) % tabs.value.length]
    if (tab) void windows.select(tab.id)
  }
}

function openLink(event: MouseEvent) {
  if (!enabled.value || event.defaultPrevented || event.shiftKey || event.altKey
    || (event.type === 'click' ? !event.ctrlKey && !event.metaKey : event.button !== 1)) return
  const link = (event.target as Element)?.closest?.('a[href]') as HTMLAnchorElement | null
  if (!link || link.hasAttribute('download')) return
  const url = new URL(link.href)
  if (url.origin !== location.origin || url.pathname !== location.pathname || !url.hash.startsWith('#/')) return
  const path = url.hash.slice(1)
  if (!router.resolve(path).meta.requiresAuth) return
  event.preventDefault()
  event.stopImmediatePropagation()
  void windows.open(path)
}

watch(failed, () => error())
onMounted(() => {
  window.addEventListener('keydown', shortcut)
  document.addEventListener('click', openLink, true)
  document.addEventListener('auxclick', openLink, true)
})
onScopeDispose(() => {
  window.removeEventListener('keydown', shortcut)
  document.removeEventListener('click', openLink, true)
  document.removeEventListener('auxclick', openLink, true)
})
</script>

<template>
  <header class="desktop-titlebar">
    <div class="desktop-brand desktop-drag-region" data-tauri-drag-region title="TraceForge">
      <router-link v-if="auth.isAuthenticated" to="/" class="desktop-home" :title="t('common.home')">
        <img :src="icon" alt="" draggable="false" />
        <span>TraceForge</span>
      </router-link>
      <template v-else>
        <img :src="icon" alt="" draggable="false" />
        <span>TraceForge</span>
      </template>
    </div>
    <AppSwitcherDropdown v-if="auth.isAuthenticated" compact />
    <div v-if="state" class="workspace-switcher">
      <DesktopWorkspacePicker :workspace-id="workspaceId" @select="switchWorkspace" />
    </div>
    <DesktopTabStrip v-if="enabled && active" ref="tabStrip" :api="windows.api" :tabs="tabs" :active-id="active.id" :workspace-id="workspaceId"
      @open="windows.open" @select="windows.select" @close="windows.remove"
      @move="windows.remove" @error="error" />
    <div v-else class="desktop-drag-region empty-titlebar" data-tauri-drag-region aria-hidden="true"></div>
    <button v-if="search.enabled" class="titlebar-search" type="button" :title="t('desktop_tabs.search_shortcut')"
      :aria-label="t('desktop_tabs.search')" @click="search.openSearch()">
      <Search aria-hidden="true" />
      <span>{{ t('desktop_tabs.search') }}</span>
      <kbd>Shift × 2</kbd>
    </button>
    <UserMenu
      v-if="auth.isAuthenticated"
      class="titlebar-user"
      :display-name="auth.user?.display_name"
      :email="auth.user?.email"
      :user-id="auth.user?.id"
      :avatar-svg="auth.user?.avatar_svg"
      :avatar-url="auth.user?.avatar_url"
      size="sm"
      variant="titlebar"
    />
    <DesktopCaptionButtons v-if="desktop?.runtime === 'tauri'" :api="windows.api" @error="error" />
    <div v-else class="caption-reserve" aria-hidden="true"></div>
  </header>
</template>

<style scoped src="./desktopWindowChrome.css"></style>
<style scoped>
.desktop-home { display: flex; align-items: center; gap: 8px; height: 29px; text-decoration: none; color: inherit; border-radius: 5px; -webkit-app-region: no-drag; app-region: no-drag; }
.desktop-home:hover { color: #0369a1; }
.desktop-home:focus-visible { outline: 2px solid #0284c7; outline-offset: 2px; }
.workspace-switcher { flex: none; border-right: 1px solid #e2e8f0; padding-right: 7px; }
.titlebar-user { flex: none; -webkit-app-region: no-drag; app-region: no-drag; }
.titlebar-search { flex: none; display: flex; height: 29px; align-items: center; gap: 7px; border: 1px solid #e2e8f0; border-radius: 8px; padding: 0 8px; font-size: 12px; color: #475569; background: #ffffff; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03); transition: background-color 140ms, border-color 140ms, color 140ms; }
.titlebar-search:hover { background: #ffffff; border-color: #bae6fd; color: #0f172a; }
.titlebar-search svg { width: 15px; height: 15px; }
.titlebar-search kbd { margin-left: 6px; padding: 2px 4px; border: 1px solid #e2e8f0; border-radius: 4px; background: #f8fafc; color: #64748b; font: 10px 'Segoe UI', sans-serif; }
@media (max-width: 850px) { .titlebar-search kbd { display: none; } }
@media (prefers-reduced-motion: reduce) { .titlebar-search { transition: none; } }
</style>
