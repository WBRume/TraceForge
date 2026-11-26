<script setup lang="ts">
import { computed, nextTick, onMounted, onScopeDispose, shallowRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Maximize2, Minus, Plus, Workflow } from '@/components/icons'
import CanvasArrows from './CanvasArrows.vue'
import CanvasBranchContext from './CanvasBranchContext.vue'
import CanvasBranchContinuation from './CanvasBranchContinuation.vue'
import CanvasItem from './CanvasItem.vue'
import CanvasOverviewLayer from './CanvasOverviewLayer.vue'
import CanvasRelationLegend from './CanvasRelationLegend.vue'
import CanvasToolbar from './CanvasToolbar.vue'
import { buildCanvasPaths } from './canvasPaths'
import type { CanvasContextRequest, CanvasContextTarget } from './contextMenu'
import { arrowInBounds, viewportBounds } from './geometry'
import { referenceKey, type CanvasConnection, type CanvasGraph, type CanvasNode, type CanvasRelationType, type CanvasSelection,
  type CanvasTool, type NodePatch, type Point, type Size } from './model'
import { useCanvasInteraction } from './useCanvasInteraction'
import type { RootDirection } from './useCanvasRoots'
import { canvasEntryScale } from './treePreview'

const props = defineProps<{
  data: CanvasGraph; selection: CanvasSelection | null; busy: boolean; summary?: boolean;
  expanded: ReadonlyMap<string, unknown>; expanding: string
  rootStream?: { next: boolean; previous: boolean; loading: boolean; ids: ReadonlySet<string> }
}>()
const emit = defineEmits<{
  select: [selection: CanvasSelection | null]
  create: [kind: 'note' | 'frame', position: Point, size?: Size]
  update: [nodeId: string, patch: NodePatch]
  connect: [source: string, target: string, mode: CanvasConnection]
  open: [id: string]
  remove: []
  openRelation: [id: string]
  context: [request: CanvasContextRequest]
  visibleTasks: [ids: string[]]
  stream: [direction: RootDirection]
  viewportSize: [size: Size]
  toggleBranch: [id: string]
  moreBranch: [id: string]
}>()
const { t } = useI18n()
const branchKey = (node: CanvasNode) => node.reference ? referenceKey(node.reference) : ''
const surface = useTemplateRef<HTMLElement>('surface')
const tool = shallowRef<CanvasTool>('select')
const relationFilter = shallowRef<CanvasRelationType | null>(null)
const activeBranch = shallowRef('')
const size = shallowRef<Size>({ width: 0, height: 0 })
let movedViewport = false
let observer: ResizeObserver | undefined
function measure(width: number, height: number) {
  if (size.value.width === width && size.value.height === height) return
  size.value = { width, height }
  emit('viewportSize', size.value)
  void nextTick(() => { if (!movedViewport) fitEntries() })
}
onMounted(() => {
  if (!surface.value) return
  measure(surface.value.clientWidth, surface.value.clientHeight)
  observer = new ResizeObserver(([entry]) => {
    if (entry) measure(entry.contentRect.width, entry.contentRect.height)
  })
  observer.observe(surface.value)
})
onScopeDispose(() => observer?.disconnect())
const map = useCanvasInteraction({
  surface,
  nodes: () => props.data.nodes,
  regions: () => props.data.regions,
  featured: () => Boolean(props.summary),
  tool: () => tool.value,
  busy: () => props.busy,
  select: selection => emit('select', selection),
  create: (...args) => { emit('create', ...args); chooseTool('select') },
  update: (id, patch) => emit('update', id, patch),
  connect: (source, target, mode) => emit('connect', source, target, mode),
})
const { viewport, moving, space, connectStart, hoveredTarget, renderedNodes, framePreview, connectionPreview } = map
const renderedById = computed(() => new Map(renderedNodes.value.map(node => [node.id, node])))
const isOverview = computed(() => viewport.value.scale < (props.summary ? 0.26 : 0.34))
const compact = computed(() => viewport.value.scale < 0.68)
const visibleIds = computed(() => {
  const { x, y, scale } = viewport.value
  return new Set(renderedNodes.value.filter(node => {
    const left = node.position.x * scale + x, top = node.position.y * scale + y
    return left < size.value.width + 100 && top < size.value.height + 100
      && left + node.size.width * scale > -100 && top + node.size.height * scale > -100
  }).map(node => node.id))
})
const frames = computed(() => renderedNodes.value.filter(node => node.kind === 'frame' && visibleIds.value.has(node.id)))
const items = computed(() => renderedNodes.value.filter(node => node.kind !== 'frame' && visibleIds.value.has(node.id)))
const expandingNodeId = computed(() => props.expanding
  ? props.data.nodes.find(node => branchKey(node) === props.expanding)?.id : undefined)
