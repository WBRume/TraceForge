<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, shallowRef, watch } from 'vue'
import type { GuideSession, PlaybookRun } from '@/types/diagnosisPlaybook'
import SopStageNav from './SopStageNav.vue'
import GuideStageWorkspace from './GuideStageWorkspace.vue'
import HypothesisCard from './HypothesisCard.vue'
import PhysicalEvidenceDrawer from './PhysicalEvidenceDrawer.vue'
import VerificationComparison from './VerificationComparison.vue'
const props = defineProps<{
  enabled: boolean; guide: GuideSession | null; run: PlaybookRun | null
  busy: boolean; running: boolean; error: string; tail: string; canContinue: boolean; agentText?: string
}>()
const emit = defineEmits<{
  guideCommand: [action: string, hypothesisId?: string]; command: [action: string, extra?: Record<string, unknown>]
  investigate: [text: string]; retry: []
}>()
const selected = shallowRef('PROBE')
const hypothesisId = shallowRef('')
const phases = ['PROBE', 'HYPOTHESIZE', 'REPRODUCE', 'PATCH']
const titles: Record<string, string> = { PROBE: '探针采证', HYPOTHESIZE: '假说与实验', REPRODUCE: '症状复现', PATCH: '补丁与回归' }
const stages = computed(() => props.run ? props.run.stages.map((s, i) => ({ id: s.id, title: titles[s.phase] || s.objective,
  state: props.run!.gate_decisions.some(g => g.step_id === s.id && g.run_epoch === props.run!.run_epoch && g.verdict === 'PASS') ? 'PASS' : s.id === props.run!.active_step ? 'ACTIVE' : i > props.run!.stages.findIndex(x => x.id === props.run!.active_step) ? 'LOCKED' : '待验证' })) :
  phases.map(id => ({ id, title: titles[id]!, state: props.guide?.confirmations[id] ? 'CONFIRMED' : id === props.guide?.active_phase ? 'ACTIVE' : 'LOCKED' })))
