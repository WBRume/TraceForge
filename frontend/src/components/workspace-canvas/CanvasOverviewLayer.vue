<script setup lang="ts">
import { useTemplateRef, watchEffect } from 'vue'
import { useI18n } from 'vue-i18n'
import { center, type Viewport } from './geometry'
import { relationStyles } from './relationStyles'
import type { CanvasEdge, CanvasGraphRelation, CanvasNode, CanvasRegion, Point, Size } from './model'

const props = defineProps<{
  nodes: CanvasNode[]; regions: CanvasRegion[]; relations: CanvasGraphRelation[]; edges: CanvasEdge[];
  viewport: Viewport; size: Size; overview: boolean; featured?: boolean; tree?: boolean; selectedId?: string;
}>()
const canvas = useTemplateRef<HTMLCanvasElement>('canvas')
const { t } = useI18n()

const colors = {
  delivery: ['#edf4fd', '#a4bbdc', '#305d95'], standalone: ['#eef6f3', '#b4d2c7', '#356b60'],
  diagnosis: ['#edf4f9', '#adc5d9', '#34698a'], knowledge: ['#f2eef8', '#c5bbd8', '#6c5686'],
  linked: ['#edf5ff', '#a9c5e2', '#2b5e8b'],
}
const assetColors: Record<string, string> = {
  requirement: '#8fadd4', task: '#80b3a5', case: '#bc9acc', playbook: '#8ba887',
  document: '#c4aa83', requirement_document: '#c4aa83', plan_document: '#c4aa83',
}
type Box = { x: number; y: number; width: number; height: number }

function screenBox(position: Point, size: Size, viewport: Viewport): Box {
  return { x: position.x * viewport.scale + viewport.x, y: position.y * viewport.scale + viewport.y,
    width: size.width * viewport.scale, height: size.height * viewport.scale }
}

function onScreen(box: Box, size: Size) {
  return box.x < size.width && box.y < size.height && box.x + box.width > 0 && box.y + box.height > 0
}

function connectorOnScreen(from: Box, to: Box, size: Size) {
  return Math.min(from.x, to.x) < size.width && Math.min(from.y, to.y) < size.height
    && Math.max(from.x + from.width, to.x + to.width) > 0 && Math.max(from.y + from.height, to.y + to.height) > 0
}

function label(context: CanvasRenderingContext2D, text: string, box: Box, color: string) {
  const maxWidth = box.width - 22
  if (maxWidth < 45) return
  context.font = '600 12px system-ui, "Microsoft YaHei", sans-serif'
  let visible = text
  while (visible.length > 1 && context.measureText(visible).width > maxWidth) visible = visible.slice(0, -2) + '…'
  context.fillStyle = color
  context.fillText(visible, box.x + 11, box.y + 19)
}

function frame(context: CanvasRenderingContext2D, box: Box, fill: string, border: string) {
  context.beginPath()
  context.roundRect(box.x, box.y, box.width, box.height, Math.min(9, box.height / 8, box.width / 8))
  context.fillStyle = fill
  context.fill()
  context.strokeStyle = border
  context.lineWidth = 1
  context.stroke()
}

function connector(context: CanvasRenderingContext2D, from: Box, to: Box, color: string, emphasized: boolean, count = 1, dash = '') {
  const a = center({ x: from.x, y: from.y }, from)
  const b = center({ x: to.x, y: to.y }, to)
  const horizontal = Math.abs(b.x - a.x) >= Math.abs(b.y - a.y) || Math.abs(b.x - a.x) > (from.width + to.width) / 2 + 5
  const direction = (horizontal ? b.x - a.x : b.y - a.y) >= 0 ? 1 : -1
  if (horizontal) { a.x += from.width / 2 * direction; b.x -= to.width / 2 * direction }
  else { a.y += from.height / 2 * direction; b.y -= to.height / 2 * direction }
  const elbow = (horizontal ? b.x - a.x : b.y - a.y) * 0.52
  context.globalAlpha = emphasized ? 0.88 : 0.47
  context.strokeStyle = color
  context.lineWidth = emphasized ? Math.min(3, 1.45 + Math.log2(count) * 0.45) : 0.8
  context.setLineDash(dash && emphasized ? dash.split(' ').map(value => Math.max(1, Number(value) * 0.38)) : [])
  context.beginPath()
  context.moveTo(a.x, a.y)
  if (horizontal) context.bezierCurveTo(a.x + elbow, a.y, b.x - elbow, b.y, b.x, b.y)
  else context.bezierCurveTo(a.x, a.y + elbow, b.x, b.y - elbow, b.x, b.y)
  context.stroke()
  if (emphasized) {
    const size = 4
    context.fillStyle = color
    context.beginPath()
    context.moveTo(b.x, b.y)
    if (horizontal) {
      context.lineTo(b.x - direction * size * 1.6, b.y - size)
      context.lineTo(b.x - direction * size * 1.6, b.y + size)
    } else {
      context.lineTo(b.x - size, b.y - direction * size * 1.6)
      context.lineTo(b.x + size, b.y - direction * size * 1.6)
    }
    context.closePath()
    context.fill()
  }
  context.globalAlpha = 1
  context.setLineDash([])
}

