<script setup lang="ts">
import type { PlaybookRun } from '@/types/diagnosisPlaybook'
defineProps<{ run: PlaybookRun; elapsed: number }>()
</script>
<template>
  <ol class="stage-rail" aria-label="诊断阶段">
    <li v-for="stage in run.stages" :key="stage.id" :class="{ active: stage.id === run.active_step }">
      <span>{{ ({ PROBE: '探针', HYPOTHESIZE: '假说', REPRODUCE: '复现', PATCH: '修复' } as Record<string, string>)[stage.phase] }}</span>
      <small v-if="run.gate_decisions.some(g => g.step_id === stage.id && g.verdict === 'PASS')">已通过</small>
      <small v-else-if="stage.id === run.active_step">{{ run.state }}<template v-if="elapsed"> · {{ elapsed }}s</template></small>
    </li>
  </ol>
</template>
<style scoped>
.stage-rail { display:flex; gap:12px; padding:0; list-style:none; flex-wrap:wrap }
.stage-rail li { display:flex; flex-direction:column; border-bottom:2px solid var(--border-color, #ddd); padding:6px 12px }
.stage-rail li.active { border-color:#2563eb; color:#2563eb }.stage-rail small { font-size:11px }
</style>
