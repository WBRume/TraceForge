<script setup lang="ts">
import { computed } from 'vue'
import { diagramLines } from './diagramText'
import { markerTransform, type EdgeDrawing } from './diagramGeometry'
import type { DiagramEdge } from './diagramModel'

const { edge, geometry } = defineProps<{ edge: DiagramEdge; geometry: EdgeDrawing }>()
const relation = computed(() => edge.relation)
const dashed = computed(() => ['dependency', 'realization', 'reply'].includes(relation.value))
const label = computed(() => diagramLines(edge.label, 182, 12, 2))

const head = computed(() => {
  if (relation.value === 'inheritance' || relation.value === 'realization') return { path: 'M 0 0 L -14 -7 V 7 Z', fill: '#fff' }
  if (['flow', 'bidirectional', 'call', 'dataflow'].includes(relation.value)) return { path: 'M 0 0 L -11 -5 V 5 Z', fill: edge.stroke }
  if (relation.value === 'dependency' || relation.value === 'reply') return { path: 'M -10 -5 L 0 0 L -10 5', fill: 'none' }
  if (relation.value === 'many') return { path: 'M -13 0 L 0 -7 M -13 0 L 0 7 M -7 -7 V 7', fill: 'none' }
  return null
})
const tail = computed(() => relation.value === 'aggregation' || relation.value === 'composition')

function marker(start = false) {
  const ordered = start ? geometry.points : [...geometry.points].reverse()
  const tip = ordered[0]
  const next = ordered.find(point => Math.hypot(point.x - tip.x, point.y - tip.y) > .001)
  return markerTransform(tip, next ?? tip)
}
</script>

<template>
  <g :data-diagram-edge="edge.id" :data-relation="edge.relation">
    <title>{{ edge.label }}</title>
    <path data-diagram-control :d="geometry.path" fill="none" stroke="transparent" stroke-width="15" vector-effect="non-scaling-stroke" />
    <path :d="geometry.path" fill="none" :stroke="edge.stroke" stroke-width="1.8"
      stroke-linecap="round" stroke-linejoin="round" :stroke-dasharray="dashed ? '7 5' : undefined" />
    <path v-if="head" data-diagram-arrow="end" :d="head.path" :transform="marker()" :fill="head.fill" :stroke="edge.stroke" stroke-width="1.4" />
    <path v-if="head && relation === 'bidirectional'" data-diagram-arrow="start"
      :d="head.path" :transform="marker(true)" :fill="head.fill" :stroke="edge.stroke" stroke-width="1.4" />
    <path v-if="tail" d="M 0 0 L -9 -5.5 L -18 0 L -9 5.5 Z" :transform="marker(true)"
      :fill="edge.relation === 'composition' ? edge.stroke : '#fff'" :stroke="edge.stroke" stroke-width="1.4" />
    <text v-if="edge.label" fill="#233d57" stroke="#fff" stroke-width="5" stroke-linejoin="round" paint-order="stroke"
      text-anchor="middle" font-weight="650" font-size="12">
      <tspan v-for="(line, index) in label" :key="index" :x="geometry.label.x"
        :y="geometry.label.y - 8 - (label.length - 1 - index) * 15">{{ line }}</tspan>
    </text>
  </g>
</template>
