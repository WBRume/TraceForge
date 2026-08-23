<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Component } from 'vue'
import { ArrowLeft, ChevronLeft, ChevronRight } from 'lucide-vue-next'

export interface SidebarItem {
  key: string
  label: string
  icon?: Component
  to?: string
  active?: boolean
  noClick?: boolean
  disabled?: boolean
  title?: string
}

const props = withDefaults(defineProps<{
  title: string
  navItems: SidebarItem[]
  footerItems?: SidebarItem[]
  collapsible?: boolean
  defaultCollapsed?: boolean
  showBack?: boolean
  backTitle?: string
  showToggle?: boolean
  toggleTitle?: string
}>(), {
  footerItems: () => [],
  collapsible: true,
  defaultCollapsed: true,
  showBack: true,
  backTitle: 'Back',
  showToggle: true,
  toggleTitle: 'Toggle Sidebar',
})

const emit = defineEmits<{
  (e: 'back'): void
  (e: 'item-click', key: string): void
}>()

const isCollapsed = ref(props.defaultCollapsed)

watch(
  () => props.defaultCollapsed,
  (value) => {
    isCollapsed.value = value
  }
)

const showToggleButton = computed(() => props.collapsible && props.showToggle)

const toggleSidebar = () => {
  if (!props.collapsible) return
  isCollapsed.value = !isCollapsed.value
}

const handleItemClick = (item: SidebarItem) => {
  if (item.noClick || item.disabled) return
  emit('item-click', item.key)
}
</script>

<template>
  <aside class="sidebar glass-panel" :class="{ 'is-collapsed': isCollapsed }">
    <div class="sidebar-header">
      <button
        v-if="showBack"
        class="back-btn"
        :title="backTitle"
        @click="$emit('back')"
      >
        <ArrowLeft class="w-5 h-5" />
      </button>
      <span class="ws-name truncate sidebar-text" :class="{ 'is-hidden': isCollapsed }">{{ title }}</span>
    </div>

    <nav class="sidebar-nav">
      <template v-for="item in navItems" :key="`nav-${item.key}`">
        <router-link
          v-if="item.to"
          :to="item.to"
          class="nav-item"
          :class="{ active: item.active, 'no-click': item.noClick }"
          :title="item.title || item.label"
        >
          <component :is="item.icon" v-if="item.icon" class="w-5 h-5" />
          <span class="item-label sidebar-text" :class="{ 'is-hidden': isCollapsed }">{{ item.label }}</span>
        </router-link>

        <button
          v-else
          class="nav-item"
          type="button"
          :class="{ active: item.active, 'no-click': item.noClick }"
          :title="item.title || item.label"
          :disabled="item.disabled || item.noClick"
          @click="handleItemClick(item)"
        >
          <component :is="item.icon" v-if="item.icon" class="w-5 h-5" />
          <span class="item-label sidebar-text" :class="{ 'is-hidden': isCollapsed }">{{ item.label }}</span>
        </button>
      </template>
    </nav>

    <div v-if="footerItems.length > 0 || showToggleButton" class="sidebar-footer">
      <div v-if="$slots['footer-extra']" class="sidebar-footer-extra">
        <slot name="footer-extra"></slot>
      </div>
      <template v-for="item in footerItems" :key="`footer-${item.key}`">
        <router-link
          v-if="item.to"
          :to="item.to"
          class="nav-item"
          :class="{ active: item.active, 'no-click': item.noClick }"
          :title="item.title || item.label"
        >
          <component :is="item.icon" v-if="item.icon" class="w-5 h-5" />
          <span class="item-label sidebar-text" :class="{ 'is-hidden': isCollapsed }">{{ item.label }}</span>
        </router-link>

        <button
          v-else
          class="nav-item"
          type="button"
          :class="{ active: item.active, 'no-click': item.noClick }"
          :title="item.title || item.label"
          :disabled="item.disabled || item.noClick"
          @click="handleItemClick(item)"
        >
          <component :is="item.icon" v-if="item.icon" class="w-5 h-5" />
          <span class="item-label sidebar-text" :class="{ 'is-hidden': isCollapsed }">{{ item.label }}</span>
        </button>
      </template>

      <button
        v-if="showToggleButton"
        class="toggle-btn"
        :title="toggleTitle"
        @click="toggleSidebar"
      >
        <ChevronRight v-if="isCollapsed" class="w-5 h-5" />
        <ChevronLeft v-else class="w-5 h-5" />
      </button>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 200px;
  display: flex;
  flex-direction: column;
  border-radius: 0 var(--radius-xl) var(--radius-xl) 0;
  margin-right: var(--space-1);
  box-shadow: 2px 0 10px rgba(0,0,0,0.02);
  z-index: 10;
  transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
  flex-shrink: 0;
}

.sidebar.is-collapsed {
  width: 64px;
}

.sidebar-header {
  padding: var(--space-6) var(--space-4);
  display: flex;
  align-items: center;
  gap: var(--space-2);
  border-bottom: 1px solid rgba(0,0,0,0.05);
}

.back-btn {
  background: transparent;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 4px;
  border-radius: var(--radius-md);
  transition: all var(--transition-fast);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.back-btn:hover {
  background: rgba(0,0,0,0.05);
  color: var(--color-text-title);
}

.ws-name {
  font-weight: 600;
  color: var(--color-primary-900);
  font-size: 1rem;
}

.truncate {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sidebar-text {
  min-width: 0;
  max-width: 140px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  opacity: 1;
  transform: translateX(0);
  transition: max-width 0.24s ease, opacity 0.18s ease, transform 0.18s ease;
}

.sidebar-text.is-hidden {
  max-width: 0;
  opacity: 0;
  transform: translateX(-4px);
  pointer-events: none;
}

.sidebar-nav {
  padding: var(--space-4) var(--space-2);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  flex-grow: 1;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  color: var(--color-text-body);
  text-decoration: none;
  font-weight: 500;
  transition: all var(--transition-fast);
  cursor: pointer;
  overflow: hidden;
}

button.nav-item {
  width: 100%;
  border: none;
  background: transparent;
  text-align: left;
}

.nav-item:hover {
  background-color: var(--color-primary-50);
  color: var(--color-primary-600);
}

.nav-item.active {
  background-color: var(--color-primary-100);
  color: var(--color-primary-600);
  font-weight: 600;
}

.sidebar-footer {
  padding: var(--space-4) var(--space-2);
  border-top: 1px solid rgba(0,0,0,0.05);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.sidebar-footer-extra {
  display: flex;
  width: 100%;
}

.toggle-btn {
  align-self: flex-end;
  background: transparent;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 8px;
  border-radius: var(--radius-md);
  transition: all var(--transition-fast);
  margin-top: var(--space-2);
}

.is-collapsed .toggle-btn {
  align-self: center;
  margin-top: 0;
}

.toggle-btn:hover {
  background: rgba(0,0,0,0.05);
  color: var(--color-primary-600);
}

.no-click {
  cursor: default;
}

.is-collapsed .nav-item {
  justify-content: center;
  padding: var(--space-3) 0;
  gap: 0;
}

.is-collapsed .sidebar-header {
  justify-content: center;
  padding: var(--space-6) 0;
}
</style>
