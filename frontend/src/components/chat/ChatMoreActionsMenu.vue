<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  BarChart3,
  Download,
  MoreHorizontal,
  Search,
  Share2,
} from 'lucide-vue-next'
import { useGlobalSearchStore } from '@/stores/globalSearch'

/**
 * 会话头部「更多操作」下拉树按钮：导出 / 归因分析 / 全局搜索 / 分享会话。
 * 每个条目的可用性由父级传入的 props 控制；点击后统一收起菜单。
 */
const props = defineProps<{
  canExport: boolean
  canShare: boolean
  showAttribution: boolean
  attributionActive: boolean
}>()

const emit = defineEmits<{
  (e: 'export'): void
  (e: 'open-attribution'): void
  (e: 'share'): void
}>()

const { t } = useI18n()
const searchStore = useGlobalSearchStore()

const menuOpen = ref(false)
const rootRef = ref<HTMLElement | null>(null)
const triggerRef = ref<HTMLElement | null>(null)

const panelStyle = computed(() => {
  const el = triggerRef.value
  if (!el) return undefined
  const rect = el.getBoundingClientRect()
  return {
    position: 'fixed' as const,
    top: `${Math.round(rect.bottom + 6)}px`,
    // 右对齐触发器；面板不会超出视口右缘（触发器在最右侧）
    left: `${Math.round(Math.max(rect.right - 180, 8))}px`,
  }
})

const menuItems = computed(() => {
  const items: Array<{
    key: string
    label: string
    icon: typeof Download
    visible: boolean
    disabled: boolean
    handler: () => void
  }> = [
    {
      key: 'export',
      label: t('chat.more_export'),
      icon: Download,
      visible: true,
      disabled: !props.canExport,
      handler: () => emit('export'),
    },
    {
      key: 'attribution',
      label: t('chat.more_attribution'),
      icon: BarChart3,
      visible: props.showAttribution,
      disabled: false,
      handler: () => emit('open-attribution'),
    },
    {
      key: 'search',
      label: t('chat.more_search'),
      icon: Search,
      visible: searchStore.enabled,
      disabled: false,
      handler: () => searchStore.openSearch(),
    },
    {
      key: 'share',
      label: t('chat.more_share'),
      icon: Share2,
      visible: true,
      disabled: !props.canShare,
      handler: () => emit('share'),
    },
  ]
  return items.filter((item) => item.visible)
})

const toggleMenu = () => {
  menuOpen.value = !menuOpen.value
}

const closeMenu = () => {
  menuOpen.value = false
}

const handleItemClick = (item: (typeof menuItems.value)[number]) => {
  if (item.disabled) return
  closeMenu()
  item.handler()
}

const handleDocClick = (event: MouseEvent) => {
  if (rootRef.value && !rootRef.value.contains(event.target as Node)) {
    closeMenu()
  }
}

onMounted(() => document.addEventListener('pointerdown', handleDocClick))
onBeforeUnmount(() => document.removeEventListener('pointerdown', handleDocClick))
</script>

<template>
  <div ref="rootRef" class="more-actions-menu">
    <button
      ref="triggerRef"
      type="button"
      class="icon-btn more-actions-trigger"
      :class="{ 'is-open': menuOpen, 'has-active': attributionActive }"
      :title="$t('chat.more_actions_title')"
      :aria-expanded="menuOpen"
      aria-haspopup="menu"
      @click="toggleMenu"
    >
      <MoreHorizontal class="w-4 h-4" />
    </button>

    <!-- header-actions 有 overflow-x: auto，面板 Teleport 到 body 并按触发器定位 -->
    <Teleport to="body">
      <transition name="more-menu-fade">
        <div
          v-if="menuOpen"
          class="more-actions-panel"
          :style="panelStyle"
          role="menu"
        >
          <button
            v-for="item in menuItems"
            :key="item.key"
            type="button"
            class="more-actions-item"
            :class="{ 'is-disabled': item.disabled, 'is-active': item.key === 'attribution' && attributionActive }"
            role="menuitem"
            :disabled="item.disabled"
            @click="handleItemClick(item)"
          >
            <component :is="item.icon" class="w-4 h-4 item-icon" />
            <span class="item-label">{{ item.label }}</span>
            <span
              v-if="item.key === 'attribution' && attributionActive"
              class="item-active-dot"
            ></span>
          </button>
        </div>
      </transition>
    </Teleport>
  </div>
</template>

<style scoped>
.more-actions-menu {
  position: relative;
  flex-shrink: 0;
}

/* 自足样式：ChatView 的 .icon-btn 是 scoped 样式，覆盖不到子组件内部，
   这里按 .icon-btn（chat-view-layout.css:344）同规格实现 */
.more-actions-trigger {
  background: transparent;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 6px;
  border-radius: var(--radius-md);
  transition: all 0.2s;
  display: flex;
  align-items: center;
  line-height: 1;
}

/* w-4/h-4 工具类同样定义在 ChatView scoped 样式里，作用域到不了子组件
   （面板还 Teleport 到 body），这里显式按 16px 与邻居按钮图标对齐 */
.more-actions-trigger svg {
  width: 16px;
  height: 16px;
}

.more-actions-trigger:hover {
  background-color: rgba(0, 0, 0, 0.05);
}

.more-actions-trigger.is-open {
  color: var(--color-primary-600);
  background-color: var(--color-primary-50);
}

.more-actions-trigger.has-active {
  color: var(--color-primary-600);
}

.more-actions-panel {
  min-width: 180px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.12);
  padding: 6px;
  z-index: 300;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.more-actions-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: #334155;
  font-size: 0.8125rem;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.more-actions-item:hover:not(.is-disabled) {
  background: #f1f5f9;
  color: #0f172a;
}

.more-actions-item.is-disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.more-actions-item.is-active {
  color: #0ea5e9;
}

.item-icon {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  color: #64748b;
}

.more-actions-item:hover:not(.is-disabled) .item-icon,
.more-actions-item.is-active .item-icon {
  color: #0ea5e9;
}

.item-label {
  flex: 1;
  white-space: nowrap;
}

.item-active-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #0ea5e9;
  flex-shrink: 0;
}

.more-menu-fade-enter-active,
.more-menu-fade-leave-active {
  transition: opacity 0.12s ease, transform 0.12s ease;
}

.more-menu-fade-enter-from,
.more-menu-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
