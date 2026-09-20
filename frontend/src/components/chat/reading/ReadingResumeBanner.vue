<script setup lang="ts">
import { computed } from 'vue'
import { X, ArrowDown } from 'lucide-vue-next'

/**
 * 阅读进度轻量提示条（方案一：居中悬浮磨砂胶囊）：
 * 进入任务时有未读 → 「有 N 条未读」+「从上次阅读处继续」。
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
  <div v-if="props.unreadCount" class="reading-resume-banner-wrapper">
    <div
      class="reading-resume-banner"
      :class="{ 'is-degraded': needsReturnLatest }"
      role="button"
      tabindex="0"
      @click="emit('resume')"
      @keydown.enter.prevent="emit('resume')"
      @keydown.space.prevent="emit('resume')"
    >
      <div class="banner-main">
        <div class="unread-dot-wrapper" aria-hidden="true">
          <span class="unread-dot-pulse"></span>
          <span class="unread-dot"></span>
        </div>
        <span class="banner-text">
          {{ $t('reading.unread_count_label', { count: unreadLabel }) }}
        </span>
        <span class="banner-separator">·</span>
        <span class="banner-action-text">
          {{ $t('reading.resume_from_anchor') }}
        </span>
        <ArrowDown class="banner-arrow-icon" aria-hidden="true" />
      </div>

      <div class="banner-side-actions" @click.stop>
        <div class="banner-divider" aria-hidden="true"></div>
        <button
          v-if="needsReturnLatest"
          type="button"
          class="banner-return-btn"
          @click.stop="emit('return-latest')"
        >
          {{ $t('reading.return_latest') }}
        </button>
        <button
          type="button"
          class="banner-close"
          :aria-label="$t('reading.close')"
          :title="$t('reading.close')"
          @click.stop="emit('close')"
        >
          <X class="banner-close-icon" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.reading-resume-banner-wrapper {
  position: absolute;
  top: 10px;
  left: 0;
  right: 0;
  display: flex;
  justify-content: center;
  pointer-events: none;
  z-index: 20;
}

.reading-resume-banner {
  pointer-events: auto;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  width: fit-content;
  max-width: calc(100% - 32px);
  margin: 0;
  padding: 5px 6px 5px 12px;
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(226, 232, 240, 0.95);
  box-shadow: 0 4px 14px -2px rgba(15, 23, 42, 0.08), 0 1px 3px -1px rgba(15, 23, 42, 0.03);
  cursor: pointer;
  user-select: none;
  transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1),
              box-shadow 0.2s cubic-bezier(0.4, 0, 0.2, 1),
              border-color 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  box-sizing: border-box;
}

/* 浮动悬停：纯白微浮，文字绝不变蓝，仅平滑加深对比 */
.reading-resume-banner:hover {
  transform: translateY(-1px);
  border-color: rgba(203, 213, 225, 1);
  box-shadow: 0 6px 18px -2px rgba(15, 23, 42, 0.1), 0 2px 6px -1px rgba(15, 23, 42, 0.04);
}

.reading-resume-banner:active {
  transform: translateY(0);
  box-shadow: 0 1px 4px -1px rgba(15, 23, 42, 0.06);
}

/* 同步降级/过期状态 */
.reading-resume-banner.is-degraded {
  background: rgba(254, 252, 232, 0.94);
  border-color: rgba(245, 158, 11, 0.35);
  box-shadow: 0 4px 14px -2px rgba(245, 158, 11, 0.12), 0 2px 6px -1px rgba(15, 23, 42, 0.04);
}

.reading-resume-banner.is-degraded:hover {
  border-color: rgba(245, 158, 11, 0.55);
  box-shadow: 0 6px 18px -2px rgba(245, 158, 11, 0.2), 0 3px 8px -1px rgba(15, 23, 42, 0.05);
}

.banner-main {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.unread-dot-wrapper {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 8px;
  height: 8px;
  flex-shrink: 0;
}

.unread-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #0ea5e9;
  position: relative;
  z-index: 1;
}

.unread-dot-pulse {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: #0ea5e9;
  opacity: 0.6;
  animation: reading-dot-pulse 2s cubic-bezier(0.45, 0, 0.55, 1) infinite;
}

@keyframes reading-dot-pulse {
  0% {
    transform: scale(1);
    opacity: 0.6;
  }
  70% {
    transform: scale(2.4);
    opacity: 0;
  }
  100% {
    transform: scale(2.4);
    opacity: 0;
  }
}

.is-degraded .unread-dot {
  background: #f59e0b;
}

.is-degraded .unread-dot-pulse {
  background: #f59e0b;
}

.banner-text {
  font-size: 0.78rem;
  font-weight: 600;
  color: #0f172a;
  white-space: nowrap;
  letter-spacing: -0.01em;
}

.is-degraded .banner-text {
  color: #92400e;
}

.banner-separator {
  font-size: 0.75rem;
  color: #cbd5e1;
  margin: 0 1px;
}

.banner-action-text {
  font-size: 0.78rem;
  font-weight: 500;
  color: #475569;
  white-space: nowrap;
  transition: color 0.18s ease;
}

/* 浮动时仅加深为清晰深色，绝对不变蓝 */
.reading-resume-banner:hover .banner-action-text {
  color: #0f172a;
}

.is-degraded .banner-action-text {
  color: #92400e;
}

.is-degraded:hover .banner-action-text {
  color: #78350f;
}

.banner-arrow-icon {
  width: 12px;
  height: 12px;
  color: #64748b;
  flex-shrink: 0;
  transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1), color 0.18s ease;
}

.is-degraded .banner-arrow-icon {
  color: #b45309;
}

/* 浮动时箭头仅微向下移动并加深，绝对不变蓝 */
.reading-resume-banner:hover .banner-arrow-icon {
  transform: translateY(1.5px);
  color: #0f172a;
}

.banner-side-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.banner-divider {
  width: 1px;
  height: 12px;
  background-color: rgba(203, 213, 225, 0.8);
  margin: 0 2px;
}

.is-degraded .banner-divider {
  background-color: rgba(251, 191, 36, 0.6);
}

.banner-return-btn {
  padding: 2px 8px;
  font-size: 0.74rem;
  line-height: 1.4;
  border-radius: 9999px;
  border: 1px solid rgba(245, 158, 11, 0.4);
  color: #92400e;
  background: rgba(254, 243, 199, 0.6);
  cursor: pointer;
  transition: all 0.15s ease;
}

.banner-return-btn:hover {
  background: #f59e0b;
  border-color: #f59e0b;
  color: #ffffff;
}

.banner-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.15s ease;
}

.banner-close:hover {
  background: rgba(15, 23, 42, 0.08);
  color: #334155;
}

.banner-close-icon {
  width: 12px;
  height: 12px;
}
</style>