const visibleContinuations = computed(() => {
  const { x, y, scale } = viewport.value
  return props.data.continuations.filter(({ position }) => {
    const left = position.x * scale + x, top = position.y * scale + y
    return left > -100 && left < size.value.width + 100 && top > -100 && top < size.value.height + 100
  })
})
const planTasks = computed(() => {
  if (props.summary) return []
  const tasks = props.data.nodes.flatMap(node => node.reference?.kind === 'task'
    && (!props.data.root_tree || props.expanded.has(branchKey(node))) ? [node] : [])
  if (tasks.length <= 12) return tasks.map(node => node.reference!.id)
  if (isOverview.value) return []
  const { x, y, scale } = viewport.value
  const distance = (node: CanvasNode) => Math.hypot(node.position.x * scale + x - size.value.width / 2,
    node.position.y * scale + y - size.value.height / 2)
  return tasks.filter(node => visibleIds.value.has(node.id)).sort((a, b) => distance(a) - distance(b))
    .slice(0, 12).map(node => node.reference!.id)
})
watch(() => [...planTasks.value].sort().join(','), (value, _, cleanup) => {
  const timer = setTimeout(() => emit('visibleTasks', value ? value.split(',') : []), 220)
  cleanup(() => clearTimeout(timer))
}, { immediate: true })
watch(() => props.data, (current, previous) => {
  if (current.quarter?.id !== previous.quarter?.id || (current.root_tree !== previous.root_tree && !movedViewport)) {
    movedViewport = false
    activeBranch.value = ''
    fitEntries()
    return
  }
  const autoCount = (data: CanvasGraph) => data.nodes.filter(node => node.automatic).length
  if (!current.root_tree && !movedViewport && autoCount(current) > autoCount(previous)) { fitEntries(); return }
  const planCount = (data: CanvasGraph) => data.nodes.filter(node => node.reference?.kind === 'plan_document').length
  if (moving.value || planCount(current) === planCount(previous)) return
  const id = props.selection?.type === 'node' ? props.selection.id : undefined
  if (!id && isOverview.value) { map.fit(); return }
  const { x, y, scale } = viewport.value
  const distance = (node: CanvasNode) => Math.hypot(node.position.x * scale + x - size.value.width / 2,
    node.position.y * scale + y - size.value.height / 2)
  const anchor = id ? previous.nodes.find(node => node.id === id)
    : previous.nodes.reduce<CanvasNode | undefined>((closest, node) => !closest || distance(node) < distance(closest) ? node : closest, undefined)
  const moved = anchor && current.nodes.find(node => node.id === anchor.id)
  if (anchor && moved) viewport.value = {
    scale, x: x + (anchor.position.x - moved.position.x) * scale, y: y + (anchor.position.y - moved.position.y) * scale,
  }
})
const selectedNode = computed(() => props.selection?.type === 'node' ? props.data.nodes.find(node => node.id === props.selection?.id) : null)
const selectedEdge = computed(() => props.selection?.type === 'edge' ? props.selection.id : undefined)
const canRemove = computed(() => selectedEdge.value || (selectedNode.value && !selectedNode.value.automatic))
const shownRelations = computed(() => relationFilter.value
  ? props.data.relations.filter(link => link.relation_type === relationFilter.value) : props.data.relations)
const arrows = computed(() => buildCanvasPaths({ nodes: renderedNodes.value, edges: props.data.edges,
  relations: props.data.relations, regions: props.data.regions, branchRoutes: props.data.branchRoutes, tree: !!props.data.quarter }))
