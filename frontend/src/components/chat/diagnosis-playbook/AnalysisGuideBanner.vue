<script setup lang="ts">
defineProps<{ guide: { title: string; version: string; steps: { id: string; objective: string }[] } }>()
</script>
<template>
  <details class="analysis-guide">
    <summary>诊断规程：{{ guide.title }} <small>{{ guide.version }} · 分析参考</small></summary>
    <p>Agent 将结合历史调用链与排查步骤分析当前任务；历史结论仍需本次证据核实。</p>
    <ol><li v-for="step in guide.steps" :key="step.id">{{ step.objective }}</li></ol>
  </details>
</template>
<style scoped>
.analysis-guide { margin:8px 16px; padding:10px 14px; border:1px solid var(--border-color,#e2e8f0); border-radius:8px; font-size:13px }
summary { cursor:pointer } small,p { color:#64748b } ol { padding-left:20px }
</style>
