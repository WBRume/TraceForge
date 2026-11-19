<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import DomainMilestones from '@/components/ai/DomainMilestones.vue'
import { ArrowPathIcon } from '@/components/icons'
import type { TaskSpecBootstrapProgress } from '@/composables/chat/types'

const props = defineProps<{
  snapshot: TaskSpecBootstrapProgress
  canBuild: boolean
  building: boolean
}>()
const emit = defineEmits<{ build: [] }>()
const { t } = useI18n()

const status = computed(() => props.snapshot.status.toLowerCase())
const statusText = computed(() => t(`chat.spec_bootstrap_status_${status.value}`))
const running = computed(() => props.snapshot.status === 'RUNNING')
const phaseLabels: Record<string, string> = {
  SPEC_PREPARE: 'prepare',
  SPEC_READ: 'read',
  SPEC_REFRESH: 'refresh',
  SPEC_ANALYZE: 'analyze',
  SPEC_VERIFY: 'verify',
}
const milestones = computed(() => props.snapshot.domain_milestones?.map(event => {
  const phase = event.tool === 'spec_bootstrap' ? phaseLabels[event.call_id] : undefined
  return phase ? { ...event, message: t(`doc_review.baseline_phase_${phase}`) } : event
}))
</script>

<template>
  <div class="spec-baseline" :data-status="status">
    <span class="baseline-chip" role="status" :title="snapshot.error_message || undefined">
      <span class="baseline-dot" aria-hidden="true" />
      {{ statusText }}
      <span v-if="running" class="baseline-progress">{{ snapshot.progress }}%</span>
    </span>
    <DomainMilestones :active="running" :events="milestones" compact />
    <button
      v-if="canBuild"
      type="button"
      class="baseline-build"
      :disabled="building"
      @click="emit('build')"
    >
      <ArrowPathIcon aria-hidden="true" />
      {{ t('chat.spec_bootstrap_action_build') }}
    </button>
  </div>
</template>

<style scoped>
.spec-baseline {
  display: inline-flex;
  align-items: center;
  gap: .45rem;
  min-width: 0;
  max-width: 100%;
  font-size: .75rem;
  color: #475569;
}
.baseline-chip, .baseline-build { display: inline-flex; align-items: center; gap: .35rem; white-space: nowrap; }
.baseline-chip { padding: .2rem .5rem; border-radius: 999px; background: #edf2f7; }
.baseline-dot { width: .4rem; height: .4rem; border-radius: 50%; background: currentColor; }
.spec-baseline[data-status="running"] .baseline-chip { background: #e0f2fe; color: #075985; }
.spec-baseline[data-status="ready"] .baseline-chip { background: #e8f7ef; color: #166534; }
.spec-baseline[data-status="failed"] .baseline-chip,
.spec-baseline[data-status="stale"] .baseline-chip { background: #fff3dd; color: #92400e; }
.baseline-progress { font-weight: 600; font-variant-numeric: tabular-nums; }
.baseline-build {
  appearance: none;
  border: 1px solid #d7e7f1;
  background: transparent;
  padding: .2rem .45rem;
  border-radius: .4rem;
  color: #0369a1;
  font: inherit;
}
.baseline-build:hover:not(:disabled) { background: #e0f2fe; }
.baseline-build:disabled { opacity: .55; }
.baseline-build svg { width: .8rem; height: .8rem; }
</style>
