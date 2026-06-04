<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { ArrowRight, LockKeyhole, RotateCw, ShieldCheck } from 'lucide-vue-next'
import { useTaskFinalWorkflow } from '@/composables/useTaskFinalWorkflow'
import WorkflowStatusPill from './WorkflowStatusPill.vue'

const props = defineProps<{
  workspaceId: string
  taskId: string
}>()

const { t, te } = useI18n()
const baseKey = 'workspace_assets.task_detail.final_workflow'
const {
  workflow,
  loading,
  error,
  lockMessage,
  load,
} = useTaskFinalWorkflow()

const workflowRoute = computed(() => ({
  name: 'workspaceAssetsTaskFinalWorkflow',
  params: { wsId: props.workspaceId, taskId: props.taskId },
}))
const blockingCount = computed(() => workflow.value?.checklist.filter((item) => item.blocking).length ?? 0)
const workflowStatus = computed(() => {
  if (workflow.value?.readonly) return 'BASELINED'
  return blockingCount.value > 0 ? 'IN_REVIEW' : 'READY'
})
const latestUpdatedAt = computed(() =>
  workflow.value?.baseline?.created_at
  || workflow.value?.final_summary?.updated_at
  || workflow.value?.task.updated_at
  || '-',
)

async function refresh() {
  if (!props.workspaceId || !props.taskId) return
  await load(props.workspaceId, props.taskId)
}

function stepTitle(key: string, fallback: string) {
  const titleKey = `${baseKey}.steps.${key}`
  return te(titleKey) ? t(titleKey) : fallback
}

function statusLabel(status: string | null | undefined) {
  const normalized = String(status || 'UNKNOWN').toUpperCase()
  const key = `${baseKey}.status.${normalized.toLowerCase().replace(/-/g, '_')}`
  return te(key) ? t(key) : normalized
}

watch(
  () => [props.workspaceId, props.taskId] as const,
  () => {
    void refresh()
  },
  { immediate: true },
)
</script>

<template>
  <section class="workflow-entry" v-loading="loading">
    <header class="entry-header">
      <div class="entry-title-block">
        <div class="entry-icon-box">
          <ShieldCheck class="entry-icon" />
        </div>
        <div>
          <p class="eyebrow">{{ t(`${baseKey}.entry.eyebrow`) }}</p>
          <h3>{{ t(`${baseKey}.entry.title`) }}</h3>
          <span>{{ t(`${baseKey}.entry.subtitle`) }}</span>
        </div>
      </div>
      <div class="entry-actions">
        <el-button :disabled="loading" @click="refresh">
          <RotateCw class="button-icon" />
          {{ t('common.refresh') }}
        </el-button>
        <RouterLink class="open-workflow-link" :to="workflowRoute">
          <span>{{ t(`${baseKey}.entry.open`) }}</span>
          <ArrowRight class="button-icon" />
        </RouterLink>
      </div>
    </header>

    <el-alert v-if="error" type="error" :closable="false" :title="error" class="entry-alert" />
    <el-alert v-else-if="lockMessage" type="info" :closable="false" class="entry-alert">
      <template #title>{{ t(`${baseKey}.entry.readonly_title`) }}</template>
      <template #default>
        <div class="lock-copy">
          <LockKeyhole class="button-icon" />
          <span>{{ t(`${baseKey}.entry.readonly_body`) }}</span>
        </div>
      </template>
    </el-alert>

    <div v-if="workflow" class="entry-summary">
      <div class="summary-row">
        <span>{{ t(`${baseKey}.fields.current_status`) }}</span>
        <WorkflowStatusPill :status="workflowStatus" />
      </div>
      <dl class="summary-grid">
        <div>
          <dt>{{ t(`${baseKey}.fields.task`) }}</dt>
          <dd>{{ statusLabel(workflow.task.status) }}</dd>
        </div>
        <div>
          <dt>{{ t(`${baseKey}.fields.baseline`) }}</dt>
          <dd>v{{ workflow.task.baseline_version ?? 0 }}</dd>
        </div>
        <div>
          <dt>{{ t(`${baseKey}.fields.blocking_items`) }}</dt>
          <dd>{{ blockingCount }}</dd>
        </div>
        <div>
          <dt>{{ t(`${baseKey}.fields.updated`) }}</dt>
          <dd>{{ latestUpdatedAt }}</dd>
        </div>
      </dl>
      <div class="step-strip">
        <div v-for="step in workflow.steps" :key="step.key" class="step-dot" :class="`is-${step.status}`">
          <span>{{ stepTitle(step.key, step.title) }}</span>
          <small>{{ step.blocking_count }}</small>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.workflow-entry {
  display: flex;
  min-height: 360px;
  flex-direction: column;
  gap: 18px;
}

.entry-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid #e2e8f0;
}

.entry-title-block,
.entry-actions,
.lock-copy,
.summary-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.entry-icon-box {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: 8px;
  background: #eff6ff;
  color: #2563eb;
}

.entry-icon {
  width: 22px;
  height: 22px;
}

.eyebrow {
  margin: 0 0 4px;
  color: #64748b;
  font-size: 0.72rem;
  font-weight: 800;
  text-transform: uppercase;
}

.entry-title-block h3 {
  margin: 0;
  color: #0f172a;
  font-size: 1.1rem;
  line-height: 1.25;
}

.entry-title-block span {
  display: block;
  margin-top: 5px;
  color: #64748b;
  font-size: 0.84rem;
}

.entry-actions {
  flex-wrap: wrap;
  justify-content: flex-end;
}

.open-workflow-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 32px;
  padding: 8px 12px;
  border-radius: 8px;
  background: #2563eb;
  color: #ffffff;
  font-size: 0.82rem;
  font-weight: 700;
  text-decoration: none;
}

.open-workflow-link:hover {
  background: #1d4ed8;
}

.button-icon {
  width: 15px;
  height: 15px;
}

.entry-alert {
  border-radius: 8px;
}

.entry-summary {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.summary-row {
  justify-content: space-between;
  color: #64748b;
  font-size: 0.82rem;
  font-weight: 700;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 0;
}

.summary-grid div {
  min-width: 0;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #ffffff;
}

.summary-grid dt {
  color: #64748b;
  font-size: 0.68rem;
  font-weight: 800;
  text-transform: uppercase;
}

.summary-grid dd {
  margin: 5px 0 0;
  overflow: hidden;
  color: #0f172a;
  font-size: 0.9rem;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.step-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.step-dot {
  min-width: 0;
  padding: 10px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.step-dot span,
.step-dot small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.step-dot span {
  color: #0f172a;
  font-size: 0.78rem;
  font-weight: 800;
}

.step-dot small {
  margin-top: 4px;
  color: #64748b;
  font-size: 0.7rem;
}

.step-dot.is-blocked {
  border-color: #fecaca;
  background: #fef2f2;
}

.step-dot.is-complete {
  border-color: #bbf7d0;
  background: #f0fdf4;
}

@media (max-width: 900px) {
  .entry-header {
    flex-direction: column;
  }

  .entry-actions {
    justify-content: flex-start;
  }

  .summary-grid,
  .step-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 560px) {
  .summary-grid,
  .step-strip {
    grid-template-columns: 1fr;
  }
}
</style>
