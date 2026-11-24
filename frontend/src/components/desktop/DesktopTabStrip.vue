<script setup lang="ts">
import { nextTick, onMounted, onScopeDispose, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ExternalLink, X } from '@/components/icons'
import type { DesktopWorkspaceWindowsApi, TabDestination } from '@/types/workspaceWindows'
import { MAIN_WORKSPACE_WINDOW, WORKSPACE_TAB_LIMIT } from '@/types/workspaceWindows'
import type { DesktopTab } from './desktopTabLabels'
import DesktopNewTabButton from './DesktopNewTabButton.vue'
import { useDesktopTabDrag } from './useDesktopTabDrag'

const props = defineProps<{ api: DesktopWorkspaceWindowsApi; tabs: DesktopTab[]; activeId: string; workspaceId: string }>()
const emit = defineEmits<{
  select: [id: string]; close: [id: string]; open: [path: string]; move: [id: string, destination: TabDestination]; error: [error: unknown]
}>()
const { t } = useI18n()
const strip = shallowRef<HTMLElement>()
const scroller = shallowRef<HTMLElement>()
const newTabButton = shallowRef<InstanceType<typeof DesktopNewTabButton>>()
const menu = shallowRef<{ id: string; x: number; y: number }>()
const menuContent = shallowRef<HTMLElement>()
const { draggingId, windowGrip, hint, start, update, finish, wasDragged } = useDesktopTabDrag(props.api,
  (id, destination) => emit('move', id, destination), error => emit('error', error))

defineExpose({ openNewTab: () => newTabButton.value?.open() })

let boundsFrame = 0
const tabButtons = () => Array.from(strip.value?.querySelectorAll<HTMLButtonElement>('[data-tab-id]') ?? [])
const tabButton = (id: string) => tabButtons().find(button => button.dataset.tabId === id)

function publishBounds() {
  cancelAnimationFrame(boundsFrame)
  boundsFrame = requestAnimationFrame(() => {
    const rect = strip.value?.getBoundingClientRect()
    if (!rect || !rect.width || !rect.height) return
    const tabs = tabButtons().map(button => {
      const row = button.parentElement!.getBoundingClientRect()
      return { id: button.dataset.tabId!, midpoint: row.left + row.width / 2 }
    })
    void props.api.setStrip({ x: rect.x, y: rect.y, width: rect.width, height: rect.height, tabs }).catch(console.error)
  })
}

function select(id: string) {
  if (!wasDragged(id)) emit('select', id)
}

function tabKey(event: KeyboardEvent, id: string, index: number) {
  const last = props.tabs.length - 1
  let next: number
  switch (event.key) {
    case 'ArrowLeft': next = index === 0 ? last : index - 1; break
    case 'ArrowRight': next = index === last ? 0 : index + 1; break
    case 'Home': next = 0; break
    case 'End': next = last; break
    case 'Delete': event.preventDefault(); emit('close', id); return
    case 'F10': {
      if (!event.shiftKey) return
      event.preventDefault()
      const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
      void showMenu(id, rect.left, rect.bottom)
      return
    }
    default: return
  }
  event.preventDefault()
  const tab = props.tabs[next]
  if (tab) {
    tabButton(tab.id)?.focus()
    emit('select', tab.id)
  }
}

function scrollTabs(event: WheelEvent) {
  const element = scroller.value
  if (!element || element.scrollWidth <= element.clientWidth || Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return
  event.preventDefault()
  element.scrollLeft += event.deltaY
}

async function showMenu(id: string, x: number, y: number) {
  menu.value = { id, x: Math.min(x, window.innerWidth - 208), y: Math.max(y, 38) }
  await nextTick()
  menuContent.value?.querySelector<HTMLButtonElement>('button')?.focus()
}

function dismissMenu(event?: PointerEvent) {
  if (!event || !menuContent.value?.contains(event.target as Node)) menu.value = undefined
}
const onBlur = () => dismissMenu()

function menuKey(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    if (menu.value) tabButton(menu.value.id)?.focus()
    dismissMenu()
  } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    const buttons = Array.from(menuContent.value?.querySelectorAll<HTMLButtonElement>('button') ?? [])
    const index = buttons.findIndex(button => button === document.activeElement)
    buttons[(index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length]?.focus()
  }
}

