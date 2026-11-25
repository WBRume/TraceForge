<script setup lang="ts">
import { shallowRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Maximize2, Minimize2, X } from '@/components/icons'

const props = defineProps<{ title: string; wide: boolean }>()
defineEmits<{ close: [] }>()
const { t } = useI18n()
const heading = useTemplateRef<HTMLElement>('heading')
const expanded = shallowRef(props.wide)
watch(() => [props.title, props.wide] as const, ([, wide]) => {
  expanded.value = wide
  heading.value?.focus({ preventScroll: true })
}, { flush: 'post' })
</script>

<template>
  <aside class="canvas-operation-panel glass-panel" :class="{ expanded }" :aria-label="title"
    data-testid="canvas-operation-panel">
    <header class="operation-header">
      <h2 ref="heading" tabindex="-1">{{ title }}</h2>
      <div class="operation-controls">
        <button type="button" :title="t(expanded ? 'common.collapse' : 'common.expand')"
          :aria-label="t(expanded ? 'common.collapse' : 'common.expand')" @click="expanded = !expanded">
          <component :is="expanded ? Minimize2 : Maximize2" :size="17" />
        </button>
        <button type="button" :title="t('workspace_canvas.actions.close_panel')"
          :aria-label="t('workspace_canvas.actions.close_panel')" @click="$emit('close')"><X :size="20" /></button>
      </div>
    </header>
    <div class="operation-content"><slot /></div>
  </aside>
</template>

<style scoped>
.canvas-operation-panel {
  position: absolute;
  z-index: 12;
  inset: 10px 10px 10px auto;
  display: flex;
  flex-direction: column;
  width: min(640px, calc(100% - 20px));
  min-width: 0;
  overflow: hidden;
  border: 1px solid #dbeafe;
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 12px 38px #1e3a8a24, 0 2px 9px #0f172a12;
}
.canvas-operation-panel.expanded { width: calc(100% - 20px); }
.operation-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 13px 9px 17px;
  border-bottom: 1px solid #e2e8f0;
  background: linear-gradient(115deg, #eff6ff, #f8fbff 70%, #fff);
}
.operation-header h2 { margin: 0; font-size: 14px; font-weight: 750; color: #1e3a8a; outline: none; }
.operation-controls { display: flex; gap: 4px; }
.operation-controls button {
  display: grid;
  place-items: center;
  width: 33px;
  height: 33px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #475569;
  cursor: pointer;
}
.operation-controls button:hover, .operation-controls button:focus-visible { background: #e0f2fe; color: #0369a1; }
.operation-content { flex: 1; min-height: 0; min-width: 0; overflow: auto; container-type: inline-size; }
</style>
