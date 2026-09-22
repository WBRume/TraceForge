<script setup lang="ts">
import { computed } from 'vue'
import type { PlaybookHypothesis } from '@/types/diagnosisPlaybook'
const props = defineProps<{ hypotheses: readonly PlaybookHypothesis[] }>()
const height = computed(() => Math.max(96, props.hypotheses.length * 68))
const status = (state: string) => ({ SUPPORTED: '证据支持', REFUTED: '已证伪', EXCLUDED: '人工排除', INCONCLUSIVE: '证据不足', QUEUED: '待验证' }[state] ?? '待验证')
</script>
<template>
  <details v-if="hypotheses.length" class="hypothesis-dag" open>
    <summary>假说与判别实验</summary>
    <svg viewBox="0 0 600 240" :style="{ height: `${height}px` }" role="img" aria-label="证据从探测分流至独立假说，再汇合至复现阶段">
      <g v-for="(hypothesis, index) in hypotheses" :key="hypothesis.id">
        <path :d="`M 100 120 C 160 120 160 ${40 + index * 80} 210 ${40 + index * 80} M 390 ${40 + index * 80} C 440 ${40 + index * 80} 440 120 500 120`" fill="none" stroke="currentColor" opacity="0.35" />
        <rect x="210" :y="16 + index * 80" width="180" height="48" rx="6" fill="var(--bg-secondary, #f1f5f9)" stroke="currentColor" />
        <text x="300" :y="36 + index * 80" text-anchor="middle">{{ hypothesis.id }}</text>
        <text x="300" :y="54 + index * 80" text-anchor="middle" class="state">{{ status(hypothesis.state) }}</text>
        <title>{{ hypothesis.claim }}</title>
      </g>
      <rect x="0" y="98" width="100" height="44" rx="6" fill="var(--bg-secondary, #f1f5f9)" stroke="currentColor" />
      <text x="50" y="125" text-anchor="middle">物理探测</text>
      <rect x="500" y="98" width="100" height="44" rx="6" fill="var(--bg-secondary, #f1f5f9)" stroke="currentColor" />
      <text x="550" y="125" text-anchor="middle">复现验证</text>
    </svg>
  </details>
</template>
<style scoped>
.hypothesis-dag { margin:12px 0; color:var(--text-secondary,#475569) }.hypothesis-dag svg { width:100%; min-height:100px; max-height:220px; display:block }.hypothesis-dag text { fill:currentColor; font-size:13px }.hypothesis-dag .state { font-size:11px }
</style>
