<script setup lang="ts">
import { computed, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import { arrowGeometry, branchArrowGeometry, crossDomainGeometry } from './geometry'
import { relationStyles } from './relationStyles'
import type { CanvasEdge, CanvasGraphRelation, CanvasNode, CanvasRegion, CanvasRelationType, Point } from './model'

const props = defineProps<{
  nodes: CanvasNode[]
  visibleIds: Set<string>
  edges: CanvasEdge[]
  relations: CanvasGraphRelation[]
  regions: CanvasRegion[]
  selectedId?: string
  tree?: boolean
  preview: { source: Point; target: Point } | null
}>()
const emit = defineEmits<{ select: [id: string]; openRelation: [id: string] }>()
const { t } = useI18n()
const markerId = `canvas-arrow-${useId()}`
const pairKey = (source: string, target: string) => [source, target].sort().join(':')

const paths = computed(() => {
  const nodesById = new Map(props.nodes.map(node => [node.id, node]))
  const regionsById = new Map(props.regions.map(region => [region.id, region]))
  const groups = new Map<string, CanvasGraphRelation[]>()
  const incoming = new Map<string, CanvasGraphRelation[]>()
  for (const relation of props.relations) {
    const key = pairKey(relation.sourceNodeId, relation.targetNodeId)
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)?.push(relation)
    const source = nodesById.get(relation.sourceNodeId), target = nodesById.get(relation.targetNodeId)
    if (!props.tree || !source || !target || Math.abs(source.position.x - target.position.x) < target.size.width) continue
    const lane = `${target.id}:${source.position.x > target.position.x ? 'right' : 'left'}`
    const list = incoming.get(lane) ?? []
    list.push(relation)
    incoming.set(lane, list)
  }
  const ports = new Map<string, number>()
  const sharedPorts = new Map<string, number>()
  for (const list of incoming.values()) {
    list.sort((a, b) => nodesById.get(a.sourceNodeId)!.position.y - nodesById.get(b.sourceNodeId)!.position.y)
    const step = Math.min(7, 72 / list.length)
    list.forEach((link, index) => ports.set(link.id, (index - (list.length - 1) / 2) * step))
    const siblings = new Map<CanvasRelationType, CanvasGraphRelation[]>()
    for (const link of list) {
      const source = nodesById.get(link.sourceNodeId)!, target = nodesById.get(link.targetNodeId)!
      if (source.domainId !== target.domainId || Math.abs(source.position.x - target.position.x) >= source.size.width + 155) continue
      const related = siblings.get(link.relation_type) ?? []
      related.push(link)
      siblings.set(link.relation_type, related)
    }
    for (const links of siblings.values()) {
      if (links.length < 3) continue
      const port = links.reduce((total, link) => total + (ports.get(link.id) ?? 0), 0) / links.length
      links.forEach(link => sharedPorts.set(link.id, port))
    }
  }
  const visible = (source: string, target: string) => props.visibleIds.has(source) || props.visibleIds.has(target)
  const business = [...groups.values()].flatMap(list => list.flatMap((relation, index) => {
    const source = nodesById.get(relation.sourceNodeId), target = nodesById.get(relation.targetNodeId)
    if (!source || !target || !visible(source.id, target.id)) return []
    const sourceRegion = source.domainId ? regionsById.get(source.domainId) : undefined
    const targetRegion = target.domainId ? regionsById.get(target.domainId) : undefined
    const offset = (index - (list.length - 1) / 2) * 14
    const sharedPort = sharedPorts.get(relation.id)
    const innerLane = sourceRegion && sourceRegion === targetRegion
      ? Math.min(sourceRegion.position.y + 5 + index * 4, source.position.y - 9, target.position.y - 9) : undefined
    const geometry = sharedPort !== undefined ? branchArrowGeometry(source, target, sharedPort)
      : props.tree ? arrowGeometry(source, target, (ports.get(relation.id) ?? 0) + offset, true, innerLane)
      : sourceRegion && targetRegion && sourceRegion !== targetRegion
      ? crossDomainGeometry(source, target, sourceRegion, targetRegion, offset, relation.relation_type === 'PREREQUISITE' ? -15 : 0)
      : arrowGeometry(source, target, offset, true, sourceRegion && sourceRegion.position.y + 63 + index * 6)
    return [{
      relation, style: relationStyles[relation.relation_type],
      ...geometry,
    }]
  }))
  const arrows = props.edges.flatMap(edge => {
    const source = nodesById.get(edge.source), target = nodesById.get(edge.target)
    if (!source || !target || !visible(source.id, target.id)) return []
    const shared = groups.get(pairKey(source.id, target.id))?.length ?? 0
    return [{ id: edge.id, path: arrowGeometry(source, target, shared ? (shared + 1) * 8 : 0).path }]
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
