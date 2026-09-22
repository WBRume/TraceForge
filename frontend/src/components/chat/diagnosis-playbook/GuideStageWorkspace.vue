<script setup lang="ts">
import { computed } from 'vue'
import ToggleSwitch from '@/components/ToggleSwitch.vue'
import type { GuideSession } from '@/types/diagnosisPlaybook'
import GuideHypothesisReview from './GuideHypothesisReview.vue'
import { isSupportedHypothesis } from './guideHypothesis'
const props = defineProps<{ state: GuideSession; phase: string; hypothesisId: string; busy: boolean; running: boolean }>()
const emit = defineEmits<{ command: [action: string, hypothesisId?: string]; investigate: [text: string] }>()
const titles: Record<string, string> = { PROBE: '探针采证', HYPOTHESIZE: '假说与实验', REPRODUCE: '症状复现', PATCH: '补丁与回归' }
const report = computed(() => props.state.reports[props.phase])
const hypothesis = computed(() => props.state.hypotheses.find(h => h.id === props.hypothesisId))
const visibleHypotheses = computed(() => hypothesis.value ? [hypothesis.value] : props.state.hypotheses)
const needsRootConfirmation = computed(() => props.phase === 'HYPOTHESIZE' && active.value &&
  !props.state.hypotheses.some(h => h.state === 'APPROVED' && isSupportedHypothesis(h)))
const hasCandidate = computed(() => props.state.hypotheses.some(h => h.state !== 'EXCLUDED' && isSupportedHypothesis(h)))
const active = computed(() => props.phase === props.state.active_phase && !props.state.completed)
const canAdvance = computed(() => active.value && !props.state.error && report.value?.ready_for_review && !!report.value.evidence.length &&
  (props.phase !== 'HYPOTHESIZE' || props.state.hypotheses.some(h => h.state === 'APPROVED' && isSupportedHypothesis(h))) &&
  report.value.outcome !== 'FAILED' && (!['REPRODUCE', 'PATCH'].includes(props.phase) || report.value.outcome === 'OBSERVED'))
const locked = computed(() => props.busy || props.running || !active.value)
const chain = computed(() => Array.isArray(props.state.guide.context.call_chain) ? props.state.guide.context.call_chain as Record<string, unknown>[] : [])
</script>
<template>
  <div class="stage-workspace">
    <header class="stage-toolbar">
      <div><h2>{{ hypothesis && phase === 'HYPOTHESIZE' ? `${hypothesis.id} · ${hypothesis.claim}` : titles[phase] }}</h2><span class="status">{{ state.completed ? '已完成' : state.confirmations[phase] ? '已确认' : running && active ? '执行中' : report ? '待确认' : '待执行' }}</span></div>
      <div v-if="active" class="toolbar-actions">
        <label class="auto-run-switch" title="开启后关闭页面仍会继续，证据不足或执行失败时暂停；关闭开关后，当前阶段结束即停止自动推进。">
          <ToggleSwitch :model-value="!!state.auto_run" :disabled="busy || state.completed" aria-label="自动执行全流程"
            @update:model-value="emit('command', state.auto_run ? 'disable_auto' : 'enable_auto')" />
          自动执行全流程
        </label>
        <button class="primary" :disabled="locked || !canAdvance" @click="emit('command', 'advance')">{{ phase === 'PATCH' ? '确认并完成' : '确认并进入下一阶段' }}</button>
      </div>
    </header>
    <p v-if="state.auto_pause_reason" role="status" class="auto-pause">{{ state.auto_pause_reason }}</p>
    <p v-if="state.error && active" role="alert" class="error">{{ state.error }}</p>
    <section v-if="phase === 'PROBE' && chain.length" class="panel"><h3>来源案例调用链</h3><ol class="chain"><li v-for="(node, index) in chain" :key="index"><strong>{{ [node.module, node.function].filter(Boolean).join('.') || node.file_path || node.file }}</strong><code>{{ node.file_path || node.file }}</code><p>{{ node.description }}</p></li></ol></section>
    <template v-if="phase === 'HYPOTHESIZE'">
      <p v-if="needsRootConfirmation" class="review-hint" role="status">{{ hasCandidate ? '请核对候选根因的判定依据，再点击“确认根因”。已证伪的假说无需逐项确认。' : '暂无有证据支持的候选根因，请补充排查后再继续。已证伪不代表已找到根因。' }}</p>
      <GuideHypothesisReview v-for="item in visibleHypotheses" :key="item.id" :hypothesis="item" :disabled="locked"
        @command="(action, id) => emit('command', action, id)" />
    </template>
    <section v-if="report?.code" class="panel code-panel"><h3>{{ phase === 'PATCH' ? '补丁与回归代码' : '实验代码' }}<small>{{ { NOT_RUN: '未执行', OBSERVED: '已记录结果', FAILED: '执行失败' }[report.outcome] }}</small></h3><pre><code>{{ report.code }}</code></pre></section>
    <section class="panel"><h3>{{ phase === 'PROBE' ? '采证结果' : '阶段结果' }}</h3>
      <p v-if="!report" class="empty">暂无阶段结果</p><p v-else class="findings">{{ report.findings }}</p>
      <button v-if="active" class="text-action" :disabled="locked" @click="emit('investigate', `请继续 SOP 的「${titles[phase]}」阶段，检查当前材料，补充本次证据和阶段结果。`)">{{ report ? '补充排查' : '开始本阶段排查' }}</button>
    </section>
    <section v-if="report?.evidence.length" class="panel"><h3>本次证据</h3><ul class="observations"><li v-for="(entry, i) in report.evidence" :key="i"><code>{{ entry.reference }}</code><p>{{ entry.observation }}</p></li></ul></section>
    <section v-if="phase === 'PROBE'" class="panel"><h3>采证清单</h3><ol><li v-for="step in state.guide.steps.filter(s => !['hypotheses', 'conclusion'].includes(s.id))" :key="step.id">{{ step.objective }}</li></ol></section>
  </div>
