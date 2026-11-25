<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { HandRaisedIcon } from '@heroicons/vue/24/outline'
import { ArrowRight, Link, MousePointer2, Pencil, Square } from '@/components/icons'
import type { CanvasTool } from './model'

const props = defineProps<{ tool: CanvasTool; canLink: boolean }>()
const emit = defineEmits<{ choose: [tool: CanvasTool] }>()
const { t } = useI18n()
const tools = computed(() => ([
  { id: 'select', icon: MousePointer2 },
  { id: 'pan', icon: HandRaisedIcon },
  { id: 'note', icon: Pencil },
  { id: 'frame', icon: Square },
  { id: 'arrow', icon: ArrowRight },
  { id: 'relation', icon: Link },
] as const).filter(tool => tool.id !== 'relation' || props.canLink))
</script>

<template>
  <nav class="canvas-toolbar" :aria-label="t('workspace_canvas.tools')" @pointerdown.stop>
    <button v-for="item in tools" :key="item.id" type="button" class="tool-button" :class="{ current: item.id === tool }"
      :aria-label="t(`workspace_canvas.tool.${item.id}`)" :aria-pressed="item.id === tool" :data-tool="item.id"
      @click="emit('choose', item.id)">
      <component :is="item.icon" class="tool-icon" />
      <span class="tool-tooltip" aria-hidden="true">{{ t(`workspace_canvas.tool.${item.id}`) }}</span>
    </button>
  </nav>
</template>

<style scoped>
.canvas-toolbar {
  position: absolute;
  z-index: 5;
  left: 16px;
  top: 18px;
  padding: 5px;
  display: grid;
  gap: 3px;
  border: 1px solid var(--canvas-line);
  border-radius: 12px;
  background: var(--canvas-chrome);
  box-shadow: 0 4px 12px #283b5a12;
}
.tool-button {
  display: grid;
  place-items: center;
  position: relative;
  width: 36px;
  height: 36px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--canvas-muted);
  cursor: pointer;
}
.tool-button:nth-child(3) { margin-top: 5px; }
.tool-button:nth-child(3)::before {
  content: '';
  position: absolute;
  top: -5px;
  left: 4px;
  right: 4px;
  border-top: 1px solid var(--canvas-line);
}
.tool-button:hover { background: var(--canvas-hover); color: var(--canvas-ink); }
.tool-button.current { background: var(--canvas-accent); color: #fff; }
.tool-icon { width: 18px; height: 18px; }
.tool-tooltip {
  position: absolute;
  left: calc(100% + 10px);
  z-index: 1;
  padding: 5px 8px;
  border-radius: 5px;
  white-space: nowrap;
  font-size: 12px;
  color: #fff;
  background: #23344f;
  opacity: 0;
  pointer-events: none;
  transition: opacity 120ms ease;
}
.tool-button:is(:hover, :focus-visible) .tool-tooltip { opacity: 1; }
@media (max-width: 650px) { .canvas-toolbar { left: 8px; top: 10px; } }
</style>