function drawGraph(context: CanvasRenderingContext2D, nodes: CanvasNode[], regions: CanvasRegion[],
  relations: CanvasGraphRelation[], edges: CanvasEdge[], viewport: Viewport, size: Size, grouped: boolean, selectedId?: string) {
  const visible = new Map<string, Box>()
  const nodeById = new Map<string, CanvasNode>()
  for (const node of nodes) {
    const box = screenBox(node.position, node.size, viewport)
    visible.set(node.id, box)
    nodeById.set(node.id, node)
  }
  const groupBoxes = new Map(regions.map(region => [region.id, screenBox(region.position, region.size, viewport)]))
  const bundles = new Map<string, { relation: CanvasGraphRelation; source: string; target: string; count: number }>()
  for (const relation of relations) {
    const source = nodeById.get(relation.sourceNodeId)?.domainId, target = nodeById.get(relation.targetNodeId)?.domainId
    const from = visible.get(relation.sourceNodeId), to = visible.get(relation.targetNodeId)
    if (!from || !to) continue
    if (source && target && source !== target) {
      const key = `${source}:${target}:${relation.relation_type}`
      const bundle = bundles.get(key)
      if (bundle) bundle.count++
      else bundles.set(key, { relation, source, target, count: 1 })
    } else if (!grouped && connectorOnScreen(from, to, size)) {
      connector(context, from, to, relationStyles[relation.relation_type].color, false)
    }
  }
  for (const { relation, source, target, count } of bundles.values()) {
    const from = (grouped || count > 1 ? groupBoxes.get(source) : undefined) ?? visible.get(relation.sourceNodeId)
    const to = (grouped || count > 1 ? groupBoxes.get(target) : undefined) ?? visible.get(relation.targetNodeId)
    if (!from || !to || !connectorOnScreen(from, to, size)) continue
    const style = relationStyles[relation.relation_type]
    connector(context, from, to, style.color, true, count, style.dash)
  }
  for (const edge of edges) {
    const from = visible.get(edge.source), to = visible.get(edge.target)
    if (from && to && connectorOnScreen(from, to, size)) connector(context, from, to, '#55708b', true, 1, '5 4')
  }
  for (const node of nodes) {
    if (grouped && node.kind === 'card' && node.id !== selectedId) continue
    const box = visible.get(node.id)!
    if (!onScreen(box, size)) continue
    if (node.kind === 'frame') frame(context, box, '#ffffff22', '#7d9fb6')
    else {
      context.fillStyle = node.id === selectedId ? '#086b9d'
        : node.kind === 'note' ? '#e8c96d' : assetColors[node.reference?.kind ?? ''] ?? '#9eb3c8'
      context.fillRect(box.x, box.y, Math.max(2, box.width), Math.max(2, box.height))
    }
  }
}

watchEffect(cleanup => {
  const { nodes, regions, relations, edges, viewport, size, overview, featured, tree, selectedId } = props
  const element = canvas.value
  if (!element || !size.width || !size.height) return
  const titles = regions.map(region => region.title ?? t(`workspace_canvas.domains.${region.kind}`))
  const tick = requestAnimationFrame(() => {
    const context = element.getContext('2d')
    if (!context) return
    const ratio = Math.min(2, window.devicePixelRatio || 1)
    const width = Math.round(size.width * ratio), height = Math.round(size.height * ratio)
    if (element.width !== width) element.width = width
    if (element.height !== height) element.height = height
    context.setTransform(ratio, 0, 0, ratio, 0, 0)
    context.clearRect(0, 0, size.width, size.height)
    const hasSections = regions.some(region => region.type === 'section')
    const grouped = overview && nodes.length > 32
    const captions: { title: string; box: Box; color: string }[] = []
    regions.forEach((region, index) => {
      const box = screenBox(region.position, region.size, viewport)
      if (!onScreen(box, size) || box.width < 14 || box.height < 10) return
      if (tree && region.assetCount === 1) return
      if (region.type === 'domain' && hasSections && region.assetCount === 1 && overview) return
      const [fill, border, color] = colors[region.kind]
      frame(context, box, region.type === 'domain' ? `${fill}a8` : fill, border)
      if (tree || (featured && region.type === 'domain' && region.assetCount === 1)) return
      if (box.height < 28 || box.width < 78 || (overview && region.type === 'domain' && box.height < 59)) return
      const title = region.type === 'section' || (grouped && region.assetCount > 1)
        ? `${titles[index]}  ${region.assetCount}` : titles[index]!
      captions.push({ title, box, color })
    })
    if (overview) drawGraph(context, nodes, regions, relations, edges, viewport, size, grouped, selectedId)
    for (const caption of captions) label(context, caption.title, caption.box, caption.color)
  })
  cleanup(() => cancelAnimationFrame(tick))
}, { flush: 'post' })
</script>

<template>
  <canvas ref="canvas" class="overview-layer" aria-hidden="true" :data-overview-nodes="overview ? nodes.length : undefined"
    :data-overview-relations="overview ? relations.length : undefined" />
</template>

<style scoped>
.overview-layer { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
</style>
