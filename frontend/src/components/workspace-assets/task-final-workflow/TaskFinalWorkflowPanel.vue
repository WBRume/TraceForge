<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { LockKeyhole, RotateCw } from 'lucide-vue-next'
import { useTaskFinalWorkflow } from '@/composables/useTaskFinalWorkflow'
import type {
  FinalWorkflowStepKey,
  ReviewTargetPreviewResponse,
  ReviewTargetRef,
} from '@/types/workspaceAssets'
import BaselineStep from './BaselineStep.vue'
import ClarificationThreadStep from './ClarificationThreadStep.vue'
import ExpertReviewStep from './ExpertReviewStep.vue'
import FinalSummaryStep from './FinalSummaryStep.vue'
import FinalWorkflowStepper from './FinalWorkflowStepper.vue'
import ReviewTargetPreviewDrawer from './ReviewTargetPreviewDrawer.vue'
import WorkflowStatusPill from './WorkflowStatusPill.vue'

const props = defineProps<{
  workspaceId: string
  taskId: string
}>()

const emit = defineEmits<{
  mutated: []
}>()

const { t, te } = useI18n()
const baseKey = 'workspace_assets.task_detail.final_workflow'
const activeStep = shallowRef<FinalWorkflowStepKey>('expert_review')
const {
  workflow,
  loading,
  saving,
  error,
  lockMessage,
  readonlyState,
  canWriteFinalWorkflow,
  canResolveClarification,
  load,
  createReview,
  updateReview,
  createClarification,
  addClarificationMessage,
  generateDraft,
  upsertFinalSummary,
  baseline,
  loadReviewTargetPreview,
} = useTaskFinalWorkflow()
const previewDrawerVisible = shallowRef(false)
const previewTarget = shallowRef<ReviewTargetRef | null>(null)
const preview = shallowRef<ReviewTargetPreviewResponse | null>(null)
const previewLoading = shallowRef(false)
const previewError = shallowRef<string | null>(null)

const operationReadonly = computed(() => readonlyState.value || !canWriteFinalWorkflow.value)
const workflowStatus = computed(() => {
  if (workflow.value?.readonly) return 'BASELINED'
  const blocked = workflow.value?.checklist.some((item) => item.blocking)
  return blocked ? 'IN_REVIEW' : 'READY'
})
const blockingCount = computed(() => workflow.value?.checklist.filter((item) => item.blocking).length ?? 0)
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

async function afterMutation(loader: () => Promise<unknown>) {
  await loader()
  emit('mutated')
}

async function openTargetPreview(target: ReviewTargetRef) {
  if (!props.workspaceId || !props.taskId) return
  previewTarget.value = target
  preview.value = null
  previewError.value = null
  previewDrawerVisible.value = true
  previewLoading.value = true
  try {
    preview.value = await loadReviewTargetPreview(props.workspaceId, props.taskId, target)
  } catch (err) {
    const responseDetail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    previewError.value = responseDetail || (err instanceof Error ? err.message : t(`${baseKey}.target_preview.error_fallback`))
  } finally {
    previewLoading.value = false
  }
}

function statusLabel(status: string | null | undefined) {
  const normalized = String(status || 'UNKNOWN').toUpperCase()
  const key = `${baseKey}.status.${normalized.toLowerCase().replace(/-/g, '_')}`
  return te(key) ? t(key) : normalized
}

watch(
  () => [props.workspaceId, props.taskId] as const,
  () => {
    refresh()
  },
  { immediate: true },
)
</script>