const visiblePaths = computed(() => {
  const view = viewportBounds(viewport.value, size.value, 95)
  return {
    business: arrows.value.business.filter(line => (!relationFilter.value || line.relation.relation_type === relationFilter.value)
      && arrowInBounds(line, view)),
    arrows: arrows.value.arrows.filter(line => arrowInBounds(line, view)),
  }
})
const branchContext = computed(() => {
  if (isOverview.value || size.value.width < 230) return null
  const { x, y, scale } = viewport.value
  const { width, height } = size.value
  const maxWidth = Math.min(268, width - 84)
  let leftmostLane = Infinity
  let context: { parent: CanvasNode; position: Point; maxWidth: number; more: boolean } | null = null
  for (const { branchParentId, stem } of visiblePaths.value.business) {
    if (!branchParentId || !stem) continue
    const parent = renderedById.value.get(branchParentId)
    if (!parent?.details) continue
    const left = x + parent.position.x * scale, titleY = y + (parent.position.y + 42) * scale
    if (left + parent.size.width * scale > 36 && left < width - 36 && titleY > 13 && titleY < height - 20) continue
    const lane = x + stem.x * scale
    const top = Math.max(12, y + stem.top * scale - 9)
    if (lane < 66 || lane > width - 14 || top >= height - 76 || y + stem.bottom * scale < top + 23) continue
    if (parent.id !== activeBranch.value && lane >= leftmostLane) continue
    leftmostLane = lane
    context = { parent, position: { x: Math.max(65, Math.min(lane - 13, width - maxWidth - 12)), y: top }, maxWidth,
      more: props.data.continuations.some(marker => marker.parentId === parent.id) }
    if (parent.id === activeBranch.value) break
  }
  return context
})
watch(() => props.data.relations, links => {
  if (!links.some(link => link.relation_type === relationFilter.value)) relationFilter.value = null
})
const sceneStyle = computed(() => ({
  transform: `translate(${viewport.value.x}px, ${viewport.value.y}px) scale(${viewport.value.scale})`,
  '--canvas-compact-title': `${Math.min(32, Math.max(24, 12 / viewport.value.scale))}px`,
  '--canvas-compact-meta': `${Math.min(24, Math.max(15, 9 / viewport.value.scale))}px`,
  '--canvas-compact-summary': `${Math.min(26, Math.max(16, 9 / viewport.value.scale))}px`,
}))
const gridStyle = computed(() => ({
  backgroundPosition: `${viewport.value.x}px ${viewport.value.y}px`,
  backgroundSize: `${Math.max(isOverview.value ? 18 : 10, viewport.value.scale * 22)}px ${Math.max(isOverview.value ? 18 : 10, viewport.value.scale * 22)}px`,
}))
const previewStyle = computed(() => {
  const preview = framePreview.value
  return preview ? { left: `${preview.position.x}px`, top: `${preview.position.y}px`,
    width: `${preview.size.width}px`, height: `${preview.size.height}px` } : undefined
})
const cursorHint = computed(() => ['note', 'frame', 'arrow', 'relation'].includes(tool.value)
  ? t(`workspace_canvas.hint.${tool.value}`) : '')

function chooseTool(next: CanvasTool) {
  map.cancelConnection()
  tool.value = next
}
watch(() => props.data.access.can_link_requirements, allowed => {
  if (!allowed && tool.value === 'relation') chooseTool('select')
})

function open(id: string) {
  if (!props.busy && tool.value === 'select') emit('open', id)
}

function openContext(target: Element, client: Point) {
  const element = surface.value
  if (!element) return
  const nodeId = target.closest('[data-canvas-node]')?.getAttribute('data-canvas-node')
  const relationId = target.closest('[data-canvas-relation]')?.getAttribute('data-canvas-relation')
  const edgeId = target.closest('[data-canvas-edge]')?.getAttribute('data-canvas-edge')
  const rect = element.getBoundingClientRect()
  const anchor = { x: client.x - rect.left, y: client.y - rect.top }
  const { x, y, scale } = viewport.value
  const position = { x: (anchor.x - x) / scale, y: (anchor.y - y) / scale }
  const frameId = !nodeId && !relationId && !edgeId ? frameAtBorder(position, 6 / scale) : undefined
  const scope: CanvasContextTarget = nodeId || frameId ? { type: 'node', id: (nodeId || frameId)! }
    : relationId ? { type: 'relation', id: relationId }
    : edgeId ? { type: 'edge', id: edgeId } : { type: 'surface' }
  map.cancelConnection()
  movedViewport = true
  emit('context', {
    target: scope,
    anchor,
    position,
    size: { width: rect.width, height: rect.height },
    restoreFocus: target.closest<HTMLElement>('[tabindex]') || element,
  })
}

