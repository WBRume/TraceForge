<script setup lang="ts">
import { computed } from 'vue'
import { shapeDecoration, shapeOutline } from './diagramGeometry'
import { diagramLines } from './diagramText'
import { hasCompartments, hasSubtitle, isContainer, type DiagramNode } from './diagramModel'

const { node } = defineProps<{ node: DiagramNode }>()
const container = computed(() => isContainer(node.shape))
const compartments = computed(() => hasCompartments(node.shape))
const outline = computed(() => shapeOutline(node.shape, node.width, node.height))
const decoration = computed(() => shapeDecoration(node.shape, node.width, node.height))
const clipId = computed(() => 'shape-label-' + node.id)
const divider = computed(() => Math.max(64, Math.round(node.height * .61)))
const titleHeight = computed(() => node.shape === 'interface' ? 47 : 34)
const isCircle = computed(() => node.shape === 'initial' || node.shape === 'final')
const subtitle = computed(() => hasSubtitle(node.shape) && node.detail
  ? diagramLines(node.detail, node.width * .72 - 10, 11, 1)[0] : '')
const label = computed(() => {
  const leftIcon = ['service', 'server', 'queue', 'router', 'firewall', 'person'].includes(node.shape)
  const width = node.shape === 'decision' ? node.width * .57 : leftIcon ? node.width * .69 - 10 : node.width - 23
  const size = node.shape === 'text' ? 17 : 14
  const height = node.shape === 'lifeline' ? 40 : node.shape === 'actor' ? 18 : node.height - 9
  const lines = diagramLines(node.label, width, size, Math.floor((height - (subtitle.value ? 18 : 0)) / 18))
  const x = node.width * (leftIcon ? .59 : .5)
  const y = node.shape === 'lifeline' ? 27 : node.shape === 'actor' ? node.height - 6
    : node.height * (node.shape === 'database' || node.shape === 'cloud' ? .59 : node.shape === 'client' ? .43 : .5)
      - (lines.length - 1) * 9 + 5 - (subtitle.value ? 8 : 0)
  return { lines, x, y, size }
})
const details = computed(() => diagramLines(node.detail, node.width - 22, 12,
  Math.floor(((node.shape === 'entity' ? node.height : divider.value) - titleHeight.value - 8) / 16)))
const operations = computed(() => diagramLines(node.operations, node.width - 22, 12, Math.floor((node.height - divider.value - 8) / 16)))
</script>

<template>
  <g :transform="`translate(${node.x} ${node.y})`" :data-diagram-node="node.id" :data-shape="node.shape">
    <title>{{ node.label }}</title>
    <clipPath :id="clipId"><rect x="2" y="2" :width="node.width - 4" :height="node.height - 4" /></clipPath>
    <path v-if="node.shape !== 'actor'" :d="outline"
      :fill="node.shape === 'text' ? 'transparent' : node.shape === 'initial' ? node.stroke : node.fill"
      :stroke="node.shape === 'text' ? 'none' : node.stroke" stroke-width="1.5"
      :stroke-dasharray="node.shape === 'frame' ? '7 4' : undefined" :pointer-events="container ? 'stroke' : 'all'" />
    <rect v-if="container || node.shape === 'actor'" :width="node.shape === 'lane' ? Math.min(92, node.width * .2) : node.width"
      :height="node.shape === 'frame' ? 32 : node.height" fill="transparent" />
    <path v-if="decoration" :d="decoration" fill="none" :stroke="node.stroke" stroke-width="1.5" pointer-events="none" />
    <circle v-if="node.shape === 'actor'" :cx="node.width / 2" :cy="node.height * .23" :r="Math.min(node.width, node.height) * .11"
      :fill="node.fill" :stroke="node.stroke" stroke-width="1.5" pointer-events="none" />
    <ellipse v-if="node.shape === 'final'" :cx="node.width / 2" :cy="node.height / 2"
      :rx="node.width * .33" :ry="node.height * .33" :fill="node.stroke" />
    <line v-if="node.shape === 'lifeline'" :x1="node.width / 2" :x2="node.width / 2"
      :y1="Math.min(node.height * .35, 50)" :y2="node.height" :stroke="node.stroke" stroke-width="1.5" stroke-dasharray="6 5" />
    <line v-if="node.shape === 'lifeline'" data-diagram-control :x1="node.width / 2" :x2="node.width / 2"
      :y1="Math.min(node.height * .35, 50)" :y2="node.height" stroke-width="16" stroke="transparent" />
    <g :clip-path="`url(#${clipId})`" pointer-events="none" fill="#172c44">
      <template v-if="compartments">
        <path :d="`M 0 ${titleHeight} H ${node.width}`" :stroke="node.stroke" fill="none" />
        <path v-if="node.shape !== 'entity'" :d="`M 0 ${divider} H ${node.width}`" :stroke="node.stroke" fill="none" />
        <text v-if="node.shape === 'interface'" :x="node.width / 2" y="16" font-size="11" text-anchor="middle">«interface»</text>
        <text :x="node.width / 2" :y="titleHeight - 11" font-size="14" font-weight="700" text-anchor="middle">{{ node.label }}</text>
        <text font-family="Consolas, 'Microsoft YaHei UI', monospace" font-size="12" xml:space="preserve">
          <tspan v-for="(line, index) in details" :key="index" x="11" :y="titleHeight + 18 + index * 16">{{ line }}</tspan>
        </text>
        <text v-if="node.shape !== 'entity'" font-family="Consolas, 'Microsoft YaHei UI', monospace" font-size="12">
          <tspan v-for="(line, index) in operations" :key="index" x="11" :y="divider + 18 + index * 16">{{ line }}</tspan>
        </text>
      </template>
      <text v-else-if="container" x="13" y="22" font-weight="650" font-size="13">
        {{ diagramLines(node.label, node.shape === 'lane' ? Math.min(78, node.width * .2) - 8 : node.width - 24, 13, 1)[0] }}
      </text>
      <text v-else-if="!isCircle" :font-size="label.size" text-anchor="middle" :font-weight="node.shape === 'note' ? 450 : 600">
        <tspan v-for="(line, index) in label.lines" :key="index" :x="label.x" :y="label.y + index * 18">{{ line }}</tspan>
        <tspan v-if="subtitle" :x="label.x" :y="label.y + label.lines.length * 18" fill="#526b84" font-size="11" font-weight="450">{{ subtitle }}</tspan>
      </text>
    </g>
  </g>
</template>
