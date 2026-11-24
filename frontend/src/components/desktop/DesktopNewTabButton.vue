<script setup lang="ts">
import { computed, nextTick, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { ArrowRight, Plus } from '@/components/icons'
import { WORKSPACE_HOME } from '@/types/workspaceWindows'
import { workspaceOverviewChoice, workspaceTabChoices } from './desktopTabLabels'
import './desktopTitleBarMenus.css'
import { moveMenuFocus, useDesktopTitleMenu } from './useDesktopTitleMenu'

const props = defineProps<{ workspaceId: string; disabled: boolean }>()
const emit = defineEmits<{ open: [path: string] }>()

const router = useRouter()
const { t } = useI18n()
const menuId = `new-tab-menu-${useId()}`

const choices = computed(() => (props.workspaceId ? workspaceTabChoices(props.workspaceId, router, t) : []))
const overviewChoice = computed(() => workspaceOverviewChoice(router, t))
const shortcutLabel = computed(() => (/mac/i.test(navigator.platform) ? '⌘T' : 'Ctrl+T'))

const { trigger, panel, isOpen, panelStyle, openMenu, closeMenu, toggleMenu } = useDesktopTitleMenu({
  panelWidth: 332,
})

watch(() => props.disabled, disabled => {
  if (disabled) closeMenu(false)
})

watch(() => props.workspaceId, () => {
  closeMenu(false)
})

function choose(path: string) {
  closeMenu(false)
  emit('open', path)
}

function onPanelKeydown(event: KeyboardEvent) {
  if (moveMenuFocus(panel.value, event.key, { columns: 2 })) event.preventDefault()
}

defineExpose({
  open() {
    if (props.disabled) return
    if (!props.workspaceId) {
      trigger.value?.focus()
      emit('open', WORKSPACE_HOME)
      return
    }
    openMenu()
    void nextTick(() => {
      panel.value?.querySelector<HTMLElement>('[data-menu-item]')?.focus({ preventScroll: true })
    })
  },
})
</script>

<template>
  <div class="new-tab-control">
    <button
      v-if="workspaceId"
      ref="trigger"
      class="new-tab"
      :class="{ 'is-open': isOpen }"
      type="button"
      :disabled="disabled"
      aria-haspopup="menu"
      :aria-expanded="isOpen"
      :aria-controls="isOpen ? menuId : undefined"
      :aria-label="t('desktop_tabs.new_tab')"
      :title="t('desktop_tabs.new_tab_shortcut')"
      @click="toggleMenu"
    >
      <Plus aria-hidden="true" />
    </button>
    <button
      v-else
      ref="trigger"
      class="new-tab"
      type="button"
      :disabled="disabled"
      :aria-label="t('desktop_tabs.new_tab')"
      :title="t('desktop_tabs.new_tab_shortcut')"
      @click="emit('open', WORKSPACE_HOME)"
    >
      <Plus aria-hidden="true" />
    </button>

    <Teleport to="body">
      <Transition name="desktop-menu-pop">
        <div
          v-if="workspaceId && isOpen"
          :id="menuId"
          ref="panel"
          class="desktop-titlebar-popover newtab-popover"
          role="menu"
          :aria-label="t('desktop_tabs.new_tab')"
          :style="panelStyle"
          @keydown="onPanelKeydown"
        >
          <div class="desktop-popover-header">
            <span class="desktop-popover-title">{{ t('desktop_tabs.new_tab') }}</span>
            <kbd class="desktop-popover-kbd">{{ shortcutLabel }}</kbd>
          </div>

          <div class="newtab-popover-grid">
            <button
              v-for="choice in choices"
              :key="choice.key"
              type="button"
              role="menuitem"
              data-menu-item
              class="newtab-popover-item"
              :title="choice.label"
              @click="choose(choice.path)"
            >
              <span class="newtab-popover-icon" :class="`tone-${choice.tone}`">
                <component :is="choice.icon" aria-hidden="true" />
              </span>
              <span class="newtab-popover-label">{{ choice.label }}</span>
            </button>
          </div>

          <div class="desktop-popover-footer">
            <button
              type="button"
              role="menuitem"
              data-menu-item
              class="desktop-popover-footer-btn"
              @click="choose(overviewChoice.path)"
            >
              <span class="desktop-popover-footer-icon">
                <component :is="overviewChoice.icon" aria-hidden="true" />
              </span>
              <span class="desktop-popover-footer-text">
                <span class="desktop-popover-footer-label">{{ overviewChoice.label }}</span>
              </span>
              <ArrowRight class="desktop-popover-footer-arrow" aria-hidden="true" />
            </button>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.new-tab-control {
  position: relative;
  display: flex;
  align-items: center;
  flex: none;
}

.new-tab {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: #526176;
  padding: 0;
  cursor: pointer;
  transition: background-color 140ms ease, border-color 140ms ease, color 140ms ease, box-shadow 140ms ease;
}

.new-tab:hover:not(:disabled) {
  background: #e2eaf4;
  border-color: #d3e0ee;
  color: #0369a1;
}

.new-tab.is-open:not(:disabled) {
  background: #ffffff;
  border-color: #93c5fd;
  color: #0284c7;
  box-shadow: 0 1px 3px rgba(14, 165, 233, 0.14);
}

.new-tab:disabled {
  opacity: 0.45;
  cursor: default;
}

.new-tab svg {
  width: 15px;
  height: 15px;
}

@media (prefers-reduced-motion: reduce) {
  .new-tab {
    transition: none;
  }
}
</style>