function frameAtBorder(point: Point, tolerance: number) {
  const nodes = renderedNodes.value
  for (let index = nodes.length - 1; index >= 0; index--) {
    const node = nodes[index]
    if (node.kind !== 'frame') continue
    const x = point.x - node.position.x, y = point.y - node.position.y
    const { width, height } = node.size
    if (x >= -tolerance && y >= -tolerance && x <= width + tolerance && y <= height + tolerance
      && Math.min(Math.abs(x), Math.abs(y), Math.abs(x - width), Math.abs(y - height)) <= tolerance) return node.id
  }
}

function rightClick(event: MouseEvent) {
  if (event.target instanceof Element) openContext(event.target, { x: event.clientX, y: event.clientY })
}

function assetsAt(event: Pick<MouseEvent, 'clientX' | 'clientY'>) {
  const rect = surface.value?.getBoundingClientRect()
  if (!rect) return {}
  const { x, y, scale } = viewport.value
  const point = { x: (event.clientX - rect.left - x) / scale, y: (event.clientY - rect.top - y) / scale }
  const contains = (item: Pick<CanvasNode, 'position' | 'size'>) => point.x >= item.position.x && point.y >= item.position.y
    && point.x <= item.position.x + item.size.width && point.y <= item.position.y + item.size.height
  const node = renderedNodes.value.find(node => node.kind !== 'frame' && contains(node))
  const region = props.data.regions.find(region => region.type === 'domain' && contains(region))
    ?? props.data.regions.find(contains)
  return { node, region }
}

function zoomIntoMap(event: MouseEvent) {
  if (!isOverview.value || tool.value !== 'select' || (event.target as Element).closest('button')) return
  const { node, region } = assetsAt(event)
  const id = node?.id ?? (region && props.data.assetNodeIds.get(region.id))
  if (id) {
    map.focusNodes([id]); emit('select', { type: 'node', id })
    return
  }
  if (region) map.focusRegion(region)
  else map.adjustZoom(1.6)
}

function wheel(event: WheelEvent) {
  movedViewport = true
  const before = viewport.value.y
  map.wheel(event)
  if (!event.ctrlKey && !event.metaKey) requestRoots(before)
}

function pointerMove(event: PointerEvent) {
  const before = viewport.value
  map.pointerMove(event)
  if (viewport.value !== before) movedViewport = true
  requestRoots(before.y)
}

function requestRoots(before: number) {
  const stream = props.rootStream
  const { y, scale } = viewport.value
  if (!stream || stream.loading || before === y) return
  const regions = props.data.regions.filter(region => stream.ids.has(region.id))
  const first = regions[0]?.position.y ?? 0
  const last = regions.at(-1)
  const bottom = last ? last.position.y + last.size.height : 150
  if (y < before && stream.next && y + bottom * scale < size.value.height + 140) emit('stream', 'next')
  if (y > before && stream.previous && y + first * scale > -140) emit('stream', 'previous')
}

function keepInView(position: Point, id: string) {
  const node = props.data.nodes.find(item => item.id === id)
  if (!node) return
  const { x, y, scale } = viewport.value
  viewport.value = { x: x + (position.x - node.position.x) * scale, y: y + (position.y - node.position.y) * scale, scale }
}

