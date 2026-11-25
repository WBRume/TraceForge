<script setup lang="ts">
import { computed, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import { arrowPath } from './geometry'
import type { CanvasEdge, CanvasNode, CanvasRelation, Point } from './model'

const props = defineProps<{
  nodes: CanvasNode[]
  visibleIds: Set<string>
  edges: CanvasEdge[]
  relations: CanvasRelation[]
  selectedId?: string
  canLink: boolean
  preview: { source: Point; target: Point } | null
}>()
const emit = defineEmits<{ select: [id: string]; editRelation: [relation: CanvasRelation] }>()
const { t } = useI18n()
const markerId = `canvas-arrow-${useId()}`

const paths = computed(() => {
  const nodesById = new Map(props.nodes.map(node => [node.id, node]))
  const taskNodes = new Map<string, CanvasNode[]>()
  const requirementNodes = new Map<string, CanvasNode[]>()
  for (const node of props.nodes) {
    if (!node.details || !node.reference) continue
    const lists = node.reference.kind === 'task' ? taskNodes : node.reference.kind === 'requirement' ? requirementNodes : null
    if (!lists) continue
    const id = node.reference.id
    if (!lists.has(id)) lists.set(id, [])
    lists.get(id)?.push(node)
  }
  const links = new Set<string>()
  const visible = (source: string, target: string) => props.visibleIds.has(source) || props.visibleIds.has(target)
  const business = props.relations.flatMap(relation => (requirementNodes.get(relation.requirement_id) || [])
    .flatMap(source => (taskNodes.get(relation.task_id) || []).filter(target => visible(source.id, target.id)).map(target => {
      const id = `${source.id}:${target.id}`
      links.add(id)
      return { id, path: arrowPath(source, target), relation }
    })))
  const arrows = props.edges.flatMap(edge => {
    const source = nodesById.get(edge.source), target = nodesById.get(edge.target)
    if (!source || !target || !visible(source.id, target.id)) return []
    // Keep both relationships selectable when a business link and an arrow share two cards.
    const shared = links.has(`${source.id}:${target.id}`) || links.has(`${target.id}:${source.id}`)
    return [{ id: edge.id, path: arrowPath(source, target), shared }]
  })
  return { business, arrows }
})
</script>

<template>
  <svg class="arrow-layer" width="1" height="1" :aria-label="t('workspace_canvas.arrows')">
    <defs>
      <marker :id="markerId" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="m 0 1 9 4 -9 4 z" class="arrow-marker" />
      </marker>
      <marker :id="`${markerId}-relation`" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="m 0 1 9 4 -9 4 z" class="relation-marker" />
      </marker>
    </defs>
    <g v-for="line in paths.business" :key="line.id" class="business-connector">
      <title>{{ t(line.relation.relation_type === 'COVERS' ? 'workspace_canvas.coverage_link' : 'workspace_canvas.requirement_link') }}</title>
      <path class="line relation-line" :d="line.path"
        :marker-end="`url(#${markerId}-relation)`" data-canvas-relation
        :data-requirement-id="line.relation.requirement_id" :data-task-id="line.relation.task_id" :data-relation-type="line.relation.relation_type" />
      <path v-if="canLink" class="arrow-hit relation-hit" :d="line.path" role="button" tabindex="0"
        :aria-label="t('workspace_canvas.actions.edit_relation')" data-relation-editor
        :data-requirement-id="line.relation.requirement_id" :data-task-id="line.relation.task_id"
        @pointerdown.stop @click.stop="emit('editRelation', line.relation)"
        @keydown.enter.prevent.stop="emit('editRelation', line.relation)" />
    </g>
    <g v-for="line in paths.arrows" :key="line.id" class="manual-arrow" :class="{ chosen: line.id === selectedId }"
      :transform="line.shared ? 'translate(0, 8)' : undefined" :data-canvas-edge="line.id">
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
.relation-line { stroke: var(--canvas-relation); stroke-dasharray: 6 5; }
.business-connector:is(:hover, :focus-within) .relation-line { stroke-width: 3.5; }
.relation-marker { fill: var(--canvas-relation); }
.dragging-line { stroke-dasharray: 5 4; }
.arrow-hit { fill: none; stroke: transparent; stroke-width: 15; pointer-events: stroke; cursor: pointer; outline: none; }
.relation-hit { stroke-width: 12; }
.manual-arrow:is(.chosen, :hover, :focus-within) .arrow-line { stroke: var(--canvas-accent); stroke-width: 3.5; }
</style>
