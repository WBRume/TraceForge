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
    <header><strong>{{ hypothesis.id }} · {{ hypothesis.claim }}</strong><span>{{ status }}</span></header>
    <dl><dt>预测</dt><dd>{{ hypothesis.prediction }}</dd><dt>证伪条件</dt><dd>{{ hypothesis.falsifier }}</dd></dl>
    <p v-if="hypothesis.verdict_reason" class="verdict-reason"><strong>判定依据：</strong>{{ hypothesis.verdict_reason }}</p>
    <p v-else class="hint">尚无结构化判定，请补充排查；有证据记录不等于该证据支持假说。</p>
    <ul class="observations"><li v-for="(entry, i) in hypothesis.evidence" :key="i"><code>{{ entry.reference }}</code><p>{{ entry.observation }}</p></li></ul>
    <p v-if="!hypothesis.evidence.length" class="hint">尚无本次证据，请补充排查后再确认。</p>
    <div class="actions">
      <button v-if="isSupportedHypothesis(hypothesis)" :disabled="disabled || hypothesis.state !== 'PROPOSED'"
        @click="emit('command', 'approve_hypothesis', hypothesis.id)">{{ hypothesis.state === 'APPROVED' ? '已确认根因' : '确认根因' }}</button>
      <button v-if="hypothesis.verdict !== 'REFUTED'" :disabled="disabled" @click="emit('command', hypothesis.state === 'EXCLUDED' ? 'restore_hypothesis' : 'exclude_hypothesis', hypothesis.id)">{{ hypothesis.state === 'EXCLUDED' ? '恢复假说' : '排除假说' }}</button>
    </div>
  </section>
</template>

<style scoped>
.hypothesis-review { background:white; border:1px solid #dbe5f1; border-radius:8px; min-width:0; overflow:hidden; font-size:12px }
.verdict-reason { padding:0 14px; white-space:pre-wrap; overflow-wrap:anywhere; line-height:1.7 }
.hypothesis-review header { display:flex; justify-content:space-between; gap:12px; padding:14px; border-bottom:1px solid #e5edf5 }.hypothesis-review strong { overflow-wrap:anywhere; font-weight:600 }.hypothesis-review header span { color:#64748b; flex-shrink:0 }
.hypothesis-review dl { display:grid; grid-template-columns:70px minmax(0,1fr); gap:12px; padding:14px; margin:0 }.hypothesis-review dt { color:#64748b }.hypothesis-review dd { margin:0; overflow-wrap:anywhere }
.observations { list-style:none; margin:0; padding:0 14px }.observations li { padding:12px 0; border-bottom:1px solid #edf2f7 }.observations p { margin:6px 0; white-space:pre-wrap }.observations code { font-size:11px; overflow-wrap:anywhere; color:#2563eb }
.actions { display:flex; gap:8px; padding:14px }.actions button { padding:7px 10px; font-size:12px; cursor:pointer; border:1px solid #dbe5f1; border-radius:5px; background:white; color:#2563eb }.actions button:disabled { opacity:.45; cursor:default }.hint { margin:14px; color:#64748b }
</style>
