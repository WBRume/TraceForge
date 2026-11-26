<script setup lang="ts">
import { computed, onMounted, onScopeDispose, shallowRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Maximize2, Minus, Plus } from '@/components/icons'
import { fittedViewport, zoomAround, type Point, type Viewport } from '@/utils/canvasViewport'
import DiagramEdgeGraphic from './DiagramEdgeGraphic.vue'
import DiagramNodeGraphic from './DiagramNodeGraphic.vue'
import { diagramBounds, diagramDrawings, inside } from './diagramGeometry'
import { drawingSvg } from './diagramExport'
import { GRID, isContainer, minNodeSize, shapeNames, snapToGrid, type DiagramDocument,
  type DiagramNode, type DiagramTool, type NodeEdit, type Shape } from './diagramModel'

const props = defineProps<{
  doc: DiagramDocument
  tool: DiagramTool
  pending: Shape | null
  selected: ReadonlySet<string>
  selectedEdge: string | null
  snap: boolean
}>()
const emit = defineEmits<{
  place: [shape: Shape, position: Point]
  select: [ids: string[]]
  edge: [id: string]
  join: [source: string, target: string, y: number]
  update: [nodes: ReadonlyMap<string, NodeEdit>]
  openFile: [file: File]
}>()
const { t } = useI18n()
const svg = useTemplateRef<SVGSVGElement>('svg')
const art = useTemplateRef<SVGGElement>('art')
const viewport = shallowRef<Viewport>({ x: 22, y: 22, scale: 1 })
const preview = shallowRef<ReadonlyMap<string, NodeEdit>>(new Map())
const space = shallowRef(false)
const source = shallowRef<string>()
const cursor = shallowRef<Point>()
const marquee = shallowRef<(Point & { width: number; height: number })>()
type Gesture = { id: number; anchor: Point; last: Point } & (
  | { kind: 'pan'; view: Viewport }
  | { kind: 'move'; nodes: DiagramNode[] }
  | { kind: 'resize'; node: DiagramNode }
  | { kind: 'area'; previous: string[] }
  | { kind: 'link' }
)
const gesture = shallowRef<Gesture>()

const nodes = computed(() => props.doc.nodes.map(node => {
  const update = preview.value.get(node.id)
  return update ? { ...node, ...update } : node
}))
const selected = computed(() => nodes.value.filter(node => props.selected.has(node.id)))
const index = computed(() => new Map(nodes.value.map(node => [node.id, node])))
const frames = computed(() => nodes.value.filter(node => isContainer(node.shape)))
const items = computed(() => nodes.value.filter(node => !isContainer(node.shape)))
const drawings = computed(() => diagramDrawings(nodes.value, props.doc.edges))
const activeLine = computed(() => drawings.value.find(drawing => drawing.edge.id === props.selectedEdge))
const port = computed(() => selected.value.length === 1 && !isContainer(selected.value[0].shape) ? selected.value[0] : null)
const sourcePoint = computed(() => {
  const node = source.value && index.value.get(source.value)
  return node ? { x: node.x + node.width, y: node.y + node.height / 2 } : null
})
const gridStyle = computed(() => {
  const step = Math.max(8, GRID * viewport.value.scale)
  return { backgroundSize: `${step}px ${step}px`, backgroundPosition: `${viewport.value.x}px ${viewport.value.y}px` }
})
const transform = computed(() => `translate(${viewport.value.x} ${viewport.value.y}) scale(${viewport.value.scale})`)
const hint = computed(() => props.pending ? 'place' : source.value ? 'connectTarget' : props.tool === 'connect' ? 'connect' : 'select')
const moving = computed(() => props.tool === 'pan' || space.value || gesture.value?.kind === 'pan')

function focus() {
  svg.value?.focus({ preventScroll: true })
}

function screenPoint(event: Pick<PointerEvent, 'clientX' | 'clientY'>): Point {
  const bounds = svg.value!.getBoundingClientRect()
  return { x: event.clientX - bounds.left, y: event.clientY - bounds.top }
}

function world(point: Point): Point {
  const { x, y, scale } = viewport.value
  return { x: (point.x - x) / scale, y: (point.y - y) / scale }
}

function position(value: number) {
  const bounded = Math.min(100000, Math.max(-100000, value))
  return props.snap ? snapToGrid(bounded) : Math.round(bounded)
}

