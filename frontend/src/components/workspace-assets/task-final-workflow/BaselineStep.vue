<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Copy, LockKeyhole, ShieldCheck } from 'lucide-vue-next'
import type { BaselineCheckItem, TaskBaseline } from '@/types/workspaceAssets'
import WorkflowChecklist from './WorkflowChecklist.vue'
import WorkflowStatusPill from './WorkflowStatusPill.vue'

const props = defineProps<{
  baseline: TaskBaseline | null
  checklist: BaselineCheckItem[]
  readonly: boolean
  saving: boolean
}>()

const emit = defineEmits<{
  baseline: []
}>()

const { t } = useI18n()
const baseKey = 'workspace_assets.task_detail.final_workflow'
const blocked = computed(() => props.checklist.some((item) => item.blocking))
const snapshotCounts = computed(() => {
  const snapshot = props.baseline?.snapshot as { counts?: Record<string, number> } | null | undefined
  return snapshot?.counts ?? {}
})

async function copyBaselineId() {
  if (props.baseline?.id) {
    await navigator.clipboard?.writeText(props.baseline.id)
  }
}
</script>

<template>
  <section class="baseline-step">
    <div class="step-heading">
      <div>
        <p class="eyebrow">{{ t(`${baseKey}.steps.step_label`, { number: 4 }) }}</p>
        <h3 class="step-title">{{ t(`${baseKey}.steps.baseline`) }}</h3>
      </div>
      <WorkflowStatusPill :status="baseline ? 'BASELINED' : 'PENDING'" />
    </div>

    <div v-if="baseline" class="baseline-snapshot">
      <div class="snapshot-head">
        <LockKeyhole class="snapshot-icon" />
        <div>
          <h4>{{ t(`${baseKey}.baseline.version`, { version: baseline.version }) }}</h4>
          <span>{{ baseline.created_at || t(`${baseKey}.baseline.frozen_snapshot`) }}</span>
        </div>
        <el-button text @click="copyBaselineId">
          <Copy class="button-icon" />
          {{ t(`${baseKey}.baseline.copy_id`) }}
        </el-button>
      </div>
      <dl class="snapshot-grid">
        <div>
          <dt>{{ t(`${baseKey}.fields.reviews`) }}</dt>
          <dd>{{ snapshotCounts.reviews ?? 0 }}</dd>
        </div>
        <div>
          <dt>{{ t(`${baseKey}.fields.clarifications`) }}</dt>
          <dd>{{ snapshotCounts.clarifications ?? 0 }}</dd>
        </div>
        <div>
          <dt>{{ t(`${baseKey}.fields.evidence`) }}</dt>
          <dd>{{ snapshotCounts.evidence ?? 0 }}</dd>
        </div>
        <div>
          <dt>{{ t(`${baseKey}.fields.decisions`) }}</dt>
          <dd>{{ snapshotCounts.decisions ?? 0 }}</dd>
        </div>
      </dl>
    </div>

    <div v-else class="baseline-readiness">
      <WorkflowChecklist :items="checklist" />
      <div class="baseline-actions">
        <el-button
          :disabled="readonly || blocked || saving"
          :loading="saving"
          type="primary"
          @click="emit('baseline')"
        >
          <ShieldCheck class="button-icon" />
          {{ t(`${baseKey}.baseline.freeze`) }}
        </el-button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.baseline-step {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.step-heading,
.snapshot-head,
.baseline-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.eyebrow {
  margin: 0 0 4px;
  color: #64748b;
  font-size: 0.74rem;
  font-weight: 800;
  text-transform: uppercase;
}

.step-title {
  margin: 0;
  color: #0f172a;
  font-size: 1.05rem;
}

.baseline-snapshot {
  padding: 18px;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
  background: #f0fdf4;
}

.snapshot-icon {
  width: 28px;
  height: 28px;
  color: #15803d;
}

.snapshot-head h4 {
  margin: 0;
  color: #14532d;
}

.snapshot-head span {
  color: #166534;
  font-size: 0.8rem;
}

.snapshot-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 18px 0 0;
}

.snapshot-grid div {
  padding: 12px;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
  background: #ffffff;
}

.snapshot-grid dt {
  color: #64748b;
  font-size: 0.72rem;
  font-weight: 800;
  text-transform: uppercase;
}

.snapshot-grid dd {
  margin: 5px 0 0;
  color: #0f172a;
  font-size: 1.2rem;
  font-weight: 800;
}

.baseline-readiness {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
}

.baseline-actions {
  justify-content: flex-end;
}

.button-icon {
  width: 15px;
  height: 15px;
  margin-right: 6px;
}

@media (max-width: 700px) {
  .snapshot-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
