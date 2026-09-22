<script setup lang="ts">
import { computed } from 'vue'
import type { GuideHypothesis } from '@/types/diagnosisPlaybook'
import { hypothesisLabel, isSupportedHypothesis } from './guideHypothesis'

const props = defineProps<{ hypothesis: GuideHypothesis; disabled: boolean }>()
const emit = defineEmits<{ command: [action: string, hypothesisId: string] }>()
const status = computed(() => hypothesisLabel(props.hypothesis))
</script>

<template>
  <section class="hypothesis-review" :aria-label="`假说 ${hypothesis.id}`">
    <header>
      <strong>{{ hypothesis.id }} · {{ hypothesis.claim }}</strong>
      <span class="status-badge" :class="{ 'is-supported': isSupportedHypothesis(hypothesis), 'is-refuted': hypothesis.verdict === 'REFUTED' }">{{ status }}</span>
    </header>
    <dl><dt>预测</dt><dd>{{ hypothesis.prediction }}</dd><dt>证伪条件</dt><dd>{{ hypothesis.falsifier }}</dd></dl>
    <p v-if="hypothesis.verdict_reason" class="verdict-reason"><strong>判定依据：</strong>{{ hypothesis.verdict_reason }}</p>
    <p v-else class="hint">尚无结构化判定，请补充排查；有证据记录不等于该证据支持假说。</p>
    <ul class="observations"><li v-for="(entry, i) in hypothesis.evidence" :key="i"><code class="obs-code">{{ entry.reference }}</code><p>{{ entry.observation }}</p></li></ul>
    <p v-if="!hypothesis.evidence.length" class="hint">尚无本次证据，请补充排查后再确认。</p>
    <div class="actions">
      <button v-if="isSupportedHypothesis(hypothesis)" class="btn-primary-action" :disabled="disabled || hypothesis.state !== 'PROPOSED'"
        @click="emit('command', 'approve_hypothesis', hypothesis.id)">{{ hypothesis.state === 'APPROVED' ? '已确认根因' : '确认根因' }}</button>
      <button v-if="hypothesis.verdict !== 'REFUTED'" class="btn-secondary-action" :disabled="disabled" @click="emit('command', hypothesis.state === 'EXCLUDED' ? 'restore_hypothesis' : 'exclude_hypothesis', hypothesis.id)">{{ hypothesis.state === 'EXCLUDED' ? '恢复假说' : '排除假说' }}</button>
    </div>
  </section>
</template>

<style scoped>
.hypothesis-review { background:#ffffff; border:1px solid #e2e8f0; border-radius:10px; min-width:0; overflow:hidden; font-size:12px; box-shadow:0 1px 3px rgba(0,0,0,0.03); margin-bottom:12px }
.hypothesis-review header { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; padding:12px 16px; background:#f8fafc; border-bottom:1px solid #e2e8f0 }
.hypothesis-review strong { flex:1; min-width:0; overflow-wrap:anywhere; font-weight:700; color:#0f172a; font-size:13px; line-height:1.5 }
.status-badge { flex-shrink:0; white-space:nowrap; display:inline-flex; align-items:center; justify-content:center; font-size:11px; font-weight:600; padding:3px 10px; border-radius:6px; background:#f1f5f9; color:#64748b; border:1px solid #e2e8f0; line-height:1.25 }
.status-badge.is-supported { background:#ecfdf5; color:#047857; border-color:#a7f3d0 }
.status-badge.is-refuted { background:#fef2f2; color:#b91c1c; border-color:#fecaca }

.verdict-reason { padding:10px 16px 6px; margin:0; white-space:pre-wrap; overflow-wrap:anywhere; line-height:1.65; color:#334155 }
.verdict-reason strong { color:#0f172a }

.hypothesis-review dl { display:grid; grid-template-columns:80px minmax(0,1fr); gap:10px; padding:12px 16px; margin:0 }
.hypothesis-review dt { color:#64748b; font-weight:600 }
.hypothesis-review dd { margin:0; overflow-wrap:anywhere; color:#334155; line-height:1.5 }

.observations { list-style:none; margin:0; padding:4px 16px }
.observations li { padding:10px 0; border-bottom:1px solid #f1f5f9 }
.observations li:last-child { border-bottom:none }
.observations p { margin:6px 0 0; white-space:pre-wrap; color:#334155; line-height:1.6 }

/* 证据引用蓝色文字样式：精细等宽蓝字+灵动微指示点，彻底告别生硬大矩形框 */
.obs-code {
  font-size:11.5px;
  font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  color:#2563eb;
  font-weight:600;
  display:inline-flex;
  align-items:center;
  gap:6px;
  line-height:1.5;
  letter-spacing:-0.01em;
  max-width:100%;
  overflow-wrap:anywhere;
}
.obs-code::before {
  content:"";
  display:inline-block;
  width:6px;
  height:6px;
  border-radius:9999px;
  background:#3b82f6;
  flex-shrink:0;
}

.actions { display:flex; gap:10px; padding:12px 16px; border-top:1px solid #f1f5f9; background:#fafafa }
.actions button { padding:6px 12px; font-size:12px; font-weight:500; cursor:pointer; border-radius:6px; transition:all 120ms ease }
.btn-primary-action { background:#10b981; border:1px solid #059669; color:#ffffff; font-weight:600; box-shadow:0 1px 2px rgba(16,185,129,0.2) }
.btn-primary-action:hover:not(:disabled) { background:#059669 }
.btn-secondary-action { background:#ffffff; border:1px solid #cbd5e1; color:#334155 }
.btn-secondary-action:hover:not(:disabled) { background:#f8fafc; border-color:#94a3b8 }
.actions button:disabled { opacity:.45; cursor:default }

.hint { margin:10px 16px; color:#64748b; font-size:11.5px }
</style>