function kindAt(target: EventTarget | null, key: string) {
  return target instanceof Element ? target.closest(`[${key}]`)?.getAttribute(key) : undefined
}

function begin(event: PointerEvent) {
  if ((event.button !== 0 && event.button !== 1) || gesture.value || !svg.value) return
  event.preventDefault()
  focus()
  const point = screenPoint(event)
  const anchor = { id: event.pointerId, anchor: point, last: point }
  const target = event.target
  const id = kindAt(target, 'data-diagram-node')
  const node = id && index.value.get(id)
  const handle = kindAt(target, 'data-diagram-resize')
  const nodeToResize = handle && index.value.get(handle)
  const start = kindAt(target, 'data-diagram-port')
  const edge = kindAt(target, 'data-diagram-edge')

  if (moving.value || event.button === 1) {
    gesture.value = { ...anchor, kind: 'pan', view: viewport.value }
  } else if (props.pending) {
    const { x, y } = world(point)
    emit('place', props.pending, { x: position(x), y: position(y) })
  } else if (start) {
    source.value = start
    cursor.value = world(point)
    gesture.value = { ...anchor, kind: 'link' }
  } else if (props.tool === 'connect' || source.value) {
    if (node && !isContainer(node.shape)) {
      if (source.value) {
        emit('join', source.value, node.id, world(point).y)
        source.value = undefined
      } else {
        source.value = node.id
        cursor.value = world(point)
      }
    } else source.value = undefined
  } else if (nodeToResize) {
    gesture.value = { ...anchor, kind: 'resize', node: nodeToResize }
  } else if (node) {
    const selected = new Set(props.selected)
    if (event.shiftKey && selected.has(node.id)) {
      selected.delete(node.id)
      emit('select', [...selected])
      return
    }
    const ids = !event.shiftKey && !selected.has(node.id) ? new Set([node.id]) : selected.add(node.id)
    emit('select', [...ids])
    for (const frame of frames.value.filter(frame => ids.has(frame.id))) {
      for (const member of nodes.value) if (inside(member, frame)) ids.add(member.id)
    }
    gesture.value = { ...anchor, kind: 'move', nodes: nodes.value.filter(item => ids.has(item.id)) }
  } else if (edge) {
    emit('edge', edge)
  } else {
    gesture.value = { ...anchor, kind: 'area', previous: event.shiftKey ? [...props.selected] : [] }
    if (!event.shiftKey) emit('select', [])
  }
  if (gesture.value) svg.value.setPointerCapture(event.pointerId)
}

function move(event: PointerEvent) {
  if (!svg.value) return
  const point = screenPoint(event)
  if (source.value) cursor.value = world(point)
  const active = gesture.value
  if (!active || active.id !== event.pointerId) return
  const x = point.x - active.anchor.x
  const y = point.y - active.anchor.y
  gesture.value = { ...active, last: point }
  if (active.kind === 'pan') {
    viewport.value = { ...active.view, x: active.view.x + x, y: active.view.y + y }
  } else if (active.kind === 'move' || active.kind === 'resize') {
    if (Math.hypot(x, y) < 3 && !preview.value.size) return
    const dx = x / viewport.value.scale, dy = y / viewport.value.scale
    if (active.kind === 'move') {
      const start = active.nodes[0]
      const deltaX = position(start.x + dx) - start.x, deltaY = position(start.y + dy) - start.y
      preview.value = new Map(active.nodes.map(node => [node.id, {
        x: Math.min(100000, Math.max(-100000, node.x + deltaX)),
        y: Math.min(100000, Math.max(-100000, node.y + deltaY)),
      }]))
    } else {
      const min = minNodeSize(active.node.shape)
      preview.value = new Map([[active.node.id, {
        width: Math.max(min.width, position(active.node.width + dx)),
        height: Math.max(min.height, position(active.node.height + dy)),
      }]])
    }
  } else if (active.kind === 'area' && Math.hypot(x, y) >= 3) {
    const a = world(active.anchor), b = world(point)
    marquee.value = { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), width: Math.abs(a.x - b.x), height: Math.abs(a.y - b.y) }
  }
}