function menuAction(action: 'detach' | 'merge' | 'close') {
  const id = menu.value?.id
  dismissMenu()
  if (!id) return
  if (action === 'close') emit('close', id)
  else emit('move', id, action === 'merge' ? { windowId: MAIN_WORKSPACE_WINDOW } : {})
}

const resize = new ResizeObserver(publishBounds)
onMounted(() => {
  if (strip.value) resize.observe(strip.value)
  publishBounds()
  window.addEventListener('pointerdown', dismissMenu, true)
  window.addEventListener('blur', onBlur)
})
watch(() => [props.tabs, props.activeId] as const, ([, next], [, previous]) => {
  if (next !== previous) tabButton(next)?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  publishBounds()
}, { flush: 'post' })
onScopeDispose(() => {
  resize.disconnect()
  cancelAnimationFrame(boundsFrame)
  window.removeEventListener('pointerdown', dismissMenu, true)
  window.removeEventListener('blur', onBlur)
  void props.api.setStrip(null).catch(console.error)
})
</script>

<template>
  <div ref="strip" class="tab-strip" :class="{ 'has-drop-hint': hint, 'is-dragging': draggingId }">
    <div class="tab-drag-edge" data-tauri-drag-region aria-hidden="true"></div>
    <div ref="scroller" class="tab-scroll" role="tablist" :aria-label="t('desktop_tabs.tabs')" @scroll="publishBounds" @wheel="scrollTabs">
      <div v-for="(tab, index) in tabs" :key="tab.id" class="desktop-tab" role="presentation"
        :class="{ 'is-active': tab.id === activeId, 'is-grabbed': tab.id === draggingId, 'is-window-grip': tab.id === windowGrip, 'drop-before': hint?.beforeTabId === tab.id }"
        @contextmenu.prevent="showMenu(tab.id, $event.clientX, $event.clientY)"
        @auxclick.middle.prevent="emit('close', tab.id)">
        <button class="tab-label" type="button" role="tab" :data-tab-id="tab.id" aria-controls="desktop-workspace-panel"
          :aria-selected="tab.id === activeId" :tabindex="tab.id === activeId ? 0 : -1" :title="`${tab.label}\n${t('desktop_tabs.hold_to_move_window')}`"
          @click="select(tab.id)" @keydown="tabKey($event, tab.id, index)"
          @pointerdown="start($event, tab.id)" @pointermove="update" @pointerup="finish(true, $event)"
          @pointercancel="finish(false, $event)" @lostpointercapture="finish(false, $event)">
          <component :is="tab.icon" class="tab-icon" aria-hidden="true" />
          <span>{{ tab.label }}</span>
        </button>
        <button class="tab-close" type="button" tabindex="-1" :aria-label="t('desktop_tabs.close_named', { name: tab.label })"
          :title="t('desktop_tabs.close_tab')" @click="emit('close', tab.id)">
          <X aria-hidden="true" />
        </button>
      </div>
    </div>
    <DesktopNewTabButton ref="newTabButton" :workspace-id="workspaceId" :disabled="tabs.length >= WORKSPACE_TAB_LIMIT"
      :class="{ 'drop-before': hint && !hint.beforeTabId }" @open="emit('open', $event)" />
    <div class="tab-spacer" data-tauri-drag-region aria-hidden="true"></div>
    <Teleport to="body">
      <div v-if="menu" ref="menuContent" class="desktop-tab-menu" role="menu" :aria-label="t('desktop_tabs.tabs')"
        :style="{ left: `${menu.x}px`, top: `${menu.y}px` }" @keydown="menuKey">
        <button type="button" role="menuitem" @click="menuAction('detach')"><ExternalLink />{{ t('desktop_tabs.detach') }}</button>
        <button v-if="!api.isPrimary" type="button" role="menuitem" @click="menuAction('merge')"><component :is="ExternalLink" class="return-icon" />{{ t('desktop_tabs.merge') }}</button>
        <button type="button" role="menuitem" @click="menuAction('close')"><X />{{ t('desktop_tabs.close_tab') }}</button>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.tab-strip { position: relative; flex: 1; display: flex; align-items: center; min-width: 0; gap: 5px; align-self: stretch; }
