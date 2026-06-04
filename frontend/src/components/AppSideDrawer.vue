<script setup lang="ts">
import { computed, ref } from 'vue'
import { X, ChevronLeft, ChevronRight } from 'lucide-vue-next'

const props = withDefaults(defineProps<{
  show: boolean
  title: string
  width?: string
  closeOnOverlay?: boolean
  level?: number // 0-3
  resizable?: boolean
  hideClose?: boolean
}>(), {
  width: 'min(980px, 88vw)',
  closeOnOverlay: true,
  level: 1,
  resizable: false,
  hideClose: false,
})

const emit = defineEmits<{
  close: []
  'update:level': [value: number]
}>()

const panelStyle = computed(() => {
  if (props.resizable && props.level > 0) {
    return {} // Handled by CSS classes
  }
  return {
    width: props.width,
  }
})

const handleOverlayClick = () => {
  if (props.closeOnOverlay) {
    emit('close')
  }
}

const handleExpand = () => {
  if (props.level < 3) {
    emit('update:level', props.level + 1)
  }
}

const handleCollapse = () => {
  if (props.level > 1) {
    emit('update:level', props.level - 1)
  } else {
    emit('close')
  }
}

const isTransitioning = ref(false)
function onTransitionStart() { isTransitioning.value = true }
function onTransitionEnd() { isTransitioning.value = false }
</script>

<template>
  <div v-if="show" class="side-drawer-overlay" @click.self="handleOverlayClick">
    <aside
      class="side-drawer-panel glass-panel"
      :class="[
        { 'is-resizable': resizable, 'is-transitioning': isTransitioning },
        resizable ? `level-${level}` : ''
      ]"
      :style="panelStyle"
      @transitionstart="onTransitionStart"
      @transitionend="onTransitionEnd"
    >
      <!-- Side Handles for Triple Stage -->
      <div v-if="resizable" class="drawer-side-handles">
        <div class="handle-group">
          <button
            class="handle-btn expand-btn"
            type="button"
            :disabled="level >= 3"
            @click="handleExpand"
            :title="$t('common.expand')"
          >
            <ChevronLeft :size="20" />
          </button>
          
          <div class="handle-divider"></div>

          <button
            class="handle-btn collapse-btn"
            type="button"
            @click="handleCollapse"
            :title="level <= 1 ? $t('common.close') : $t('common.collapse')"
          >
            <ChevronRight :size="20" />
          </button>
        </div>
      </div>

      <header class="side-drawer-header">
        <div class="side-drawer-title">
          <slot name="icon" />
          <span>{{ title }}</span>
        </div>
        <div class="side-drawer-actions">
          <slot name="actions" />
          <button v-if="!hideClose" type="button" class="side-drawer-close" @click="emit('close')">
            <X class="w-4 h-4" />
          </button>
        </div>
      </header>
      <div class="side-drawer-body">
        <slot />
      </div>
    </aside>
  </div>
</template>

<style scoped>
.side-drawer-overlay {
  position: fixed;
  inset: 0;
  z-index: 42;
  display: flex;
  justify-content: flex-end;
  background: rgba(15, 23, 42, 0.28);
  contain: layout style paint;
}

.side-drawer-panel {
  height: 100%;
  border: none;
  border-left: 1px solid rgba(15, 23, 42, 0.12);
  border-radius: 0;
  background: #ffffff;
  display: flex;
  flex-direction: column;
  box-shadow: -24px 0 64px rgba(15, 23, 42, 0.14);
  transition: width 0.28s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  will-change: width;
  contain: layout style;
}

.side-drawer-panel.is-transitioning {
  contain: none;
}

/* Triple Stage Widths */
.side-drawer-panel.is-resizable.level-1 {
  width: clamp(680px, 48vw, 860px);
}
.side-drawer-panel.is-resizable.level-2 {
  width: clamp(860px, 72vw, 1280px);
}
.side-drawer-panel.is-resizable.level-3 {
  width: calc(100% - 250px);
}

/* Side Handles */
.drawer-side-handles {
  position: absolute;
  left: -40px;
  top: 50%;
  transform: translateY(-50%);
  width: 40px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(14, 165, 233, 0.12);
  border-right: none;
  border-radius: 12px 0 0 12px;
  display: flex;
  flex-direction: column;
  padding: 12px 0;
  box-shadow: -8px 2px 24px rgba(15, 23, 42, 0.05);
  z-index: 20;
}

.handle-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
}

.handle-divider {
  width: 24px;
  height: 1px;
  background: rgba(148, 163, 184, 0.2);
  margin: 4px 0;
}

.handle-btn {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  border: 1px solid transparent;
  background: transparent;
  color: #64748B;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.handle-btn:hover:not(:disabled) {
  background: #f1f5f9;
  color: #0ea5e9;
  border-color: rgba(14, 165, 233, 0.2);
}

.handle-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.side-drawer-header {
  padding: 14px 16px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.08);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.side-drawer-title {
  min-width: 0;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--color-primary-700);
  font-weight: 600;
}

.side-drawer-title span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.side-drawer-title :slotted(svg) {
  flex: 0 0 auto;
}

.side-drawer-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
}

.side-drawer-close {
  width: 30px;
  height: 30px;
  border: 1px solid rgba(148, 163, 184, 0.35);
  border-radius: 8px;
  background: transparent;
  color: #475569;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.side-drawer-close:hover {
  background: #f8fafc;
}

.side-drawer-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  contain: layout size;
}

.w-4 {
  width: 16px;
  height: 16px;
}

@media (max-width: 1600px) {
  .side-drawer-panel.is-resizable.level-1 {
    width: min(70vw, 860px);
  }
  .side-drawer-panel.is-resizable.level-2 {
    width: min(82vw, 1180px);
  }
}

@media (max-width: 1200px) {
  .side-drawer-panel:not(.is-resizable) {
    width: 100vw !important;
  }
  
  .side-drawer-panel.is-resizable.level-1 {
    width: min(82vw, 900px);
  }
  .side-drawer-panel.is-resizable.level-2 {
    width: min(90vw, 1040px);
  }
  .side-drawer-panel.is-resizable.level-3 {
    width: 100%;
  }
}
</style>