const hypotheses = computed(() => props.run?.hypotheses || props.guide?.hypotheses || [])
const physicalHypothesis = computed(() => props.run?.hypotheses.find(h => h.id === hypothesisId.value))
const physicalReceipts = computed(() => props.run?.evidence.filter(e => e.step_id === selected.value && e.run_epoch === props.run?.run_epoch) || [])
const physicalBusy = computed(() => props.busy || ['AGENT_RUNNING', 'VERIFYING', 'RECOVERING', 'COMPLETED', 'CANCELLED'].includes(props.run?.state || ''))
watch(() => [props.guide?.task_id, props.run?.id], () => { hypothesisId.value = '' })
watch(() => props.run?.active_step || props.guide?.active_phase, value => { if (value) selected.value = value }, { immediate: true })
const chooseHypothesis = (id: string) => {
  hypothesisId.value = id
  selected.value = props.run?.stages.find(s => s.phase === 'HYPOTHESIZE')?.id || 'HYPOTHESIZE'
}
const chooseStage = (id: string) => { selected.value = id; hypothesisId.value = '' }
const layoutEl = shallowRef<HTMLElement | null>(null)
const LAYOUT_KEY = 'sop-layout-widths'
const LAYOUT_DEFAULT = { left: 210, right: 340 }
const MIDDLE_MIN = 320
const clampWidth = (v: number, min: number, max: number) => Math.round(Math.min(Math.max(min, v), Math.max(min, max)))
const widths = shallowRef({ ...LAYOUT_DEFAULT })
try {
  const saved = JSON.parse(localStorage.getItem(LAYOUT_KEY) || 'null')
  if (saved?.left && saved?.right) widths.value = { left: clampWidth(saved.left, 150, 560), right: clampWidth(saved.right, 280, 760) }
} catch {}
const saveWidths = () => { try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(widths.value)) } catch {} }
const applyWidth = (side: 'left' | 'right', value: number) => {
  const available = (layoutEl.value?.clientWidth || window.innerWidth) - 24
  const width = side === 'left'
    ? clampWidth(value, 150, available - MIDDLE_MIN - widths.value.right)
    : clampWidth(value, 280, available - widths.value.left - MIDDLE_MIN)
  widths.value = { ...widths.value, [side]: width }
}
const dragState = shallowRef<{ side: 'left' | 'right'; start: number; width: number } | null>(null)
const startDrag = (side: 'left' | 'right', event: PointerEvent) => {
  dragState.value = { side, start: event.clientX, width: widths.value[side] }
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}
const onDrag = (event: PointerEvent) => {
  const state = dragState.value
  if (!state) return
  applyWidth(state.side, state.width + (state.side === 'left' ? event.clientX - state.start : state.start - event.clientX))
}
const endDrag = () => { if (dragState.value) { dragState.value = null; saveWidths() } }
const onSplitterKey = (side: 'left' | 'right', event: KeyboardEvent) => {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  event.preventDefault()
  applyWidth(side, widths.value[side] + (event.key === 'ArrowLeft' ? -24 : 24))
  saveWidths()
}
const resetWidths = () => { widths.value = { ...LAYOUT_DEFAULT }; saveWidths() }
const onWindowResize = () => { applyWidth('left', widths.value.left); applyWidth('right', widths.value.right) }
onMounted(() => window.addEventListener('resize', onWindowResize))
onBeforeUnmount(() => { window.removeEventListener('resize', onWindowResize); endDrag() })
const layoutStyle = computed(() => ({ gridTemplateColumns: `${widths.value.left}px 6px minmax(${MIDDLE_MIN}px,1fr) 6px ${widths.value.right}px` }))
</script>
<template>
  <div v-if="!enabled" class="ordinary-conversation"><slot /></div>
  <div v-else ref="layoutEl" class="sop-layout" :class="{ dragging: !!dragState }" :style="layoutStyle" aria-label="诊断规程工作台">
    <SopStageNav :stages="stages" :selected="selected" :hypotheses="hypotheses" :hypothesis-id="hypothesisId" @stage="chooseStage" @hypothesis="chooseHypothesis" />
    <div class="sop-splitter" :class="{ 'drag-source': dragState?.side === 'left' }" role="separator" aria-orientation="vertical" aria-label="调整阶段树宽度" tabindex="0" @pointerdown="startDrag('left', $event)" @pointermove="onDrag" @pointerup="endDrag" @pointercancel="endDrag" @keydown="onSplitterKey('left', $event)" @dblclick="resetWidths" />
    <main class="sop-workspace">
      <div v-if="error" class="workspace-error" role="alert">{{ error }} <button @click="emit('retry')">刷新</button></div>
      <GuideStageWorkspace v-if="guide && !run" :state="guide" :phase="selected" :hypothesis-id="hypothesisId" :busy="busy" :running="running" @command="(action, id) => emit('guideCommand', action, id)" @investigate="emit('investigate', $event)" />
      <div v-else-if="run" class="physical-workspace">
        <header><h2>{{ stages.find(s => s.id === selected)?.title }}</h2><span>{{ run.state }}</span></header>
        <p v-if="run.missing_facts?.length" role="status">{{ run.missing_facts.join('、') }}</p>
        <HypothesisCard v-if="physicalHypothesis" :hypothesis="physicalHypothesis" :disabled="physicalBusy" @decide="(action, id, reason) => emit('command', action, { hypothesis_id: id, reason })" />
        <VerificationComparison :receipts="physicalReceipts" />
        <PhysicalEvidenceDrawer :receipts="physicalReceipts" :tail="tail" :workspace-id="run.workspace_id" :task-id="run.task_id" :run-id="run.id" />
        <p v-if="!physicalReceipts.length" class="empty">暂无验证回执</p>
        <div class="physical-actions"><button v-if="canContinue" :disabled="busy" @click="emit('command', 'continue')">继续排查</button><button v-if="!['COMPLETED','CANCELLED'].includes(run.state)" :disabled="busy" @click="emit('command', 'cancel')">停止排查</button></div>
        <div v-if="run.missing_facts?.includes('CASE_SELECTION_REQUIRED')"><button v-for="candidate in run.case_candidates" :key="candidate.id" :disabled="busy" @click="emit('command', 'select_case', { case_id: candidate.id })">归档到 {{ candidate.title }}</button></div>
      </div>
      <p v-else class="loading" role="status">加载规程…</p>
    </main>
    <div class="sop-splitter" :class="{ 'drag-source': dragState?.side === 'right' }" role="separator" aria-orientation="vertical" aria-label="调整对话区宽度" tabindex="0" @pointerdown="startDrag('right', $event)" @pointermove="onDrag" @pointerup="endDrag" @pointercancel="endDrag" @keydown="onSplitterKey('right', $event)" @dblclick="resetWidths" />
    <aside class="sop-conversation" aria-label="Agent 诊断对话">
      <header class="agent-heading">Agent 诊断副驾驶 <span v-if="running">执行中</span></header>
      <pre v-if="run && agentText" class="agent-output">{{ agentText }}</pre>
      <slot />
    </aside>
  </div>
</template>
<style scoped>
.ordinary-conversation { display:flex; flex:1; min-height:0; flex-direction:column }
.sop-layout { display:grid; flex:1; min-height:0; min-width:0; overflow:auto; background:#f7f9fc }
.sop-layout.dragging { cursor:col-resize; user-select:none }
.sop-splitter { position:relative; cursor:col-resize; touch-action:none; outline:none }
.sop-splitter::before { content:''; position:absolute; inset:0 2px; background:#dbe5f1 }
.sop-splitter::after { content:''; position:absolute; inset:0 -4px }
.sop-splitter:hover::before { background:#c3d2e4 }
.sop-layout.dragging .sop-splitter.drag-source::before { background:#93c5fd }
.sop-workspace { overflow:auto; min-width:0; min-height:0 }.sop-conversation { display:flex; flex-direction:column; min-height:0; min-width:0; background:white }
.agent-heading { display:flex; justify-content:space-between; gap:8px; font-size:13px; font-weight:600; padding:16px; border-bottom:1px solid #dbe5f1; flex-shrink:0 }.agent-heading span { color:#2563eb; font-weight:400; font-size:11px }
.workspace-error { margin:12px 16px; color:#b45309; font-size:12px }.physical-workspace { padding:16px; font-size:13px }.physical-workspace header { display:flex; gap:12px; justify-content:space-between; align-items:center }.physical-workspace h2 { font-size:14px }.physical-actions { display:flex; gap:12px }
.physical-workspace button,.workspace-error button { border:1px solid #dbe5f1; border-radius:5px; padding:6px 10px; background:white; color:#2563eb; cursor:pointer }.physical-workspace button:disabled { opacity:.5 }.empty,.loading { color:#94a3b8; font-size:13px }.loading { padding:20px }.agent-output { white-space:pre-wrap; overflow:auto; max-height:40%; font-size:12px; padding:12px; margin:10px; background:#eff6ff; border-radius:6px }
</style>