.tab-drag-edge { position: absolute; inset: 0 0 auto; height: 6px; }
.tab-drag-edge, .tab-spacer { -webkit-app-region: drag; app-region: drag; }
.tab-scroll { display: flex; align-items: center; gap: 3px; padding: 2px; overflow-x: auto; min-width: 0; scrollbar-width: none; }
.tab-scroll::-webkit-scrollbar { display: none; }
.desktop-tab {
  position: relative;
  flex: 0 0 clamp(112px, 12vw, 180px);
  display: flex;
  align-items: center;
  height: 32px;
  padding-right: 4px;
  border: 1px solid transparent;
  border-radius: 7px;
  color: #526176;
  transition: background-color 130ms ease, border-color 130ms ease, opacity 130ms ease;
}
.desktop-tab:hover { background: #e2eaf4; }
.desktop-tab.is-active { color: #182e45; background: #fff; border-color: #d9e4ef; box-shadow: 0 1px 2px #1536510d; }
.desktop-tab.is-active::after { content: ''; position: absolute; bottom: -1px; left: 10px; right: 10px; height: 2px; border-radius: 2px; background: var(--color-primary-500); pointer-events: none; }
.desktop-tab.is-grabbed { opacity: .42; }
.is-dragging .tab-label, .is-window-grip .tab-label { cursor: grabbing; }
.tab-label, .tab-close { border: 0; background: transparent; color: inherit; }
.tab-label { display: flex; flex: 1; min-width: 0; align-items: center; gap: 7px; text-align: left; height: 100%; padding: 0 3px 0 9px; border-radius: 6px; font-size: 12px; font-weight: 550; touch-action: none; }
.tab-label span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tab-icon { width: 15px; height: 15px; flex: none; }
.is-active .tab-icon { color: var(--color-primary-600); }
.tab-close { position: relative; display: grid; place-items: center; flex: none; border-radius: 5px; }
.tab-close { width: 21px; height: 22px; padding: 0; color: #64748b; opacity: .62; }
.tab-close:hover, .tab-close:focus-visible { opacity: 1; background: #e3ebf4; color: #1e293b; }
.tab-close svg { width: 13px; height: 13px; }
.drop-before::before { content: ''; position: absolute; z-index: 1; left: -3px; top: 2px; bottom: 2px; width: 3px; border-radius: 2px; background: var(--color-primary-500); pointer-events: none; }
.has-drop-hint .tab-spacer { background: #dcebf9; }
.tab-spacer { flex: 1; min-width: 26px; align-self: stretch; }
.desktop-tab-menu { position: fixed; z-index: 2400; min-width: 184px; padding: 4px; border: 1px solid #dce6ef; border-radius: 8px; background: #fff; box-shadow: 0 8px 26px #182e4524; }
.desktop-tab-menu button { display: flex; align-items: center; text-align: left; gap: 9px; width: 100%; padding: 7px 9px; border: 0; border-radius: 5px; color: #334155; background: transparent; font-size: 12.5px; }
.desktop-tab-menu button:hover, .desktop-tab-menu button:focus-visible { background: #edf5fc; color: #0c4a6e; }
.desktop-tab-menu svg { width: 15px; height: 15px; flex: none; }
.return-icon { transform: scaleX(-1); }
@media (prefers-reduced-motion: reduce) { .desktop-tab { transition: none; } }
</style>
