<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Component } from 'vue'
import { ArrowLeft, ChevronLeft, ChevronRight } from '@/components/icons'

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
  <aside class="sidebar" :class="{ 'is-collapsed': isCollapsed }">
    <!-- 红框 1：导航主功能岛 -->
    <div class="sidebar-main-island" data-slot="sidebar-main">
      <div class="sidebar-header">
        <button
          v-if="showBack"
          class="back-btn"
          type="button"
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
          <slot :name="`context-${item.key}`" :collapsed="isCollapsed"></slot>
        </template>
      </nav>
    </div>

    <!-- 红框 2：导航底部设置微岛 -->
    <div v-if="footerItems.length > 0 || showToggleButton" class="sidebar-footer sidebar-bottom-island" data-slot="sidebar-bottom">
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
        type="button"
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
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-radius: 0;
  margin-right: 0;
  border: none;
  background: transparent;
  box-shadow: none;
  z-index: 10;
  transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: visible;
  flex-shrink: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  box-sizing: border-box;
}

.sidebar.is-collapsed {
  width: 60px;
}

/* 红框 1：导航主功能岛 */
.sidebar-main-island {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--color-surface-white, #ffffff);
  border-radius: 16px;
  border: 1px solid rgba(0, 0, 0, 0.06);
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
  overflow: hidden;
  transition: all 0.24s cubic-bezier(0.4, 0, 0.2, 1);
}

/* 红框 2：导航底部设置微岛 */
.sidebar-footer.sidebar-bottom-island {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex-shrink: 0;
  background: var(--color-surface-white, #ffffff);
  border-radius: 14px;
  border: 1px solid rgba(0, 0, 0, 0.06);
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
  padding: 8px 6px;
  transition: all 0.24s cubic-bezier(0.4, 0, 0.2, 1);
}

.sidebar-header {
  height: 52px;
  box-sizing: border-box;
  padding: 0 var(--space-4);
  display: flex;
  align-items: center;
  gap: var(--space-2);
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
  flex-shrink: 0;
}

.back-btn {
  background: transparent;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 0;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  transition: all var(--transition-fast);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.back-btn:hover {
  background: rgba(0, 0, 0, 0.05);
  color: var(--color-text-title);
}

.ws-name {
  font-weight: 600;
  color: var(--color-primary-900);
  font-size: 0.9375rem;
  line-height: 1.4;
  letter-spacing: -0.01em;
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
  min-height: 0;
  overflow-y: auto;
  padding: 8px 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex-grow: 1;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 0.625rem var(--space-4);
  border-radius: 10px;
  color: var(--color-text-body);
  text-decoration: none;
  font-size: 0.875rem;
  font-weight: 400;
  line-height: 1.4;
  transition: all var(--transition-fast);
  cursor: pointer;
  overflow: hidden;
  user-select: none;
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
  font-weight: 500;
}

.sidebar-footer-extra {
  display: flex;
  width: 100%;
  justify-content: center;
}

.toggle-btn {
  align-self: flex-end;
  background: transparent;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  width: 36px;
  height: 36px;
  padding: 0;
  border-radius: 10px;
  transition: all var(--transition-fast);
  margin-top: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.is-collapsed .toggle-btn {
  align-self: center;
  margin: 0 auto;
}

.toggle-btn:hover {
  background: rgba(0, 0, 0, 0.05);
  color: var(--color-primary-600);
}

.no-click {
  cursor: default;
}

.is-collapsed .nav-item {
  justify-content: center;
  width: 40px;
  height: 40px;
  padding: 0;
  margin: 0 auto;
  gap: 0;
  border-radius: 10px;
}

.is-collapsed .sidebar-header {
  justify-content: center;
  padding: 0;
}
</style>
