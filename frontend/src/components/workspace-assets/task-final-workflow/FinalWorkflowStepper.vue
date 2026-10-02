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
      :class="{
        'is-active': activeKey === step.key,
        'is-complete': step.status === 'complete',
        'is-blocked': step.status === 'blocked',
      }"
      @click="emit('select', step.key)"
    >
      <div class="step-index-wrap">
        <span class="step-index">{{ index + 1 }}</span>
      </div>
      <div class="step-copy">
        <div class="step-title-row">
          <span class="step-title">{{ stepTitle(step) }}</span>
          <WorkflowStatusPill :status="step.status" />
        </div>
        <span class="step-detail">{{ stepNumber(index) }} · {{ stepDetail(step) }}</span>
      </div>
    </button>
  </div>
</template>

<style scoped>
.workflow-stepper {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.step-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  width: 100%;
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  background: #ffffff;
  text-align: left;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.02);
}

.step-item:hover {
  border-color: #bae6fd;
  background: #f8fafc;
  transform: translateY(-1px);
}

.step-item.is-active {
  border-color: #38bdf8;
  background: #f0f9ff;
  box-shadow: 0 4px 14px rgba(2, 132, 199, 0.08);
}

.step-index-wrap {
  flex-shrink: 0;
  margin-top: 1px;
}

.step-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #f1f5f9;
  color: #475569;
  font-size: 0.78rem;
  font-weight: 800;
  transition: all 0.2s;
}

.step-item.is-active .step-index {
  background: #0284c7;
  color: #ffffff;
}

.step-item.is-complete .step-index {
  background: #dcfce7;
  color: #15803d;
}

.step-item.is-blocked .step-index {
  background: #fef3c7;
  color: #b45309;
}

.step-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 4px;
}

.step-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
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
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1100px) {
  .workflow-stepper {
    flex-direction: row;
    overflow-x: auto;
    padding-bottom: 6px;
  }

  .step-item {
    min-width: 260px;
    flex-shrink: 0;
  }
}
</style>