</template>
<style scoped>
.stage-workspace { display:flex; flex-direction:column; gap:14px; padding:16px; min-width:0 }
.review-hint { margin:0; padding:12px 14px; color:#54708d; background:#eff6ff; border-radius:6px; font-size:12px; line-height:1.7 }
.toolbar-actions { display:flex; gap:12px; align-items:center; flex-shrink:0 }
.auto-run-switch { --toggle-active:#2563eb; display:flex; align-items:center; gap:6px; font-size:12px; font-weight:600; color:#475569; cursor:pointer; white-space:nowrap }
.auto-pause { margin:0; padding:10px 14px; color:#b45309; background:#fffbeb; border:1px solid #fde68a; border-radius:6px; font-size:12px }
.stage-toolbar { display:flex; gap:12px; align-items:center; justify-content:space-between; padding:14px 16px; border:1px solid #dbe5f1; border-radius:8px; background:white }
h2 { margin:0; font-size:14px; font-weight:650; overflow-wrap:anywhere }.status { display:inline-block; margin-top:6px; color:#64748b; font-size:11px }
button { padding:7px 10px; font-size:12px; cursor:pointer; border:1px solid #dbe5f1; border-radius:5px; background:white; color:#2563eb }button:disabled { opacity:.45; cursor:default }.primary { background:#2563eb; border-color:#2563eb; color:white; flex-shrink:0 }.text-action { margin:0 14px 14px }
.panel { background:white; border:1px solid #dbe5f1; border-radius:8px; overflow:hidden; min-width:0 }h3 { margin:0; font-size:13px; font-weight:600; padding:12px 14px; border-bottom:1px solid #e5edf5; display:flex; justify-content:space-between; gap:12px }h3 small { font-size:11px; color:#64748b; font-weight:400 }
.panel>p,.panel>ol { margin:14px; font-size:13px; line-height:1.7 }.panel>ol { padding-left:18px }.findings { white-space:pre-wrap; overflow-wrap:anywhere }.empty { color:#94a3b8 }.error { color:#b45309; margin:0; font-size:12px }
dl { display:grid; grid-template-columns:70px minmax(0,1fr); gap:12px; padding:14px; margin:0; font-size:12px }dt { color:#64748b }dd { margin:0; overflow-wrap:anywhere }
.observations { list-style:none; margin:0; padding:0 14px }.observations li { padding:12px 0; border-bottom:1px solid #edf2f7; font-size:12px }.observations p { margin:6px 0; white-space:pre-wrap }.observations code,.chain code { font-size:11px; overflow-wrap:anywhere; color:#2563eb }.chain code { display:block }.chain li { margin-bottom:10px }.chain p { margin:2px 0 }
.actions { display:flex; gap:8px; padding:14px }.code-panel pre { margin:0; background:#1e1e1e; color:#e5e7eb; padding:16px; overflow:auto; font-size:12px; line-height:1.7; max-height:440px }
</style>
