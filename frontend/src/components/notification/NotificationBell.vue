<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Bell, CheckCheck } from 'lucide-vue-next'
import { useNotificationStore } from '@/stores/notification'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const store = useNotificationStore()

const popoverOpen = ref(false)

onMounted(() => {
  store.start()
})

onUnmounted(() => {
  store.stop()
})

const hasUnread = computed(() => store.unreadCount > 0)
const unreadBadgeText = computed(() => (store.unreadCount > 99 ? '99+' : String(store.unreadCount)))

const togglePopover = async () => {
  popoverOpen.value = !popoverOpen.value
  if (popoverOpen.value) {
    await store.fetchList()
    void store.refreshUnreadCount()
  }
}

const handleReadAll = async () => {
  await store.markAllRead()
}

const formatTime = (iso: string | null): string => {
  if (!iso) return ''
  const date = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return t('notification.just_now')
  if (diffMin < 60) return t('notification.minutes_ago', { n: diffMin })
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return t('notification.hours_ago', { n: diffHour })
  return date.toLocaleDateString()
}

const handleItemClick = async (item: any) => {
  await store.markRead(item.id)
  popoverOpen.value = false
  const payload = item.payload || {}
  const taskId = String(payload.task_id || '')
  const workspaceId = String(payload.workspace_id || '')
  if (taskId && workspaceId) {
    const target = `/ws/${workspaceId}/chat/${taskId}`
    if (route.path !== target) {
      router.push(target)
    }
  }
}
</script>

<template>
  <div class="notification-bell-wrap">
    <button
      type="button"
      class="notification-nav-item"
      :title="$t('notification.title')"
      @click="togglePopover"
    >
      <span class="bell-icon-wrap">
        <Bell class="w-5 h-5" />
        <span v-if="hasUnread" class="unread-dot">{{ unreadBadgeText }}</span>
      </span>
      <span class="notification-nav-label">{{ $t('notification.title') }}</span>
      <span v-if="hasUnread" class="unread-pill">{{ unreadBadgeText }}</span>
    </button>

    <Transition name="notif-pop">
      <div v-if="popoverOpen" class="notification-popover">
        <div class="popover-header">
          <span class="popover-title">{{ $t('notification.title') }}</span>
          <button
            v-if="hasUnread"
            type="button"
            class="read-all-btn"
            @click="handleReadAll"
          >
            <CheckCheck class="w-3.5 h-3.5" />
            <span>{{ $t('notification.mark_all_read') }}</span>
          </button>
        </div>

        <div class="popover-body">
          <div v-if="store.loading && store.items.length === 0" class="empty-hint">
            {{ $t('common.loading') }}
          </div>
          <div v-else-if="store.items.length === 0" class="empty-hint">
            {{ $t('notification.empty') }}
          </div>
          <template v-else>
            <button
              v-for="item in store.items"
              :key="item.id"
              type="button"
              class="notification-item"
              :class="{ 'is-unread': !item.read_at }"
              @click="handleItemClick(item)"
            >
              <span class="item-dot" :class="{ 'is-unread': !item.read_at }"></span>
              <span class="item-main">
                <span class="item-title">{{ item.title }}</span>
                <span v-if="item.body" class="item-body">{{ item.body }}</span>
                <span class="item-time">{{ formatTime(item.created_at) }}</span>
              </span>
            </button>
          </template>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.notification-bell-wrap {
  display: flex;
  width: 100%;
  position: relative;
}

/* 与 AppSidebar .nav-item 完全同规格：尺寸/内边距/颜色/交互一致 */
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

.notification-popover {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 0;
  width: 320px;
  max-width: min(320px, calc(100vw - 32px));
  border-radius: var(--radius-lg);
  background: var(--color-surface-white);
  border: 1px solid #E2E8F0;
  box-shadow: var(--shadow-lg);
  z-index: 200;
  overflow: hidden;
}

.popover-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
}

.popover-title {
  font-weight: 600;
  color: var(--color-text-title);
  font-size: 0.85rem;
}

.read-all-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: transparent;
  color: var(--color-primary-600);
  font-size: 0.72rem;
  font-weight: 500;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: var(--radius-sm);
  transition: background var(--transition-fast);
}

.read-all-btn:hover {
  background: var(--color-primary-50);
}

.popover-body {
  max-height: 380px;
  overflow-y: auto;
  padding: 6px;
}

.empty-hint {
  padding: 28px 12px;
  text-align: center;
  color: #94A3B8;
  font-size: 0.8rem;
}

.notification-item {
  display: flex;
  gap: 8px;
  width: 100%;
  text-align: left;
  border: none;
  background: transparent;
  border-radius: var(--radius-md);
  padding: 10px;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.notification-item:hover {
  background: #F1F5F9;
}

.notification-item.is-unread {
  background: var(--color-primary-50);
}

.notification-item.is-unread:hover {
  background: var(--color-primary-100);
}

.item-dot {
  flex: 0 0 auto;
  width: 7px;
  height: 7px;
  margin-top: 6px;
  border-radius: var(--radius-full);
  background: transparent;
  border: 1px solid #CBD5E1;
}

.item-dot.is-unread {
  background: var(--color-primary-500);
  border-color: var(--color-primary-500);
}

.item-main {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.item-title {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--color-text-body);
  line-height: 1.4;
}

.notification-item.is-unread .item-title {
  font-weight: 600;
  color: var(--color-text-title);
}

.item-body {
  font-size: 0.72rem;
  color: var(--color-text-muted);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.item-time {
  font-size: 0.66rem;
  color: #94A3B8;
}

.notif-pop-enter-active,
.notif-pop-leave-active {
  transition: opacity 0.16s ease, transform 0.16s ease;
}

.notif-pop-enter-from,
.notif-pop-leave-to {
  opacity: 0;
  transform: translateY(6px);
}
</style>

<!-- 非 scoped：跟随侧栏折叠态（.sidebar.is-collapsed 由 AppSidebar 控制） -->
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
