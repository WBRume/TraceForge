<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { ChevronUp, Plus } from '@/components/icons'
import { sourceIcons, type CanvasNode, type Point } from './model'

defineProps<{ parent: CanvasNode; position: Point; maxWidth: number; more: boolean; busy: boolean }>()
const emit = defineEmits<{ locate: []; continue: [] }>()
const { t } = useI18n()
</script>

<template>
  <div v-if="parent.reference" class="branch-context" :data-canvas-branch-context="parent.id"
    :style="{ left: `${position.x}px`, top: `${position.y}px`, maxWidth: `${maxWidth}px` }"
    @pointerdown.stop @dblclick.stop>
    <component :is="sourceIcons[parent.reference.kind]" :size="15" class="context-icon" />
    <span class="context-title" :title="parent.details?.title">{{ parent.details?.title }}</span>
    <button type="button" :aria-label="t('workspace_canvas.tree.locate_parent')" :title="t('workspace_canvas.tree.locate_parent')"
      @click="emit('locate')"><ChevronUp :size="16" /></button>
    <button v-if="more" type="button" :aria-label="t('workspace_canvas.tree.more')" :title="t('workspace_canvas.tree.more')"
      :disabled="busy" @click="emit('continue')"><Plus :size="17" /></button>
  </div>
</template>

<style scoped>
.branch-context {
  position: absolute;
  z-index: 3;
  display: flex;
  align-items: center;
  gap: 5px;
  min-height: 32px;
  padding: 2px 3px 2px 8px;
  border: 1px solid #a8c5df;
  border-radius: 7px;
  background: var(--canvas-chrome);
  color: var(--canvas-ink);
  box-shadow: 0 2px 7px #2035581a;
}
.context-icon { flex: 0 0 auto; color: var(--canvas-accent); }
.context-title {
  overflow: hidden;
  margin-inline-end: 3px;
  font-size: 12px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.branch-context button {
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--canvas-accent);
  cursor: pointer;
}
.branch-context button:is(:hover, :focus-visible):not(:disabled) { background: var(--canvas-hover); }
.branch-context button:disabled { opacity: .55; cursor: wait; }
</style>