<template>
  <section class="task-final-workflow-panel" v-loading="loading">
    <header class="workflow-header">
      <div class="workflow-title-block">
        <p class="eyebrow">{{ t(`${baseKey}.panel.eyebrow`) }}</p>
        <h2>{{ t(`${baseKey}.panel.title`) }}</h2>
        <span>{{ t(`${baseKey}.panel.subtitle`) }}</span>
      </div>
      <div class="workflow-header-actions">
        <WorkflowStatusPill :status="workflowStatus" />
        <el-button :disabled="loading" @click="refresh">
          <RotateCw class="button-icon" />
          {{ t('common.refresh') }}
        </el-button>
      </div>
    </header>

    <el-alert
      v-if="lockMessage"
      class="workflow-alert"
      type="info"
      :closable="false"
      :title="t(`${baseKey}.panel.readonly_title`)"
    >
      <template #default>
        <div class="lock-copy">
          <LockKeyhole class="lock-icon" />
          <span>{{ t(`${baseKey}.panel.readonly_body`) }}</span>
        </div>
      </template>
    </el-alert>

    <el-alert v-if="error" class="workflow-alert" type="error" :closable="false" :title="error" />

    <div v-if="workflow" class="workflow-grid">
      <div class="workflow-status-strip">
        <dl>
          <div>
            <dt>{{ t(`${baseKey}.fields.task`) }}</dt>
            <dd>{{ statusLabel(workflow.task.status) }}</dd>
          </div>
          <div>
            <dt>{{ t(`${baseKey}.fields.workflow`) }}</dt>
            <dd>{{ statusLabel(workflowStatus) }}</dd>
          </div>
          <div>
            <dt>{{ t(`${baseKey}.fields.baseline`) }}</dt>
            <dd>v{{ workflow.task.baseline_version ?? 0 }}</dd>
          </div>
          <div>
            <dt>{{ t(`${baseKey}.fields.blocking`) }}</dt>
            <dd>{{ blockingCount }}</dd>
          </div>
          <div>
            <dt>{{ t(`${baseKey}.fields.updated`) }}</dt>
            <dd>{{ latestUpdatedAt }}</dd>
          </div>
        </dl>
      </div>

      <aside class="workflow-rail">
        <FinalWorkflowStepper
          :steps="workflow.steps"
          :active-key="activeStep"
          @select="activeStep = $event"
        />
      </aside>

      <main class="workflow-main">
        <ExpertReviewStep
          v-if="activeStep === 'expert_review'"
          :reviews="workflow.reviews"
          :review-targets="workflow.review_targets"
          :readonly="operationReadonly"
          :saving="saving"
          @create-review="(payload) => afterMutation(() => createReview(workspaceId, taskId, payload))"
          @update-review="(reviewId, payload) => afterMutation(() => updateReview(workspaceId, taskId, reviewId, payload))"
        />
        <ClarificationThreadStep
          v-else-if="activeStep === 'clarification'"
          :clarifications="workflow.clarifications"
          :threads="workflow.clarification_threads"
          :reviews="workflow.reviews"
          :review-targets="workflow.review_targets"
          :readonly="operationReadonly"
          :can-resolve-clarification="canResolveClarification"
          :saving="saving"
          @create="(payload) => afterMutation(() => createClarification(workspaceId, taskId, payload))"
          @add-message="(clarificationId, payload) => afterMutation(() => addClarificationMessage(workspaceId, taskId, clarificationId, payload))"
          @preview-target="openTargetPreview"
        />
        <FinalSummaryStep
          v-else-if="activeStep === 'final_summary'"
          :summary="workflow.final_summary ?? null"
          :checklist="workflow.checklist"
          :readonly="operationReadonly"
          :saving="saving"
          @generate-draft="afterMutation(() => generateDraft(workspaceId, taskId))"
          @save="(payload) => afterMutation(() => upsertFinalSummary(workspaceId, taskId, payload))"
        />
        <BaselineStep
          v-else
          :baseline="workflow.baseline ?? null"
          :checklist="workflow.checklist"
          :readonly="operationReadonly"
          :saving="saving"
          @baseline="afterMutation(() => baseline(workspaceId, taskId))"
        />
      </main>
    </div>

    <ReviewTargetPreviewDrawer
      v-model:visible="previewDrawerVisible"
      :target="previewTarget"
      :preview="preview"
      :loading="previewLoading"
      :error="previewError"
    />
  </section>
</template>

<style scoped>
.task-final-workflow-panel {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-height: 520px;
}

.workflow-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid #e2e8f0;
}

.workflow-title-block {
  min-width: 0;
}

.eyebrow {
  margin: 0 0 4px;
  color: #64748b;
  font-size: 0.74rem;
  font-weight: 800;
  text-transform: uppercase;
}

.workflow-title-block h2 {
  margin: 0;
  color: #0f172a;
  font-size: 1.32rem;
  line-height: 1.2;
}

.workflow-title-block span {
  display: block;
  margin-top: 6px;
  color: #64748b;
  font-size: 0.86rem;
}

.workflow-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.button-icon,
.lock-icon {
  width: 15px;
  height: 15px;
  margin-right: 6px;
}

.workflow-alert {
  border-radius: 8px;
}

.lock-copy {
  display: flex;
  align-items: center;
  gap: 8px;
}

.workflow-grid {
  display: grid;
  grid-template-columns: 310px minmax(0, 1fr);
  gap: 24px;
}

.workflow-status-strip {
  grid-column: 1 / -1;
  padding: 12px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.workflow-status-strip dl {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  margin: 0;
}

.workflow-status-strip dt {
  color: #64748b;
  font-size: 0.68rem;
  font-weight: 800;
  text-transform: uppercase;
}

.workflow-status-strip dd {
  margin: 4px 0 0;
  overflow: hidden;
  color: #0f172a;
  font-size: 0.82rem;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workflow-rail {
  padding-right: 18px;
  border-right: 1px solid #e2e8f0;
}

.workflow-main {
  min-width: 0;
}

@media (max-width: 1100px) {
  .workflow-grid {
    grid-template-columns: 1fr;
  }

  .workflow-rail {
    padding-right: 0;
    padding-bottom: 12px;
    border-right: 0;
    border-bottom: 1px solid #e2e8f0;
  }

  .workflow-status-strip dl {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 700px) {
  .workflow-header {
    flex-direction: column;
  }

  .workflow-header-actions {
    width: 100%;
    justify-content: space-between;
  }
}
</style>
