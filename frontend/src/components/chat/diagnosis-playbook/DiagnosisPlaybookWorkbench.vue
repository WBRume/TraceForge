<script setup lang="ts">
import { computed } from 'vue'
import type { PlaybookRun } from '@/types/diagnosisPlaybook'
import PlaybookStageRail from './PlaybookStageRail.vue'
import HypothesisCard from './HypothesisCard.vue'
import PhysicalEvidenceDrawer from './PhysicalEvidenceDrawer.vue'
import HypothesisDAG from './HypothesisDAG.vue'
import VerificationComparison from './VerificationComparison.vue'
const props = defineProps<{ run: PlaybookRun; elapsed: number; tail: string; error: string; busy: boolean; canContinue: boolean }>()
const emit = defineEmits<{ command: [action: string, extra?: Record<string, unknown>] }>()
const isolation = computed(() => ({ CONTAINER_SANDBOX: '容器沙箱物理隔离', WORKTREE_BROKER: '受管工作树隔离', ADVISORY_GUARD: '建议级软防护（本地未隔离）' }[props.run.enforcement ?? ''] ?? '环境尚未绑定'))
</script>
<template>
  <section id="diagnosis-playbook-workbench" class="playbook-workbench" aria-label="故障诊断规程">
    <header><strong>{{ run.title }} · {{ run.spec_version }}</strong><span :class="['isolation', run.enforcement]">{{ isolation }}</span></header>
    <PlaybookStageRail :run="run" :elapsed="elapsed" />
    <p v-if="run.missing_facts?.length" role="status">待补充：{{ run.missing_facts.join('、') }}</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <div v-if="run.missing_facts?.includes('CASE_SELECTION_REQUIRED')">
      <p>此任务关联了多个案例，请选择本次技术验证归档的位置：</p>
      <button v-for="candidate in run.case_candidates" :key="candidate.id" :disabled="busy" @click="emit('command', 'select_case', { case_id: candidate.id })">{{ candidate.title }}</button>
    </div>
    <HypothesisDAG :hypotheses="run.hypotheses" />
    <HypothesisCard v-for="hypothesis in run.hypotheses" :key="hypothesis.id" :hypothesis="hypothesis" :disabled="busy || ['AGENT_RUNNING', 'VERIFYING', 'RECOVERING', 'COMPLETED', 'CANCELLED'].includes(run.state)" @decide="(action, id, reason) => emit('command', action, { hypothesis_id: id, reason })" />
    <VerificationComparison :receipts="run.evidence.filter(receipt => receipt.run_epoch === run.run_epoch)" />
    <PhysicalEvidenceDrawer :receipts="run.evidence" :tail="tail" :workspace-id="run.workspace_id" :task-id="run.task_id" :run-id="run.id" />
    <div class="actions">
      <button v-if="canContinue && !run.missing_facts?.includes('CASE_SELECTION_REQUIRED')" :disabled="busy" @click="emit('command', 'continue')">继续排查</button>
      <button v-if="!['COMPLETED','CANCELLED'].includes(run.state)" :disabled="busy" @click="emit('command', 'cancel')">停止排查</button>
      <span v-if="run.projection">已生成物理验证案例</span>
    </div>
  </section>
</template>
<style scoped>
.playbook-workbench { flex-shrink:0; min-width:0; max-height:45vh; overflow:auto; margin:8px 16px; padding:14px; border:1px solid var(--border-color,#ddd); border-radius:8px; font-size:13px; overflow-wrap:anywhere }.playbook-workbench header { display:flex; justify-content:space-between; gap:8px; flex-wrap:wrap }.isolation { color:#2563eb; font-size:11px }.isolation.ADVISORY_GUARD { color:#a16207 }.actions { display:flex; gap:12px }.actions button { padding:4px 10px; border:1px solid var(--border-color,#ddd); border-radius:4px }
</style>