function onKeydown(event: KeyboardEvent) {
  const target = event.target as HTMLElement
  if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
    const rect = target.getBoundingClientRect()
    event.preventDefault()
    openContext(target, { x: rect.left + Math.min(48, rect.width / 2), y: rect.top + Math.min(32, rect.height / 2) })
    return
  }
  if (target.closest('button, input, textarea, [contenteditable]')) return
  if (event.code === 'Space') { event.preventDefault(); space.value = true }
  if (event.key === 'Escape') { chooseTool('select'); emit('select', null) }
  if (event.key === '+' || event.key === '=') map.adjustZoom(1.2)
  if (event.key === '-') map.adjustZoom(1 / 1.2)
  if (event.key === '0') map.fit()
  if (props.rootStream && ['ArrowDown', 'ArrowUp', 'PageDown', 'PageUp'].includes(event.key)) {
    event.preventDefault()
    movedViewport = true
    const direction = event.key.endsWith('Down') ? -1 : 1
    const step = event.key.startsWith('Page') ? size.value.height * 0.78 : 120
    const current = viewport.value
    viewport.value = { ...current, y: current.y + direction * step }
    requestRoots(current.y)
  }
  if (event.key === 'Delete' && canRemove.value && !props.busy) { event.preventDefault(); emit('remove') }
}

function noteAtCenter() {
  emit('create', 'note', map.insertionPoint('note'))
  chooseTool('select')
}

function selected(node: CanvasNode) { return props.selection?.type === 'node' && props.selection.id === node.id }
function isEntry(node: CanvasNode) { return !!node.domainId && props.data.assetNodeIds.get(node.domainId) === node.id }
function fitEntries() {
  const first = props.data.nodes.find(isEntry)
  if (!props.data.root_tree) {
    map.fit()
    if (viewport.value.scale >= 0.62 || !first) return
  }
  if (!first) { map.fit(); return }
  const { width } = size.value
  const scale = props.data.root_tree ? canvasEntryScale(width) : 0.72
  viewport.value = { scale, x: Math.min(111, width * 0.18) - first.position.x * scale, y: 34 - first.position.y * scale }
}

function streamAnchor(direction: RootDirection) {
  const roots = props.data.nodes.filter(node => node.domainId && props.rootStream?.ids.has(node.domainId) && isEntry(node))
  const node = direction === 'next' ? roots.at(-1) : roots[0]
  return node ? { id: node.id, position: node.position } : undefined
}

function revealChild(parentId: string, childId: string, preserveScale = false) {
  const child = props.data.nodes.find(node => node.id === childId)
  if (!child) return
  const { x, y, scale } = viewport.value
  const left = x + child.position.x * scale, top = y + child.position.y * scale
  const right = left + child.size.width * scale, bottom = top + child.size.height * scale
  const dx = Math.max(44 - left, Math.min(0, size.value.width - 30 - right))
  const dy = Math.max(20 - top, Math.min(0, size.value.height - 65 - bottom))
  if (!dx && !dy) return
  movedViewport = true
  if (preserveScale) viewport.value = { x: x + dx, y: y + dy, scale }
  else map.focusNodes([parentId, childId])
}

function toggleBranch(id: string) {
  activeBranch.value = id
  emit('toggleBranch', id)
}

function continueBranch(id: string) {
  activeBranch.value = id
  emit('moreBranch', id)
}

function locateParent(id: string) {
  movedViewport = true
  map.focusNodes([id])
  emit('select', { type: 'node', id })
}
onMounted(fitEntries)
defineExpose({ insertionPoint: map.insertionPoint, focusNodes: map.focusNodes, focusRegion: map.focusRegion,
  fit: fitEntries, keepInView, revealChild, streamAnchor })
</script>

