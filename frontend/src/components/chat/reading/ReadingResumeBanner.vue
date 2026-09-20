<script setup lang="ts">
import { computed } from 'vue'
import { X } from 'lucide-vue-next'

/**
 * 阅读进度轻量提示条：进入任务时有未读 → 「有 N 条未读」+「从上次阅读处继续」。
 * - 点击继续：跳转未读起点并确认整批（由父级处理）；
 * - 点击关闭：仅收起提示条，不确认未读（下次进入仍会提示）；
 * - 同步状态过期/离线时额外提供「回到最新」出口。
 * 纯展示组件：不发 HTTP、不改 props，交互全部经事件上抛。
 */
const props = defineProps<{
  unreadCount: { value: string; relation: 'eq' | 'gte' } | null
  syncState: string
}>()

const emit = defineEmits<{
  (e: 'resume'): void
  (e: 'return-latest'): void
  (e: 'close'): void
}>()

const unreadLabel = computed(() => {
  if (!props.unreadCount) return ''
  const value = props.unreadCount.value
  return props.unreadCount.relation === 'gte' ? `${value}+` : value
})

/** 数据可能过期或通道离线：给一个回到最新的出口。 */
const needsReturnLatest = computed(() => props.syncState === 'stale' || props.syncState === 'offline')
</script>

<template>
  <div
    v-if="props.unreadCount"
    class="reading-resume-banner"
    :class="{ 'is-degraded': needsReturnLatest }"
  >
    <div class="banner-main">
      <span class="unread-dot" aria-hidden="true"></span>
      <span class="banner-text">
        {{ $t('reading.unread_count_label', { count: unreadLabel }) }}
      </span>
    </div>
    <div class="banner-actions">
      <button type="button" class="banner-btn primary" @click="emit('resume')">
        {{ $t('reading.resume_from_anchor') }}
      </button>
      <button v-if="needsReturnLatest" type="button" class="banner-btn ghost" @click="emit('return-latest')">
        {{ $t('reading.return_latest') }}
      </button>
      <button
        type="button"
        class="banner-close"
        :aria-label="$t('reading.close')"
        :title="$t('reading.close')"
        @click="emit('close')"
      >
        <X class="banner-close-icon" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.reading-resume-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin: 10px var(--space-6, 16px) 0;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(14, 165, 233, 0.08);
  border: 1px solid rgba(14, 165, 233, 0.22);
}

.reading-resume-banner.is-degraded {
  background: rgba(234, 179, 8, 0.08);
  border-color: rgba(234, 179, 8, 0.3);
}

.banner-main {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.unread-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #0ea5e9;
  flex-shrink: 0;
}

.banner-text {
  font-size: 0.82rem;
  color: #0369a1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.is-degraded .banner-text {
  color: #92400e;
}

.banner-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.banner-btn {
  padding: 3px 12px;
  font-size: 0.78rem;
  line-height: 1.5;
  border-radius: 6px;
  border: 1px solid rgba(14, 165, 233, 0.35);
  background: #fff;
  color: #0369a1;
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.banner-btn:hover {
  background: rgba(14, 165, 233, 0.1);
}

.banner-btn.primary {
  background: #0ea5e9;
  border-color: #0ea5e9;
  color: #fff;
}

.banner-btn.primary:hover {
  background: #0284c7;
}

.banner-btn.ghost {
  border-color: rgba(234, 179, 8, 0.4);
  color: #92400e;
  background: transparent;
}

.banner-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  transition: background-color 0.15s ease, color 0.15s ease;
}

.banner-close:hover {
  background: rgba(15, 23, 42, 0.08);
  color: #0f172a;
}

.banner-close-icon {
  width: 14px;
  height: 14px;
}
</style>
