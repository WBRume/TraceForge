<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { ArrowRight, LockKeyhole, RotateCw } from '@/components/icons'
import { useTaskFinalWorkflow } from '@/composables/useTaskFinalWorkflow'
import type { TaskFinalWorkflowStep } from '@/types/workspaceAssets'
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

function stepTitle(key: string, fallback: string) {
  const titleKey = `${baseKey}.steps.${key}`
  return te(titleKey) ? t(titleKey) : fallback
}

function stepDesc(step: TaskFinalWorkflowStep) {
  const detailKey = `${baseKey}.step_details.${step.key}.${String(step.status).toLowerCase()}`
  return te(detailKey) ? t(detailKey, { count: step.blocking_count ?? 0 }) : step.detail
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

defineExpose({ refresh, workflowStatus })
</script>

<template>
  <section class="workflow-entry-card" v-loading="loading">
    <header class="panel-head">
      <div class="head-title-wrap">
        <div class="head-icon-box">
          <svg class="head-icon" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
          </svg>
        </div>
        <div>
          <h2>{{ t(`${baseKey}.entry.title`) }}</h2>
          <p class="head-subtitle">全流程覆盖专家审查、澄清会话、最终业务摘要与基线快照固化</p>
        </div>
      </div>
      <div class="entry-actions">
        <el-button :disabled="loading" class="refresh-btn" @click="refresh">
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

    <div v-if="workflow" class="entry-content">
      <!-- 顶部信息仪表盘横幅 -->
      <div class="dashboard-strip">
        <div class="strip-item">
          <span class="strip-label">{{ t(`${baseKey}.fields.task`) }}</span>
          <span class="strip-value font-bold text-slate-800">
            <span class="status-dot" :class="workflow.task.status === 'DONE' ? 'is-done' : 'is-coding'"></span>
            {{ statusLabel(workflow.task.status) }}
          </span>
        </div>
        <div class="strip-item">
          <span class="strip-label">{{ t(`${baseKey}.fields.baseline`) }}</span>
          <span class="strip-value font-semibold">第 {{ workflow.task.baseline_version ?? 0 }} 版</span>
        </div>
        <div class="strip-item">
          <span class="strip-label">{{ t(`${baseKey}.fields.blocking_items`) }}</span>
          <span class="strip-value" :class="blockingCount > 0 ? 'text-amber-600 font-bold' : 'text-emerald-600 font-bold'">
            {{ blockingCount }} 项
          </span>
        </div>
        <div class="strip-item">
          <span class="strip-label">{{ t(`${baseKey}.fields.updated`) }}</span>
          <span class="strip-value text-slate-600">{{ formatTime(latestUpdatedAt) }}</span>
        </div>
      </div>

      <!-- 4 步流程管线引导卡片 -->
      <div class="pipeline-grid">
        <RouterLink
          v-for="(step, index) in workflow.steps"
          :key="step.key"
          class="step-card"
          :class="`is-${step.status}`"
          :to="workflowRoute"
        >
          <div class="step-card-top">
            <span class="step-badge-num">{{ index + 1 }}</span>
            <WorkflowStatusPill :status="step.status" />
          </div>
          <h4 class="step-card-title">{{ stepTitle(step.key, step.title) }}</h4>
          <p class="step-card-desc">{{ stepDesc(step) }}</p>
          <div class="step-card-footer">
            <span v-if="step.blocking_count && step.blocking_count > 0" class="step-blocking-note">
              {{ step.blocking_count }} 项阻塞待办
            </span>
            <span v-else class="step-clean-note">
              流程正常
            </span>
            <span class="step-arrow">进入 →</span>
          </div>
        </RouterLink>
      </div>
    </div>
  </section>
</template>

<style scoped>
.workflow-entry-card {
  display: flex;
  min-height: 340px;
  flex-direction: column;
  gap: 20px;
  padding: 24px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(226, 232, 240, 0.9);
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.03);
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 18px;
  border-bottom: 1px solid #f1f5f9;
}

.head-title-wrap {
  display: flex;
  align-items: center;
  gap: 14px;
}

.head-icon-box {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: 12px;
  background: rgba(14, 165, 233, 0.1);
  color: #0284c7;
}

.head-icon {
  width: 22px;
  height: 22px;
}

.panel-head h2 {
  margin: 0;
  color: #0f172a;
  font-size: 1.25rem;
  font-weight: 800;
  letter-spacing: -0.01em;
}

.head-subtitle {
  margin: 2px 0 0;
  color: #64748b;
  font-size: 0.78rem;
}

.entry-actions,
.lock-copy {
  display: flex;
  align-items: center;
  gap: 12px;
}

.refresh-btn {
  border-radius: 10px;
  font-weight: 600;
}

.open-workflow-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  padding: 8px 16px;
  border-radius: 10px;
  background: #0284c7;
  color: #ffffff;
  font-size: 0.82rem;
  font-weight: 700;
  text-decoration: none;
  box-shadow: 0 2px 8px rgba(2, 132, 199, 0.25);
  transition: all 0.2s ease;
}

.open-workflow-link:hover {
  background: #0369a1;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(2, 132, 199, 0.35);
}

.button-icon {
  width: 14px;
  height: 14px;
}

.entry-alert {
  border-radius: 12px;
}

.entry-content {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

/* 顶部信息仪表盘 */
.dashboard-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  padding: 14px 18px;
  border-radius: 14px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.strip-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.strip-label {
  color: #64748b;
  font-size: 0.72rem;
  font-weight: 600;
}

.strip-value {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #0f172a;
  font-size: 0.86rem;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
}

.status-dot.is-coding {
  background: #f59e0b;
}

.status-dot.is-done {
  background: #10b981;
}

/* 4 步流向卡片 */
.pipeline-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.step-card {
  display: flex;
  flex-direction: column;
  padding: 16px;
  border-radius: 14px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  text-decoration: none;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.02);
}

.step-card:hover {
  transform: translateY(-2px);
  border-color: #7dd3fc;
  box-shadow: 0 8px 20px rgba(14, 165, 233, 0.08);
}

.step-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.step-badge-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #f1f5f9;
  color: #475569;
  font-size: 0.76rem;
  font-weight: 800;
}

.step-card.is-complete .step-badge-num {
  background: #dcfce7;
  color: #15803d;
}

.step-card.is-active .step-badge-num,
.step-card.is-ready .step-badge-num {
  background: #e0f2fe;
  color: #0369a1;
}

.step-card.is-blocked .step-badge-num {
  background: #fef3c7;
  color: #b45309;
}

.step-card-title {
  margin: 0;
  color: #0f172a;
  font-size: 0.88rem;
  font-weight: 800;
}

.step-card-desc {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 0.74rem;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 32px;
}

.step-card-footer {
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px solid #f1f5f9;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.72rem;
}

.step-blocking-note {
  color: #b45309;
  font-weight: 700;
}

.step-clean-note {
  color: #94a3b8;
}

.step-arrow {
  color: #0284c7;
  font-weight: 700;
  opacity: 0.8;
  transition: transform 0.2s;
}

.step-card:hover .step-arrow {
  transform: translateX(2px);
  opacity: 1;
}

@media (max-width: 960px) {
  .dashboard-strip,
  .pipeline-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 600px) {
  .panel-head {
    flex-direction: column;
    align-items: flex-start;
  }
  .dashboard-strip,
  .pipeline-grid {
    grid-template-columns: 1fr;
  }
}
</style>
