<script setup lang="ts">
import { computed } from 'vue'
import { markerTransform, pathThrough } from './diagramGeometry'
import type { DiagramNode } from './diagramModel'

const { node } = defineProps<{ node: DiagramNode }>()
const strokes = computed(() => (node.paths ?? []).map(path => path.map(([x, y]) => ({
  x: x * node.width, y: y * node.height,
}))))
const outline = computed(() => strokes.value.map(pathThrough).join(' '))
const arrows = computed(() => {
  const line = strokes.value[0]
  if (!node.arrow || !line || line.length < 2) return []
  const marks = [{ side: 'end', transform: markerTransform(line[line.length - 1], line[line.length - 2]) }]
  if (node.startArrow) marks.push({ side: 'start', transform: markerTransform(line[0], line[1]) })
  return marks
})
</script>

<template>
  <g :transform="`translate(${node.x} ${node.y})`" :data-diagram-node="node.id" :data-shape="node.shape">
    <path data-diagram-control :d="outline" fill="none" stroke="transparent" stroke-width="14" vector-effect="non-scaling-stroke" />
    <path :d="outline" fill="none" :stroke="node.stroke" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
    <path v-for="arrow in arrows" :key="arrow.side" :data-diagram-arrow="arrow.side" d="M 0 0 L -11 -5 V 5 Z"
      :transform="arrow.transform" :fill="node.stroke" :stroke="node.stroke" stroke-width="1.4" />
  </g>
</template>
