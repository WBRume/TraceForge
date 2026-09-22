<script setup lang="ts">
import { hypothesisLabel } from './guideHypothesis'
defineProps<{
  stages: { id: string; title: string; state: string }[]
  selected: string; hypotheses: { id: string; claim: string; state: string; evidence?: unknown[]; verdict?: string }[]; hypothesisId: string
}>()
const emit = defineEmits<{ stage: [id: string]; hypothesis: [id: string] }>()
const labels: Record<string, string> = { APPROVED: '已确认', SUPPORTED: '支持', REFUTED: '证伪', EXCLUDED: '排除', PROPOSED: '待验证', QUEUED: '待验证', INCONCLUSIVE: '待补充' }
</script>
<template>
  <nav class="sop-nav" aria-label="SOP 阶段">
    <h3>SOP 规程阶段树</h3>
    <button v-for="(stage, index) in stages" :key="stage.id" class="nav-item"
      :class="{ selected: selected === stage.id }" :disabled="stage.state === 'LOCKED'"
      :aria-current="selected === stage.id ? 'step' : undefined" @click="emit('stage', stage.id)">
      <span>{{ String(index + 1).padStart(2, '0') }} · {{ stage.title }}</span>
      <small :class="stage.state">{{ { LOCKED: '未开始', ACTIVE: '当前', CONFIRMED: '已确认', PASS: 'PASS' }[stage.state] || stage.state }}</small>
    </button>
    <h3 class="hypothesis-heading">可证伪假说树</h3>
    <p v-if="!hypotheses.length" class="empty">暂无假说</p>
    <button v-for="item in hypotheses" :key="item.id" class="nav-item hypothesis" :class="{ selected: hypothesisId === item.id }" @click="emit('hypothesis', item.id)">
      <span>{{ item.id }} · {{ item.claim }}</span><small :class="[item.state, item.verdict]">{{ item.evidence !== undefined ? hypothesisLabel(item) : labels[item.state] || item.state }}</small>
    </button>
  </nav>
</template>
<style scoped>
.sop-nav { padding:18px 14px; overflow:auto; min-width:0; background:white }
h3 { font-size:12px; color:#54708d; font-weight:600; margin:0 0 12px }.hypothesis-heading { padding-top:18px; margin-top:22px; border-top:1px solid #e0e7f0 }
.nav-item { width:100%; display:flex; gap:8px; align-items:center; justify-content:space-between; border:0; border-radius:5px; padding:10px 8px; text-align:left; background:transparent; cursor:pointer; color:#334b68; font-size:12px }
.nav-item span { min-width:0; overflow-wrap:anywhere }.nav-item small { flex-shrink:0; font-size:10px }.nav-item.selected { color:#2563eb; background:#eff6ff }.nav-item:disabled { color:#a6b0c2; cursor:default }
.PASS,.CONFIRMED,.APPROVED,.SUPPORTED { color:#059669 }.EXCLUDED { color:#8a98ad }.REFUTED { color:#dc2626 }.ACTIVE { color:#2563eb }.empty { color:#94a3b8; font-size:12px }
</style>
