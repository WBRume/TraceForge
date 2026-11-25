<script setup lang="ts">
import { computed, onMounted, onScopeDispose, shallowRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Maximize2, Minus, Plus, Workflow } from '@/components/icons'
import { useAuthStore } from '@/stores/auth'
import { getApiServerUrl } from '@/utils/api'
import CanvasArrows from './CanvasArrows.vue'
import CanvasItem from './CanvasItem.vue'
import CanvasRelationLegend from './CanvasRelationLegend.vue'
import CanvasToolbar from './CanvasToolbar.vue'
import type { CanvasContextRequest, CanvasContextTarget } from './contextMenu'
import { sourceIcons, type CanvasConnection, type CanvasGraph, type CanvasNode, type CanvasRelationType, type CanvasSelection,
  type CanvasTool, type NodePatch, type Point, type Size } from './model'
import { useCanvasInteraction } from './useCanvasInteraction'

const props = defineProps<{ workspaceId: string; data: CanvasGraph; selection: CanvasSelection | null; busy: boolean }>()
const emit = defineEmits<{
  select: [selection: CanvasSelection | null]
  create: [kind: 'note' | 'frame', position: Point, size?: Size]
  update: [nodeId: string, patch: NodePatch]
  connect: [source: string, target: string, mode: CanvasConnection]
  open: [id: string]
  remove: []
  openRelation: [id: string]
  context: [request: CanvasContextRequest]
}>()
const { t } = useI18n()
const auth = useAuthStore()
const surface = useTemplateRef<HTMLElement>('surface')
const tool = shallowRef<CanvasTool>('select')
const relationFilter = shallowRef<CanvasRelationType | null>(null)
const size = shallowRef<Size>({ width: 0, height: 0 })
let observer: ResizeObserver | undefined
onMounted(() => {
  if (!surface.value) return
  size.value = { width: surface.value.clientWidth, height: surface.value.clientHeight }
  observer = new ResizeObserver(([entry]) => {
    if (entry) size.value = { width: entry.contentRect.width, height: entry.contentRect.height }
  })
  observer.observe(surface.value)
})
onScopeDispose(() => observer?.disconnect())
const map = useCanvasInteraction({
  surface,
  viewportKey: `workspace-asset-graph:${getApiServerUrl()}:${auth.user?.id}:${props.workspaceId}`,
  nodes: () => props.data.nodes,
  tool: () => tool.value,
  busy: () => props.busy,
  select: selection => emit('select', selection),
  create: (...args) => { emit('create', ...args); chooseTool('select') },
  update: (id, patch) => emit('update', id, patch),
  connect: (source, target, mode) => emit('connect', source, target, mode),
})
const { viewport, moving, space, connectStart, hoveredTarget, renderedNodes, framePreview, connectionPreview } = map
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
const selectedNode = computed(() => props.selection?.type === 'node' ? props.data.nodes.find(node => node.id === props.selection?.id) : null)
const selectedEdge = computed(() => props.selection?.type === 'edge' ? props.selection.id : undefined)
const canRemove = computed(() => selectedEdge.value || (selectedNode.value && !selectedNode.value.automatic))
const shownRelations = computed(() => relationFilter.value
  ? props.data.relations.filter(link => link.relation_type === relationFilter.value) : props.data.relations)