function finish(event: PointerEvent) {
  const active = gesture.value
  if (!active || active.id !== event.pointerId) return
  if (active.kind === 'link' && source.value) {
    const point = screenPoint(event)
    if (Math.hypot(point.x - active.anchor.x, point.y - active.anchor.y) >= 5) {
      const id = kindAt(document.elementFromPoint(event.clientX, event.clientY), 'data-diagram-node')
      if (id && index.value.has(id) && !isContainer(index.value.get(id)!.shape)) emit('join', source.value, id, world(point).y)
      source.value = undefined
    }
  } else if (active.kind === 'area' && marquee.value) {
    const ids = new Set(active.previous)
    for (const node of nodes.value) if (inside(node, marquee.value)) ids.add(node.id)
    emit('select', [...ids])
  } else if (preview.value.size) {
    emit('update', preview.value)
  }
  clearGesture()
}

function clearGesture() {
  gesture.value = undefined
  marquee.value = undefined
  preview.value = new Map()
}

function cancel() {
  source.value = undefined
  clearGesture()
}

function drop(event: DragEvent) {
  const file = event.dataTransfer?.files[0]
  if (file) { emit('openFile', file); return }
  const shape = event.dataTransfer?.getData('application/x-traceforge-shape') as Shape
  if (!shapeNames.includes(shape)) return
  const { x, y } = world(screenPoint(event))
  emit('place', shape, { x: position(x), y: position(y) })
  focus()
}

function scaleAt(point: Point, scale: number) {
  viewport.value = zoomAround(viewport.value, point, Math.min(2.5, Math.max(.025, scale)))
}

function wheel(event: WheelEvent) {
  if (!gesture.value) scaleAt(screenPoint(event), viewport.value.scale * Math.exp(-event.deltaY * .0016))
}

function zoom(factor: number) {
  if (svg.value) scaleAt({ x: svg.value.clientWidth / 2, y: svg.value.clientHeight / 2 }, viewport.value.scale * factor)
}

function fit() {
  if (!svg.value) return
  const size = { width: svg.value.clientWidth, height: svg.value.clientHeight }
  if (!nodes.value.length) { viewport.value = { x: 22, y: 22, scale: 1 }; return }
  const bounds = diagramBounds(nodes.value, drawings.value)
  viewport.value = fittedViewport([{ position: { x: bounds.left, y: bounds.top }, size: bounds }], size,
    { padding: size.width < 550 ? 48 : 72, verticalOffset: 0 })
}

function exportSvg() {
  if (!art.value) throw new Error('Drawing is unavailable')
  return drawingSvg(art.value, diagramBounds(nodes.value, drawings.value))
}

watch(() => [props.tool, props.pending], cancel)
let observer: ResizeObserver | undefined
onMounted(() => {
  observer = new ResizeObserver(() => {
    if (svg.value?.clientWidth && svg.value.clientHeight) {
      fit()
      observer?.disconnect()
    }
  })
  if (svg.value) observer.observe(svg.value)
})
onScopeDispose(() => observer?.disconnect())

defineExpose({ fit, exportSvg, focus, cancel, zoom })
</script>