<template>
  <section class="stage-shell" :aria-label="t('workspace_canvas.title')">
    <div ref="surface" class="canvas-surface" data-testid="workspace-canvas-surface" :data-quarter="data.quarter?.id"
      :data-root-tree="data.root_tree || undefined" tabindex="0" :style="gridStyle"
      :data-zoom-mode="isOverview ? 'overview' : compact ? 'compact' : 'detail'"
      :class="[`mode-${tool}`, { moving, 'panning-key': space, 'map-scale': isOverview }]"
      @pointerdown="map.pointerDown" @pointermove="pointerMove" @pointercancel="map.cancelGesture" @wheel.prevent="wheel"
      @keydown="onKeydown" @contextmenu.prevent="rightClick" @dblclick="zoomIntoMap">
      <CanvasOverviewLayer v-if="isOverview" :nodes="renderedNodes" :relations="shownRelations" :edges="data.edges"
        :viewport="viewport" :size="size" :selected-id="selectedNode?.id" />
      <div v-if="!isOverview" class="canvas-scene" :style="sceneStyle">
        <div class="scene-layer frame-layer">
          <CanvasItem v-for="node in frames" :key="node.id" :node="node" :active="selected(node)"
            :linked="connectStart?.id === node.id || hoveredTarget === node.id" @press="(event, handle) => map.nodeDown(event, node, handle)"
            @focus="emit('select', { type: 'node', id: node.id })" @open="open(node.id)" />
        </div>
        <CanvasArrows :paths="visiblePaths" :selected-id="selectedEdge" :preview="connectionPreview"
          @select="id => emit('select', { type: 'edge', id })" @open-relation="id => emit('openRelation', id)" />
        <div class="scene-layer card-layer">
          <CanvasItem v-for="node in items" :key="node.id" :node="node" :active="selected(node)"
            :entry="isEntry(node)" :compact="compact" :quarter-id="data.quarter?.id"
            :tree="!!data.quarter" :expanded="!!node.expandedChildren"
            :busy="expandingNodeId === node.id"
            :linked="connectStart?.id === node.id || hoveredTarget === node.id" @press="(event, handle) => map.nodeDown(event, node, handle)"
            @focus="emit('select', { type: 'node', id: node.id })" @open="open(node.id)"
            @toggle="toggleBranch(node.id)" />
          <CanvasBranchContinuation v-for="marker in visibleContinuations" :key="marker.parentId"
            :marker="marker" :busy="expandingNodeId === marker.parentId" @continue="continueBranch(marker.parentId)" />
        </div>
        <div v-if="framePreview" class="frame-preview" :style="previewStyle" />
      </div>

      <CanvasToolbar :tool="tool" :can-link="data.access.can_link_requirements" @choose="chooseTool" />
      <CanvasBranchContext v-if="branchContext" v-bind="branchContext" :busy="expandingNodeId === branchContext.parent.id"
        @locate="locateParent(branchContext.parent.id)" @continue="continueBranch(branchContext.parent.id)" />
      <div v-if="!data.nodes.length && tool === 'select'" class="stage-empty">
        <div class="empty-symbol"><Workflow :size="30" /></div>
        <h2>{{ t('workspace_canvas.empty_title') }}</h2>
        <div class="empty-actions" @pointerdown.stop>
          <button type="button" class="empty-primary" :disabled="busy" @click="noteAtCenter"><Plus :size="16" />{{ t('workspace_canvas.tool.note') }}</button>
        </div>
      </div>
      <div v-if="cursorHint" class="cursor-hint" aria-live="polite">{{ cursorHint }}</div>
      <div v-else-if="isOverview" class="map-hint">{{ t('workspace_canvas.domains.map_zoom') }}</div>
      <div v-else-if="!branchContext && (rootStream?.next || rootStream?.loading)" class="map-hint root-guidance">
        {{ t(rootStream.loading ? 'common.loading' : 'workspace_canvas.tree.pan_more') }}
      </div>
      <CanvasRelationLegend :relations="data.relations" :active="relationFilter"
        @choose="type => relationFilter = relationFilter === type ? null : type" />
      <div class="viewport-controls canvas-control" @pointerdown.stop>
        <button class="control-button" type="button" :title="t('workspace_canvas.zoom_out')" :aria-label="t('workspace_canvas.zoom_out')"
          @click="map.adjustZoom(1 / 1.2)"><Minus :size="17" /></button>
        <output class="zoom-value" :title="t('workspace_canvas.zoom_hint')">{{ Math.round(viewport.scale * 100) }}%</output>
        <button class="control-button" type="button" :title="t('workspace_canvas.zoom_in')" :aria-label="t('workspace_canvas.zoom_in')"
          @click="map.adjustZoom(1.2)"><Plus :size="17" /></button>
        <button class="control-button fit-button" type="button" :title="t('workspace_canvas.fit')" :aria-label="t('workspace_canvas.fit')"
          @click="map.fit(true)"><Maximize2 :size="15" /></button>
      </div>
    </div>
    <slot />
  </section>
</template>

