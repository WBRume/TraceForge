<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { LockKeyhole, RotateCw } from '@/components/icons'
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

function formatTime(isoString?: string | null) {
  if (!isoString || isoString === '-') return '-'
  try {
    const d = new Date(isoString)
    if (isNaN(d.getTime())) return isoString
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    const hh = String(d.getHours()).padStart(2, '0')
    const mm = String(d.getMinutes()).padStart(2, '0')
    return `${y}年${m}月${day}日 ${hh}:${mm}`
  } catch {
    return isoString
  }
}

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
        <div class="header-icon-box">
          <svg class="header-icon" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
          </svg>
        </div>
        <div>
          <h2>{{ t(`${baseKey}.panel.title`) }}</h2>
          <p class="header-subtitle">全流程覆盖专家审查、澄清会话、最终业务摘要与基线快照固化</p>
        </div>
      </div>
      <div class="workflow-header-actions">
        <WorkflowStatusPill :status="workflowStatus" />
        <el-button :disabled="loading" class="refresh-btn" @click="refresh">
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
      <!-- 顶部信息仪表盘横幅 -->
      <div class="workflow-status-strip">
        <dl>
          <div>
            <dt>{{ t(`${baseKey}.fields.task`) }}</dt>
            <dd>
              <span class="status-dot" :class="workflow.task.status === 'DONE' ? 'is-done' : 'is-coding'"></span>
              {{ statusLabel(workflow.task.status) }}
            </dd>
          </div>
          <div>
            <dt>{{ t(`${baseKey}.fields.workflow`) }}</dt>
            <dd>{{ statusLabel(workflowStatus) }}</dd>
          </div>
          <div>
            <dt>{{ t(`${baseKey}.fields.baseline`) }}</dt>
            <dd>第 {{ workflow.task.baseline_version ?? 0 }} 版</dd>
          </div>
          <div>
            <dt>{{ t(`${baseKey}.fields.blocking`) }}</dt>
            <dd :class="blockingCount > 0 ? 'text-amber-600 font-bold' : 'text-emerald-600 font-bold'">
              {{ blockingCount }} 项待办
            </dd>
          </div>
          <div>
            <dt>{{ t(`${baseKey}.fields.updated`) }}</dt>
            <dd class="text-slate-600 font-medium">{{ formatTime(latestUpdatedAt) }}</dd>
          </div>
        </dl>
      </div>

      <!-- 左侧垂直时间轴导引器 -->
      <aside class="workflow-rail">
        <FinalWorkflowStepper
          :steps="workflow.steps"
          :active-key="activeStep"
          @select="activeStep = $event"
        />
      </aside>

      <!-- 右侧步骤内容视窗 -->
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
          :reviews="workflow.reviews"
          :clarification-count="workflow.clarifications?.length ?? 0"
          :evidence-count="workflow.task.evidence_count ?? 0"
          :delta-count="workflow.task.human_delta_count ?? 0"
          :decision-count="workflow.task.decision_count ?? 0"
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
  gap: 20px;
  min-height: 520px;
}

.workflow-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 18px;
  border-bottom: 1px solid #f1f5f9;
}

.workflow-title-block {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}

.header-icon-box {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: rgba(14, 165, 233, 0.1);
  color: #0284c7;
  flex-shrink: 0;
}

.header-icon {
  width: 22px;
  height: 22px;
}

.workflow-title-block h2 {
  margin: 0;
  color: #0f172a;
  font-size: 1.25rem;
  font-weight: 800;
  line-height: 1.2;
}

.header-subtitle {
  margin: 2px 0 0;
  color: #64748b;
  font-size: 0.76rem;
}

.workflow-header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.refresh-btn {
  border-radius: 10px;
  font-weight: 600;
}

.button-icon,
.lock-icon {
  width: 14px;
  height: 14px;
  margin-right: 6px;
}

.workflow-alert {
  border-radius: 12px;
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

/* 顶部状态仪表横幅 */
.workflow-status-strip {
  grid-column: 1 / -1;
  padding: 14px 18px;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  background: #f8fafc;
}

.workflow-status-strip dl {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 14px;
  margin: 0;
}

.workflow-status-strip dt {
  color: #64748b;
  font-size: 0.72rem;
  font-weight: 600;
}

.workflow-status-strip dd {
  margin: 4px 0 0;
  overflow: hidden;
  color: #0f172a;
  font-size: 0.86rem;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}

.status-dot.is-coding {
  background: #f59e0b;
}

.status-dot.is-done {
  background: #10b981;
}

.workflow-rail {
  padding-right: 18px;
  border-right: 1px solid #f1f5f9;
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
    padding-bottom: 14px;
    border-right: 0;
    border-bottom: 1px solid #f1f5f9;
  }

  .workflow-status-strip dl {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 700px) {
  .workflow-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .workflow-header-actions {
    width: 100%;
    justify-content: space-between;
  }
}

:deep(.el-dialog) {
  border-radius: 20px;
  overflow: hidden;
  box-shadow: 0 20px 40px rgba(15, 23, 42, 0.16);
  border: 1px solid rgba(226, 232, 240, 0.9);
}

:deep(.el-dialog__header) {
  padding: 20px 24px;
  margin-right: 0;
  border-bottom: 1px solid #f1f5f9;
}

:deep(.el-dialog__title) {
  font-size: 1.05rem;
  font-weight: 800;
  color: #0f172a;
}

:deep(.el-dialog__body) {
  padding: 22px 24px;
}

:deep(.el-dialog__footer) {
  padding: 16px 24px;
  border-top: 1px solid #f1f5f9;
  background: #f8fafc;
}

:deep(.el-drawer) {
  border-top-left-radius: 24px;
  border-bottom-left-radius: 24px;
  box-shadow: -10px 0 35px rgba(15, 23, 42, 0.12);
}

:deep(.el-drawer__header) {
  padding: 20px 24px;
  margin-bottom: 0;
  border-bottom: 1px solid #f1f5f9;
}

:deep(.el-button) {
  border-radius: 10px;
  font-weight: 600;
  transition: all 0.2s ease;
}

:deep(.el-button--primary) {
  background: #0284c7;
  border-color: #0284c7;
  box-shadow: 0 2px 8px rgba(2, 132, 199, 0.25);
}

:deep(.el-button--primary:hover) {
  background: #0369a1;
  border-color: #0369a1;
}

:deep(.el-input__wrapper),
:deep(.el-textarea__inner) {
  border-radius: 10px;
  box-shadow: 0 0 0 1px #e2e8f0 inset;
  transition: all 0.2s;
}

:deep(.el-input__wrapper:hover),
:deep(.el-textarea__inner:hover) {
  box-shadow: 0 0 0 1px #93c5fd inset;
}

:deep(.el-input__wrapper.is-focus),
:deep(.el-textarea__inner:focus) {
  box-shadow: 0 0 0 2px rgba(2, 132, 199, 0.2) inset, 0 0 0 1px #0284c7 inset;
}
</style>