<template>
  <section class="diagram-stage" :style="gridStyle">
    <svg ref="svg" class="drawing-surface" :class="{ moving, linking: tool === 'connect' || source, placing: pending }"
      data-testid="diagram-canvas" tabindex="0" :aria-label="t('diagram.stage.label')"
      @pointerdown="begin" @pointermove="move" @pointerup="finish" @pointercancel="cancel" @lostpointercapture="clearGesture"
      @wheel.prevent="wheel" @dragover.prevent @drop.prevent="drop" @keydown.space.prevent="space = true"
      @keyup.space.prevent="space = false" @blur="space = false">
      <g :transform="transform">
        <path v-if="activeLine" :d="activeLine.geometry.path" fill="none" stroke="#94ddfc" stroke-width="8" pointer-events="none" />
        <g ref="art" font-family="Inter, 'Segoe UI', 'Microsoft YaHei UI', sans-serif">
          <DiagramNodeGraphic v-for="node in frames" :key="node.id" :node="node" />
          <DiagramEdgeGraphic v-for="item in drawings" :key="item.edge.id" :edge="item.edge" :geometry="item.geometry" />
          <DiagramNodeGraphic v-for="node in items" :key="node.id" :node="node" />
        </g>
        <rect v-for="node in selected" :key="node.id" :x="node.x - 4" :y="node.y - 4"
          :width="node.width + 8" :height="node.height + 8" rx="5" fill="none" stroke="#0284c7" stroke-width="1.5"
          vector-effect="non-scaling-stroke" pointer-events="none" />
        <rect v-if="selected.length === 1 && tool === 'select' && !pending" :x="selected[0].x + selected[0].width - 4"
          :y="selected[0].y + selected[0].height - 4" width="10" height="10" rx="2" fill="#ffffff" stroke="#0284c7"
          class="resize-handle" :data-diagram-resize="selected[0].id" />
        <circle v-if="port && tool === 'select' && !pending && !source" :cx="port.x + port.width + 9"
          :cy="port.y + port.height / 2" r="6" fill="#ffffff" stroke="#0284c7" stroke-width="1.5"
          class="port-handle" :data-diagram-port="port.id">
          <title>{{ t('diagram.tool.connect') }}</title>
        </circle>
        <line v-if="sourcePoint && cursor" :x1="sourcePoint.x" :y1="sourcePoint.y" :x2="cursor.x" :y2="cursor.y"
          stroke="#0284c7" stroke-width="1.5" stroke-dasharray="6 4" pointer-events="none" />
        <rect v-if="marquee" v-bind="marquee" fill="#dbefff88" stroke="#0284c7" stroke-dasharray="5 4"
          vector-effect="non-scaling-stroke" pointer-events="none" />
      </g>
    </svg>
    <p v-if="!doc.nodes.length && !pending" class="empty-canvas">{{ t('diagram.stage.empty') }}</p>
    <div class="canvas-footer">
      <span class="canvas-tip">{{ t('diagram.stage.' + hint) }}</span>
      <div class="zoom-controls">
        <button type="button" :title="t('diagram.tool.zoomOut')" :aria-label="t('diagram.tool.zoomOut')" @click="zoom(1 / 1.2)"><Minus :size="16" /></button>
        <output>{{ Math.round(viewport.scale * 100) }}%</output>
        <button type="button" :title="t('diagram.tool.zoomIn')" :aria-label="t('diagram.tool.zoomIn')" @click="zoom(1.2)"><Plus :size="16" /></button>
        <button type="button" :title="t('diagram.tool.fit')" :aria-label="t('diagram.tool.fit')" @click="fit"><Maximize2 :size="16" /></button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.diagram-stage { position: relative; min-width: 0; min-height: 0; overflow: hidden; background-color: #f2f6fa; background-image: radial-gradient(#bdccdc 0.75px, transparent 0.95px); }
.drawing-surface { position: absolute; inset: 0; width: 100%; height: 100%; touch-action: none; outline: none; user-select: none; }
.drawing-surface :deep([data-diagram-node]) { cursor: move; }
.drawing-surface :deep([data-diagram-edge]) { cursor: pointer; }
.drawing-surface.moving, .drawing-surface.moving :deep([data-diagram-node]) { cursor: grab; }
.drawing-surface.moving:active { cursor: grabbing; }
.drawing-surface.linking, .drawing-surface.linking :deep([data-diagram-node]), .drawing-surface.placing { cursor: crosshair; }
.resize-handle { cursor: nwse-resize; }
.port-handle { cursor: crosshair; }
.empty-canvas { position: absolute; left: 50%; top: 45%; transform: translate(-50%, -50%); padding: 12px 16px; border: 1px solid #dce5ef; border-radius: 8px; background: #f8fafc; color: #52677d; font-size: 13px; text-align: center; pointer-events: none; }
.canvas-footer { position: absolute; inset: auto 14px 14px; display: flex; gap: 10px; align-items: flex-end; justify-content: space-between; pointer-events: none; }
.canvas-tip, .zoom-controls { border: 1px solid #dce5ef; border-radius: 8px; background: #ffffffed; color: #52677d; font-size: 12px; }
.canvas-tip { padding: 8px 10px; }
.zoom-controls { display: flex; align-items: center; flex-shrink: 0; gap: 5px; padding: 3px; pointer-events: auto; }
.zoom-controls output { min-width: 40px; text-align: center; font-variant-numeric: tabular-nums; }
.zoom-controls button { display: grid; place-items: center; width: 30px; height: 28px; border: 0; border-radius: 5px; color: #3b536d; background: transparent; cursor: pointer; }
.zoom-controls button:hover { background: #ecf5fc; }
@media (max-width: 900px) { .canvas-tip { display: none; } .canvas-footer { justify-content: flex-end; } }
</style>