watch(() => props.data.relations, links => {
  if (!links.some(link => link.relation_type === relationFilter.value)) relationFilter.value = null
})
const sceneStyle = computed(() => ({ transform: `translate(${viewport.value.x}px, ${viewport.value.y}px) scale(${viewport.value.scale})` }))
const gridStyle = computed(() => ({
  backgroundPosition: `${viewport.value.x}px ${viewport.value.y}px`,
  backgroundSize: `${Math.max(8, viewport.value.scale * 22)}px ${Math.max(8, viewport.value.scale * 22)}px`,
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
  const scope: CanvasContextTarget = nodeId ? { type: 'node', id: nodeId }
    : relationId ? { type: 'relation', id: relationId }
    : edgeId ? { type: 'edge', id: edgeId } : { type: 'surface' }
  const rect = element.getBoundingClientRect()
  const anchor = { x: client.x - rect.left, y: client.y - rect.top }
  const { x, y, scale } = viewport.value
  map.cancelConnection()
  emit('context', {
    target: scope,
    anchor,
    position: { x: (anchor.x - x) / scale, y: (anchor.y - y) / scale },
    size: { width: rect.width, height: rect.height },
    restoreFocus: target.closest<HTMLElement>('[tabindex]') || element,
  })
}

function rightClick(event: MouseEvent) {
  if (event.target instanceof Element) openContext(event.target, { x: event.clientX, y: event.clientY })
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
  if (event.key === 'Delete' && canRemove.value && !props.busy) { event.preventDefault(); emit('remove') }
}

function noteAtCenter() {
  emit('create', 'note', map.insertionPoint('note'))
  chooseTool('select')
}

function selected(node: CanvasNode) { return props.selection?.type === 'node' && props.selection.id === node.id }
defineExpose({ insertionPoint: map.insertionPoint, focusNodes: map.focusNodes, fit: map.fit })
</script>

<template>
  <section class="stage-shell" :aria-label="t('workspace_canvas.title')">
    <div ref="surface" class="canvas-surface" data-testid="workspace-canvas-surface" tabindex="0" :style="gridStyle"
      :class="[`mode-${tool}`, { moving, 'panning-key': space }]"
      @pointerdown="map.pointerDown" @pointermove="map.pointerMove" @pointercancel="map.cancelGesture" @wheel.prevent="map.wheel"
      @keydown="onKeydown" @contextmenu.prevent="rightClick">
      <div class="canvas-scene" :style="sceneStyle">
        <div v-for="group in data.groups" :key="group.kind" class="asset-lane" :style="{ left: `${group.position.x}px`, top: `${group.position.y}px` }">
          <component :is="sourceIcons[group.kind]" :size="17" />{{ t(`workspace_canvas.kind.${group.kind}`) }}
        </div>
        <div class="scene-layer frame-layer">
          <CanvasItem v-for="node in frames" :key="node.id" :node="node" :active="selected(node)"
            :linked="connectStart?.id === node.id || hoveredTarget === node.id" @press="(event, handle) => map.nodeDown(event, node, handle)"
            @focus="emit('select', { type: 'node', id: node.id })" @open="open(node.id)" />
        </div>
        <CanvasArrows :nodes="renderedNodes" :visible-ids="visibleIds" :edges="data.edges" :relations="shownRelations" :selected-id="selectedEdge"
          :preview="connectionPreview"
          @select="id => emit('select', { type: 'edge', id })" @open-relation="id => emit('openRelation', id)" />
        <div class="scene-layer card-layer">
          <CanvasItem v-for="node in items" :key="node.id" :node="node" :active="selected(node)"
            :linked="connectStart?.id === node.id || hoveredTarget === node.id" @press="(event, handle) => map.nodeDown(event, node, handle)"
            @focus="emit('select', { type: 'node', id: node.id })" @open="open(node.id)" />
        </div>
        <div v-if="framePreview" class="frame-preview" :style="previewStyle" />
      </div>

      <CanvasToolbar :tool="tool" :can-link="data.access.can_link_requirements" @choose="chooseTool" />
      <div v-if="!data.nodes.length && tool === 'select'" class="stage-empty">
        <div class="empty-symbol"><Workflow :size="30" /></div>
        <h2>{{ t('workspace_canvas.empty_title') }}</h2>
        <div class="empty-actions" @pointerdown.stop>
          <button type="button" class="empty-primary" :disabled="busy" @click="noteAtCenter"><Plus :size="16" />{{ t('workspace_canvas.tool.note') }}</button>
        </div>
      </div>
      <div v-if="cursorHint" class="cursor-hint" aria-live="polite">{{ cursorHint }}</div>
      <CanvasRelationLegend :relations="data.relations" :active="relationFilter"
        @choose="type => relationFilter = relationFilter === type ? null : type" />
      <div class="viewport-controls canvas-control" @pointerdown.stop>
        <button class="control-button" type="button" :title="t('workspace_canvas.zoom_out')" :aria-label="t('workspace_canvas.zoom_out')"
          @click="map.adjustZoom(1 / 1.2)"><Minus :size="17" /></button>
        <output class="zoom-value" :title="t('workspace_canvas.zoom_hint')">{{ Math.round(viewport.scale * 100) }}%</output>
        <button class="control-button" type="button" :title="t('workspace_canvas.zoom_in')" :aria-label="t('workspace_canvas.zoom_in')"
          @click="map.adjustZoom(1.2)"><Plus :size="17" /></button>
        <button class="control-button fit-button" type="button" :title="t('workspace_canvas.fit')" :aria-label="t('workspace_canvas.fit')"
          @click="map.fit"><Maximize2 :size="15" /></button>
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
.mode-note, .mode-frame, .mode-arrow, .mode-relation,
.mode-arrow :deep(.canvas-item:not(.kind-frame)), .mode-relation :deep(.canvas-item:not(.kind-frame)) { cursor: crosshair; }
.mode-pan, .mode-pan :deep(.canvas-item), .panning-key, .panning-key :deep(.canvas-item) { cursor: grab; }
.canvas-surface.moving, .canvas-surface.moving :deep(.canvas-item) { cursor: grabbing; }
.canvas-scene, .scene-layer { position: absolute; inset: 0 auto auto 0; width: 0; height: 0; pointer-events: none; }
.canvas-scene { transform-origin: 0 0; }
.asset-lane { position: absolute; display: flex; align-items: center; gap: 6px; width: max-content;
  color: #0369a1; font-size: 15px; font-weight: 750; padding: 4px 8px; border-radius: 6px; background: #e0f2fe; }
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
