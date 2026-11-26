<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Plus } from '@/components/icons'
import type { CanvasBranchContinuation } from './model'

defineProps<{ marker: CanvasBranchContinuation; busy: boolean }>()
const emit = defineEmits<{ continue: [] }>()
const { t } = useI18n()
</script>

<template>
  <button type="button" class="branch-continuation"
    :data-canvas-continuation="marker.parentId" :disabled="busy"
    :style="{ left: `${marker.position.x}px`, top: `${marker.position.y}px`, '--stem-height': `${marker.stemHeight}px` }"
    :aria-label="t('workspace_canvas.tree.more')" :title="t('workspace_canvas.tree.more')"
    @pointerdown.stop @dblclick.stop @click.stop="emit('continue')">
    <Plus :size="16" />
  </button>
</template>

<style scoped>
.branch-continuation {
  position: absolute;
  transform: translate(-50%, -50%);
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid #b8cde0;
  border-radius: 50%;
  background: var(--canvas-chrome);
  color: var(--canvas-accent);
  box-shadow: 0 2px 5px #20355816;
  pointer-events: auto;
  cursor: pointer;
}
.branch-continuation::before {
  content: '';
  position: absolute;
  bottom: 100%;
  left: 50%;
  height: max(0px, calc(var(--stem-height) - 14px));
  border-left: 1.5px dashed #9fb5c9;
  pointer-events: none;
}
.branch-continuation:not(:disabled):hover { border-color: var(--canvas-accent); background: var(--canvas-hover); }
.branch-continuation:focus-visible { outline: 2px solid var(--canvas-accent); outline-offset: 2px; }
.branch-continuation:disabled { opacity: .55; cursor: wait; }
</style>
