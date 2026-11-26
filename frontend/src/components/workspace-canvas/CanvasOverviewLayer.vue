<script setup lang="ts">
import { useTemplateRef, watchEffect } from 'vue'
import { center, type Viewport } from './geometry'
import { relationStyles } from './relationStyles'
import type { CanvasEdge, CanvasGraphRelation, CanvasNode, Point, Size } from './model'

const props = defineProps<{
  nodes: CanvasNode[]; relations: CanvasGraphRelation[]; edges: CanvasEdge[];
  viewport: Viewport; size: Size; selectedId?: string;
}>()
const canvas = useTemplateRef<HTMLCanvasElement>('canvas')

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

function frame(context: CanvasRenderingContext2D, box: Box, fill: string, border: string) {
  context.beginPath()
  context.roundRect(box.x, box.y, box.width, box.height, Math.min(9, box.height / 8, box.width / 8))
  context.fillStyle = fill
  context.fill()
  context.strokeStyle = border
  context.lineWidth = 1
  context.stroke()
}

function connector(context: CanvasRenderingContext2D, from: Box, to: Box, color: string, emphasized: boolean, dash = '') {
  const a = center({ x: from.x, y: from.y }, from)
  const b = center({ x: to.x, y: to.y }, to)
  const horizontal = Math.abs(b.x - a.x) >= Math.abs(b.y - a.y) || Math.abs(b.x - a.x) > (from.width + to.width) / 2 + 5
  const direction = (horizontal ? b.x - a.x : b.y - a.y) >= 0 ? 1 : -1
  if (horizontal) { a.x += from.width / 2 * direction; b.x -= to.width / 2 * direction }
  else { a.y += from.height / 2 * direction; b.y -= to.height / 2 * direction }
  const elbow = (horizontal ? b.x - a.x : b.y - a.y) * 0.52
  context.globalAlpha = emphasized ? 0.88 : 0.47
  context.strokeStyle = color
  context.lineWidth = emphasized ? 1.45 : 0.8
  context.setLineDash(dash ? dash.split(' ').map(value => Math.max(1, Number(value) * 0.38)) : [])
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

function drawGraph(context: CanvasRenderingContext2D, nodes: CanvasNode[],
  relations: CanvasGraphRelation[], edges: CanvasEdge[], viewport: Viewport, size: Size, selectedId?: string) {
  const visible = new Map(nodes.map(node => [node.id, screenBox(node.position, node.size, viewport)]))
  for (const relation of relations) {
    const from = visible.get(relation.sourceNodeId), to = visible.get(relation.targetNodeId)
    if (!from || !to || !connectorOnScreen(from, to, size)) continue
    const style = relationStyles[relation.relation_type]
    connector(context, from, to, style.color, selectedId === relation.sourceNodeId || selectedId === relation.targetNodeId, style.dash)
  }
  for (const edge of edges) {
    const from = visible.get(edge.source), to = visible.get(edge.target)
    if (from && to && connectorOnScreen(from, to, size)) connector(context, from, to, '#55708b', true, '5 4')
  }
  for (const node of nodes) {
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
  const { nodes, relations, edges, viewport, size, selectedId } = props
  const element = canvas.value
  if (!element || !size.width || !size.height) return
  const tick = requestAnimationFrame(() => {
    const context = element.getContext('2d')
    if (!context) return
    const ratio = Math.min(2, window.devicePixelRatio || 1)
    const width = Math.round(size.width * ratio), height = Math.round(size.height * ratio)
    if (element.width !== width) element.width = width
    if (element.height !== height) element.height = height
    context.setTransform(ratio, 0, 0, ratio, 0, 0)
    context.clearRect(0, 0, size.width, size.height)
    drawGraph(context, nodes, relations, edges, viewport, size, selectedId)
  })
  cleanup(() => cancelAnimationFrame(tick))
}, { flush: 'post' })
</script>

<template>
  <canvas ref="canvas" class="overview-layer" aria-hidden="true" :data-overview-nodes="nodes.length" :data-overview-relations="relations.length" />
</template>

<style scoped>
.overview-layer { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
</style>