<style scoped>
.stage-shell { position: relative; flex: 1; min-width: 0; min-height: 0; }
.canvas-surface {
  position: absolute;
  inset: 0;
  isolation: isolate;
  overflow: hidden;
  outline: none;
  color: var(--canvas-ink);
  background-color: var(--canvas-paper);
  background-image: radial-gradient(circle, var(--canvas-dot) 1px, transparent 1.1px);
  cursor: default;
  touch-action: none;
  overscroll-behavior: contain;
}
.canvas-surface:focus-visible { box-shadow: inset 0 0 0 2px var(--canvas-accent); }
.map-scale { background-image: radial-gradient(circle, #d4e1ed 0.8px, transparent 1px); }
.map-hint { position: absolute; top: 16px; left: 67px; padding: 4px 7px; color: #516e88; font-size: 12px; pointer-events: none; }
.mode-note, .mode-frame, .mode-arrow, .mode-relation,
.mode-arrow :deep(.canvas-item:not(.kind-frame)), .mode-relation :deep(.canvas-item:not(.kind-frame)) { cursor: crosshair; }
.mode-pan, .mode-pan :deep(.canvas-item), .panning-key, .panning-key :deep(.canvas-item) { cursor: grab; }
.canvas-surface.moving, .canvas-surface.moving :deep(.canvas-item) { cursor: grabbing; }
.canvas-scene, .scene-layer { position: absolute; inset: 0 auto auto 0; width: 0; height: 0; pointer-events: none; }
.canvas-scene { transform-origin: 0 0; }
.card-layer :deep(.canvas-item.active) { z-index: 2; }
.frame-preview { position: absolute; border-radius: 10px; border: 1px dashed var(--canvas-accent); background: #587bda1a; }
.stage-empty {
  position: absolute;
  top: 49%;
  left: 50%;
  width: min(380px, calc(100% - 116px));
  display: grid;
  justify-items: center;
  gap: 12px;
  text-align: center;
  transform: translate(-50%, -50%);
  pointer-events: none;
}
.empty-symbol { display: grid; place-items: center; width: 64px; height: 64px; border: 1px solid var(--canvas-line); border-radius: 18px; color: var(--canvas-accent); background: var(--canvas-chrome); box-shadow: 0 4px 13px #2643690c; }
.stage-empty h2 { margin: 0; }
.stage-empty h2 { font-size: clamp(20px, 2.5vw, 25px); letter-spacing: -.035em; }
.empty-actions { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; pointer-events: auto; }
.empty-primary { display: inline-flex; align-items: center; gap: 5px; min-height: 36px; border-radius: 8px; border: 1px solid var(--canvas-line); padding: 0 12px; font: inherit; font-size: 12px; font-weight: 700; cursor: pointer; }
.empty-primary { color: #fff; background: var(--canvas-accent); border-color: var(--canvas-accent); }
.empty-primary:hover { filter: brightness(1.1); }
.canvas-control { position: absolute; z-index: 3; display: flex; align-items: center; gap: 2px; padding: 3px; border: 1px solid var(--canvas-line); border-radius: 9px; background: var(--canvas-chrome); box-shadow: 0 4px 12px #263c5d12; }
.viewport-controls { bottom: 16px; right: 16px; }
.control-button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 33px; min-width: 34px; border: none; border-radius: 6px; padding: 0 6px; background: transparent; color: var(--canvas-muted); font: inherit; font-size: 12px; cursor: pointer; }
.control-button:is(:hover, :focus-visible) { background: var(--canvas-hover); color: var(--canvas-ink); }
.zoom-value { min-width: 44px; text-align: center; font-size: 12px; font-weight: 650; font-variant-numeric: tabular-nums; }
.fit-button { border-left: 1px solid var(--canvas-line); }
.cursor-hint { position: absolute; bottom: 67px; left: 50%; max-width: calc(100% - 24px); transform: translateX(-50%); padding: 6px 10px; border-radius: 7px; background: #263b5b; color: #fff; text-align: center; font-size: 12px; pointer-events: none; }
@media (min-width: 800px) { .cursor-hint { bottom: 22px; } }
@media (max-width: 650px) { .stage-empty { left: 53%; } .viewport-controls { bottom: 10px; right: 8px; } }
</style>
