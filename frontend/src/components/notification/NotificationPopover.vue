<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { CheckCheck, X } from 'lucide-vue-next'
import type { AppNotificationItem } from '@/stores/notification'

const props = defineProps<{
  items: AppNotificationItem[]
  loading: boolean
}>()

const emit = defineEmits<{
  (e: 'consume', item: AppNotificationItem): void
  (e: 'remove', id: string): void
  (e: 'mark-all-read'): void
  (e: 'clear-all'): void
}>()

const { t } = useI18n()

const hasUnread = computed(() => props.items.some((item) => !item.read_at))

const formatTime = (iso: string | null): string => {
  if (!iso) return ''
  const date = new Date(iso)
  const diffMin = Math.floor((Date.now() - date.getTime()) / 60000)
  if (diffMin < 1) return t('notification.just_now')
  if (diffMin < 60) return t('notification.minutes_ago', { n: diffMin })
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return t('notification.hours_ago', { n: diffHour })
  return date.toLocaleDateString()
}
</script>

<template>
  <div class="notification-popover">
    <div class="popover-header">
      <span class="popover-title">{{ $t('notification.title') }}</span>
      <span class="header-actions">
        <button
          v-if="hasUnread"
          type="button"
          class="header-btn"
          @click="emit('mark-all-read')"
        >
          <CheckCheck class="w-3.5 h-3.5" />
          <span>{{ $t('notification.mark_all_read') }}</span>
        </button>
        <button
          v-if="items.length > 0"
          type="button"
          class="header-btn is-danger"
          @click="emit('clear-all')"
        >
          <span>{{ $t('notification.clear_all') }}</span>
        </button>
      </span>
    </div>

    <div class="popover-body">
      <div v-if="loading && items.length === 0" class="empty-hint">
        {{ $t('common.loading') }}
      </div>
      <div v-else-if="items.length === 0" class="empty-hint">
        {{ $t('notification.empty') }}
      </div>
      <template v-else>
        <div
          v-for="item in items"
          :key="item.id"
          role="button"
          tabindex="0"
          class="notification-item"
          :class="{ 'is-unread': !item.read_at }"
          @click="emit('consume', item)"
          @keydown.enter="emit('consume', item)"
        >
          <span class="item-dot" :class="{ 'is-unread': !item.read_at }"></span>
          <span class="item-main">
            <span class="item-title">{{ item.title }}</span>
            <span v-if="item.body" class="item-body">{{ item.body }}</span>
            <span class="item-time">{{ formatTime(item.created_at) }}</span>
          </span>
          <button
            type="button"
            class="item-remove"
            :title="$t('notification.delete')"
            @click.stop="emit('remove', item.id)"
          >
            <X class="w-3.5 h-3.5" />
          </button>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.notification-popover {
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 24px);
  border-radius: var(--radius-lg);
  background: var(--color-surface-white);
  border: 1px solid #E2E8F0;
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}

.popover-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: 10px 14px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  flex: 0 0 auto;
}

.popover-title {
  font-weight: 600;
  color: var(--color-text-title);
  font-size: 0.85rem;
}

.header-actions {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.header-btn {
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
  white-space: nowrap;
}

.header-btn.is-danger {
  color: #B91C1C;
}

.header-btn.is-danger:hover {
  background: #FEE2E2;
}

.header-btn:hover {
  background: var(--color-primary-50);
}

.popover-body {
  flex: 1 1 auto;
  min-height: 0;
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
  align-items: flex-start;
  gap: 8px;
  width: 100%;
  text-align: left;
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
  flex: 1 1 auto;
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

.item-remove {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  margin-top: 2px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: #94A3B8;
  cursor: pointer;
  opacity: 0;
  transition: all var(--transition-fast);
}

.notification-item:hover .item-remove,
.notification-item:focus-within .item-remove {
  opacity: 1;
}

.item-remove:hover {
  background: #FEE2E2;
  color: #B91C1C;
}
</style>
