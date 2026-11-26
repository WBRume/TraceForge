<script setup lang="ts">
import { useId } from 'vue'
import { useI18n } from 'vue-i18n'
import type { CanvasPaths } from './canvasPaths'
import { relationStyles } from './relationStyles'
import type { Point } from './model'

defineProps<{
  paths: CanvasPaths
  selectedId?: string
  preview: { source: Point; target: Point } | null
}>()
const emit = defineEmits<{ select: [id: string]; openRelation: [id: string] }>()
const { t } = useI18n()
const markerId = `canvas-arrow-${useId()}`
</script>

<template>
  <svg class="arrow-layer" width="1" height="1" :aria-label="t('workspace_canvas.arrows')">
    <defs>
      <marker :id="markerId" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="m 0 1 9 4 -9 4 z" class="arrow-marker" />
      </marker>
      <marker v-for="(style, type) in relationStyles" :id="`${markerId}-${type}`" :key="type"
        viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="m 0 1 9 4 -9 4 z" :fill="style.color" />
      </marker>
    </defs>
    <g v-for="line in paths.business" :key="line.relation.id" class="business-connector" :data-canvas-relation="line.relation.id"
      :data-relation-type="line.relation.relation_type" :data-source-kind="line.relation.source.kind"
      :data-source-id="line.relation.source.id" :data-target-kind="line.relation.target.kind" :data-target-id="line.relation.target.id">
      <title>{{ t(`workspace_canvas.relations.${line.relation.relation_type}`) }}</title>
      <path class="relation-line" :d="line.path" :stroke="line.style.color" :stroke-width="line.style.width"
        :stroke-dasharray="line.style.dash" :marker-end="`url(#${markerId}-${line.relation.relation_type})`" />
      <path class="arrow-hit relation-hit" :d="line.path" role="button" tabindex="0"
        :aria-label="t(`workspace_canvas.relations.${line.relation.relation_type}`)"
        @pointerdown.stop @click.stop="emit('openRelation', line.relation.id)"
        @keydown.enter.prevent.stop="emit('openRelation', line.relation.id)" />
      <text class="relation-label" :x="line.label.x" :y="line.label.y - 6" :fill="line.style.color">
        {{ t(`workspace_canvas.relations.${line.relation.relation_type}`) }}
      </text>
    </g>
    <g v-for="line in paths.arrows" :key="line.id" class="manual-arrow" :class="{ chosen: line.id === selectedId }"
      :data-canvas-edge="line.id">
      <path class="line arrow-line" :d="line.path" :marker-end="`url(#${markerId})`" />
      <path class="arrow-hit" :d="line.path" role="button" tabindex="0" :aria-label="t('workspace_canvas.arrow')"
        @pointerdown.stop="emit('select', line.id)" @keydown.enter.prevent="emit('select', line.id)" />
    </g>
    <line v-if="preview" class="line dragging-line" :x1="preview.source.x" :y1="preview.source.y"
      :x2="preview.target.x" :y2="preview.target.y" :marker-end="`url(#${markerId})`" />
  </svg>
</template>

<style scoped>
.arrow-layer { position: absolute; inset: 0 auto auto 0; overflow: visible; pointer-events: none; }
.line { fill: none; stroke-width: 2.25; }
.arrow-line, .dragging-line { stroke: var(--canvas-edge); }
.arrow-marker { fill: var(--canvas-edge); }
.relation-line { fill: none; stroke-linejoin: round; }
.relation-label { pointer-events: none; visibility: hidden; text-anchor: middle; font-size: 16px; font-weight: 750; paint-order: stroke; stroke: var(--canvas-paper); stroke-width: 5; }
.business-connector:is(:hover, :focus-within) .relation-label { visibility: visible; }
.dragging-line { stroke-dasharray: 5 4; }
.arrow-hit { fill: none; stroke: transparent; stroke-width: 15; pointer-events: stroke; cursor: pointer; outline: none; }
.relation-hit { stroke-width: 12; }
.manual-arrow:is(.chosen, :hover, :focus-within) .arrow-line { stroke: var(--canvas-accent); stroke-width: 3.5; }
</style>
