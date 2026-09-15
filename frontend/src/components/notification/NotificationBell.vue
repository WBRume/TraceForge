<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, useTemplateRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Bell } from 'lucide-vue-next'
import { useNotificationStore } from '@/stores/notification'
import type { AppNotificationItem } from '@/stores/notification'
import { resolveNotificationTarget } from '@/components/notification/registry'
import NotificationPopover from '@/components/notification/NotificationPopover.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const store = useNotificationStore()

const popoverOpen = ref(false)
const popoverStyle = ref<Record<string, string>>({})

// 弹层 Teleport 到 body 并用 fixed 定位锚定在铃铛右侧:
// 侧栏容器 overflow: hidden,absolute 定位会被裁剪在侧栏区域内
const bellButtonRef = useTemplateRef<HTMLButtonElement>('bellButton')
const popoverRef = useTemplateRef<HTMLElement>('popoverRoot')

const hasUnread = computed(() => store.unreadCount > 0)
const unreadBadgeText = computed(() => (store.unreadCount > 99 ? '99+' : String(store.unreadCount)))

const updatePosition = () => {
  const rect = bellButtonRef.value?.getBoundingClientRect()
  if (!rect) return
  const left = rect.right + 8
  popoverStyle.value = {
    position: 'fixed',
    left: `${Math.max(left, 8)}px`,
    bottom: `${Math.max(window.innerHeight - rect.top + 6, 8)}px`,
    width: '320px',
    maxWidth: `min(320px, calc(100vw - ${Math.max(left, 8)}px - 16px))`,
    zIndex: '1200',
  }
}

const togglePopover = async () => {
  popoverOpen.value = !popoverOpen.value
  if (popoverOpen.value) {
    updatePosition()
    await store.fetchList()
    void store.refreshUnreadCount()
  }
}

const closePopover = () => {
  popoverOpen.value = false
}

const handleConsume = (item: AppNotificationItem) => {
  closePopover()
  void store.removeItem(item.id)
  const target = resolveNotificationTarget(item)
  if (target && route.path !== target) {
    router.push(target)
  }
}

const handleRemove = (id: string) => {
  void store.removeItem(id)
}

const handleReadAll = () => {
  void store.markAllRead()
}

const handleClearAll = () => {
  void store.clearAll()
}

const onPointerDown = (event: PointerEvent) => {
  const target = event.target as Node
  if (bellButtonRef.value?.contains(target) || popoverRef.value?.contains(target)) return
  closePopover()
}

const onKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape') closePopover()
}

const onResize = () => {
  if (popoverOpen.value) updatePosition()
}

watch(popoverOpen, (open) => {
  if (open) {
    document.addEventListener('pointerdown', onPointerDown, true)
    document.addEventListener('keydown', onKeydown, true)
    window.addEventListener('resize', onResize)
  } else {
    document.removeEventListener('pointerdown', onPointerDown, true)
    document.removeEventListener('keydown', onKeydown, true)
    window.removeEventListener('resize', onResize)
  }
})

onMounted(() => {
  store.start()
})

onUnmounted(() => {
  store.stop()
  document.removeEventListener('pointerdown', onPointerDown, true)
  document.removeEventListener('keydown', onKeydown, true)
  window.removeEventListener('resize', onResize)
})
</script>

<template>
  <div class="notification-bell-wrap">
    <button
      ref="bellButton"
      type="button"
      class="notification-nav-item"
      :title="t('notification.title')"
      @click="togglePopover"
    >
      <span class="bell-icon-wrap">
        <Bell class="w-5 h-5" />
        <span v-if="hasUnread" class="unread-dot">{{ unreadBadgeText }}</span>
      </span>
      <span class="notification-nav-label">{{ $t('notification.title') }}</span>
      <span v-if="hasUnread" class="unread-pill">{{ unreadBadgeText }}</span>
    </button>

    <Teleport to="body">
      <Transition name="notif-pop">
        <div v-if="popoverOpen" ref="popoverRoot" class="notification-popover-anchor" :style="popoverStyle">
          <NotificationPopover
            :items="store.items"
            :loading="store.loading"
            @consume="handleConsume"
            @remove="handleRemove"
            @mark-all-read="handleReadAll"
            @clear-all="handleClearAll"
          />
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.notification-bell-wrap {
  display: flex;
  width: 100%;
  position: relative;
}

/* 与 AppSidebar .nav-item 完全同规格:尺寸/内边距/颜色/交互一致 */
.notification-nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  color: var(--color-text-body);
  font-weight: 500;
  font-size: 0.9375rem;
  transition: all var(--transition-fast);
  cursor: pointer;
  overflow: hidden;
  width: 100%;
  border: none;
  background: transparent;
  text-align: left;
}

.notification-nav-item:hover {
  background-color: var(--color-primary-50);
  color: var(--color-primary-600);
}

.bell-icon-wrap {
  position: relative;
  display: inline-flex;
  flex: 0 0 auto;
}

.unread-dot {
  display: none;
}

.unread-pill {
  margin-left: auto;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: var(--radius-full);
  background: #FEE2E2;
  color: #B91C1C;
  font-size: 0.66rem;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
}

.notification-nav-label {
  min-width: 0;
  max-width: 140px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: max-width 0.24s ease, opacity 0.18s ease;
}

.notif-pop-enter-active,
.notif-pop-leave-active {
  transition: opacity 0.16s ease, transform 0.16s ease;
}

.notif-pop-enter-from,
.notif-pop-leave-to {
  opacity: 0;
  transform: translateX(-8px);
}
</style>

<!-- 非 scoped:跟随侧栏折叠态(.sidebar.is-collapsed 由 AppSidebar 控制) -->
<style>
.sidebar.is-collapsed .notification-nav-item {
  justify-content: center;
  padding: var(--space-3) 0;
  gap: 0;
}

.sidebar.is-collapsed .notification-nav-label {
  max-width: 0;
  opacity: 0;
  pointer-events: none;
}

.sidebar.is-collapsed .unread-pill {
  display: none;
}

.sidebar.is-collapsed .unread-dot {
  display: inline-flex;
  position: absolute;
  top: -4px;
  right: -6px;
  min-width: 15px;
  height: 15px;
  padding: 0 4px;
  border-radius: var(--radius-full);
  background: #EF4444;
  color: #fff;
  font-size: 0.58rem;
  font-weight: 700;
  align-items: center;
  justify-content: center;
  box-shadow: 0 0 0 2px var(--color-bg-base);
}
</style>
