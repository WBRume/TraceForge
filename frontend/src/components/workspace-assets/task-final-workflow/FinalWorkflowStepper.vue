<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { FinalWorkflowStepKey, TaskFinalWorkflowStep } from '@/types/workspaceAssets'
import WorkflowStatusPill from './WorkflowStatusPill.vue'

defineProps<{
  steps: TaskFinalWorkflowStep[]
  activeKey: FinalWorkflowStepKey
}>()

const emit = defineEmits<{
  select: [key: FinalWorkflowStepKey]
}>()

const { t, te } = useI18n()
const baseKey = 'workspace_assets.task_detail.final_workflow'

function stepNumber(index: number) {
  return t(`${baseKey}.steps.step_label`, { number: index + 1 })
}

function stepTitle(step: TaskFinalWorkflowStep) {
  return t(`${baseKey}.steps.${step.key}`)
}

function stepDetail(step: TaskFinalWorkflowStep) {
  const key = `${baseKey}.step_details.${step.key}.${String(step.status).toLowerCase()}`
  return te(key) ? t(key, { count: step.blocking_count ?? 0 }) : step.detail
}
</script>

<template>
  <div class="workflow-stepper">
    <button
      v-for="(step, index) in steps"
      :key="step.key"
      type="button"
      class="step-item"
      :class="{ 'is-active': activeKey === step.key, 'is-complete': step.status === 'complete' }"
      @click="emit('select', step.key)"
    >
      <span class="step-index">{{ index + 1 }}</span>
      <span class="step-copy">
        <span class="step-title">{{ stepTitle(step) }}</span>
        <span class="step-detail">{{ stepNumber(index) }} · {{ stepDetail(step) }}</span>
      </span>
      <WorkflowStatusPill :status="step.status" />
    </button>
  </div>
</template>

<style scoped>
.workflow-stepper {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.step-item {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 64px;
  padding: 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.step-item:hover {
  border-color: #dbeafe;
  background: #f8fafc;
}

.step-item.is-active {
  border-color: #93c5fd;
  background: #eff6ff;
}

.step-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #e2e8f0;
  color: #475569;
  font-size: 0.8rem;
  font-weight: 800;
}

.step-item.is-complete .step-index {
  background: #dcfce7;
  color: #15803d;
}

.step-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.step-title {
  color: #0f172a;
  font-size: 0.86rem;
  font-weight: 800;
}

.step-detail {
  overflow: hidden;
  color: #64748b;
  font-size: 0.72rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 900px) {
  .workflow-stepper {
    flex-direction: row;
    overflow-x: auto;
    padding-bottom: 4px;
  }

  .step-item {
    min-width: 240px;
  }
}
</style>
