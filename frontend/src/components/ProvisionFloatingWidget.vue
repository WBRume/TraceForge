<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { AlertTriangle, CheckCircle2, Loader2, Minimize2, X } from 'lucide-vue-next'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import { useProvisioningStore, type ProvisionJobView } from '@/stores/provisioning'
import { formatApiError } from '@/utils/error'

const store = useProvisioningStore()
const router = useRouter()
const { t } = useI18n()

const KNOWN_ERROR_KEYS = new Set(['task_status_not_ready', 'load_failed', 'failed_fallback', 'job_not_found'])

const jobs = computed(() => store.jobList)
const activeJobs = computed(() => jobs.value.filter((job) => !job.terminal))
const terminalJobs = computed(() => jobs.value.filter((job) => job.terminal))
const pillVisible = computed(() => jobs.value.length > 0)

// 取消确认弹窗（沿用 ConfirmActionModal 全局风格）
const cancelTarget = ref<ProvisionJobView | null>(null)
const cancelling = ref(false)

const stageText = (job: ProvisionJobView) => {
  if (job.ready) return t('provisioning.stage_completed')
  const stage = String(job.cancelRequested && !job.terminal ? 'CANCELLING' : job.stage || '').toUpperCase()
  const map: Record<string, string> = {
    QUEUED: t('provisioning.stage_queued'),
    VALIDATING_INPUT: t('provisioning.stage_validating'),
    WAITING_REPO_LOCK: t('provisioning.stage_waiting_lock'),
    WAITING_TASK_QUEUE: t('provisioning.stage_waiting_queue'),
    WAITING_EXECUTION_QUEUE: t('provisioning.stage_waiting_queue'),
    CLONING_REPOSITORY: t('provisioning.stage_cloning'),
    CREATING_WORKSPACE: t('provisioning.stage_creating_workspace'),
    PREPARING_TASK: t('provisioning.stage_preparing_task'),
    PREPARING_WORKTREE: t('provisioning.stage_preparing_worktree'),
    PREPARING_LOCAL_WORKSPACE: t('provisioning.stage_preparing_local'),
    CANCELLING: t('provisioning.stage_cancelling'),
    CANCELLED: t('provisioning.stage_cancelled'),
    COMPLETED: t('provisioning.stage_completed'),
    FAILED: t('provisioning.stage_failed'),
  }
  return map[stage] || stage || t('provisioning.stage_running')
}

const jobErrorText = (job: ProvisionJobView) => {
  if (!job.errorMessage) return ''
  return KNOWN_ERROR_KEYS.has(job.errorMessage) ? t(`provisioning.${job.errorMessage}`) : job.errorMessage
}

const jobTitle = (job: ProvisionJobView) => job.taskName || t('provisioning.task_provision_title')

const aggregateProgress = computed(() => {
  if (activeJobs.value.length === 0) return 100
  const total = activeJobs.value.reduce((sum, job) => sum + job.progress, 0)
  return Math.round(total / activeJobs.value.length)
})

const hasTerminalAttention = computed(() =>
  terminalJobs.value.some((job) => !job.ready),
)

const pillIcon = computed(() => {
  if (hasTerminalAttention.value) return 'attention'
  if (activeJobs.value.length === 0) return 'success'
  return 'running'
})

const pillProgressText = computed(() => {
  if (activeJobs.value.length > 0) return `${aggregateProgress.value}%`
  if (hasTerminalAttention.value) return ''
  return '100%'
})

const openCancelConfirm = (job: ProvisionJobView) => {
  if (job.cancelRequested) return
  cancelTarget.value = job
}

const closeCancelConfirm = () => {
  if (cancelling.value) return
  cancelTarget.value = null
}

const confirmCancel = async () => {
  const job = cancelTarget.value
  if (!job) return
  cancelling.value = true
  try {
    await store.cancel(job.jobId)
    cancelTarget.value = null
  } catch (err) {
    ElMessage.error(formatApiError(err, t('provisioning.cancel_failed'), t))
  } finally {
    cancelling.value = false
  }
}

const handleEnterSession = (job: ProvisionJobView) => {
  const workspaceId = String(job.workspaceId || '').trim()
  const taskId = String(job.taskId || '').trim()
  store.dismiss(job.jobId)
  if (workspaceId && taskId) {
    router.push(`/ws/${workspaceId}/chat/${taskId}`)
  }
}

const handleDismiss = (job: ProvisionJobView) => {
  store.dismiss(job.jobId)
}
</script>

<template>
  <div v-if="pillVisible" class="provision-widget">
    <!-- 最小化 pill：不遮挡全局，点击展开 -->
    <button
      v-if="!store.expanded"
      type="button"
      class="widget-pill"
      :class="{ 'widget-pill-alert': hasTerminalAttention }"
      @click="store.expand()"
    >
      <CheckCircle2 v-if="pillIcon === 'success'" class="w-4 h-4 widget-ok" />
      <AlertTriangle v-else-if="pillIcon === 'attention'" class="w-4 h-4 widget-alert-icon" />
      <Loader2 v-else class="w-4 h-4 widget-spin" />
      <span v-if="pillProgressText" class="widget-pill-progress">{{ pillProgressText }}</span>
      <span v-if="activeJobs.length > 1" class="widget-pill-count">{{ activeJobs.length }}</span>
      <span v-else-if="activeJobs.length === 1" class="widget-pill-task">{{ jobTitle(activeJobs[0]) }}</span>
    </button>

    <!-- 展开面板：右下角浮卡，不遮罩全局 -->
    <div v-else class="widget-panel glass-panel">
      <header class="widget-header">
        <h3>{{ t('provisioning.widget_title') }}</h3>
        <button
          class="widget-icon-btn"
          type="button"
          :title="t('provisioning.minimize')"
          @click="store.minimize()"
        >
          <Minimize2 class="w-4 h-4" />
        </button>
      </header>

      <p v-if="activeJobs.length === 0 && terminalJobs.length > 0" class="widget-hint">
        {{ t('provisioning.all_finished_hint') }}
      </p>

      <div class="widget-body">
        <div v-for="job in jobs" :key="job.jobId" class="widget-job" :class="{ 'widget-job-error': job.terminal && !job.ready }">
          <div class="widget-job-head">
            <span class="widget-job-name" :title="jobTitle(job)">{{ jobTitle(job) }}</span>
            <span class="widget-job-stage">{{ stageText(job) }}</span>
          </div>

          <div v-if="!job.terminal" class="widget-job-progress">
            <el-progress
              :percentage="Math.max(0, Math.min(Number(job.progress || 0), 100))"
              :stroke-width="6"
              :show-text="false"
            />
            <div class="widget-job-meta">
              <span class="widget-job-percent">{{ job.progress }}%</span>
              <span class="widget-job-message">{{ job.message || t('provisioning.task_provision_waiting') }}</span>
            </div>
          </div>

          <div v-else-if="job.ready" class="widget-job-success">
            <CheckCircle2 class="w-4 h-4 widget-ok" />
            <span>{{ t('provisioning.job_ready') }}</span>
          </div>

          <div v-else class="widget-job-error-box">
            <AlertTriangle class="w-4 h-4 widget-alert-icon" />
            <span>{{ jobErrorText(job) || t('provisioning.failed_fallback') }}</span>
          </div>

          <div class="widget-job-actions">
            <button
              v-if="job.ready"
              type="button"
              class="widget-btn-primary"
              @click="handleEnterSession(job)"
            >
              {{ t('provisioning.task_provision_enter_session') }}
            </button>
            <button
              v-else-if="!job.terminal"
              type="button"
              class="widget-btn-secondary"
              :disabled="job.cancelRequested"
              @click="openCancelConfirm(job)"
            >
              <Loader2 v-if="job.cancelRequested" class="w-3.5 h-3.5 widget-spin" />
              {{ job.cancelRequested ? t('provisioning.cancelling') : t('common.cancel') }}
            </button>
            <button
              v-else
              type="button"
              class="widget-icon-btn"
              :title="t('common.close')"
              @click="handleDismiss(job)"
            >
              <X class="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 取消任务创建确认弹窗（沿用全局 ConfirmActionModal 风格） -->
    <ConfirmActionModal
      :show="Boolean(cancelTarget)"
      :title="t('provisioning.cancel_confirm_title')"
      :message="t('provisioning.cancel_confirm', { name: cancelTarget ? jobTitle(cancelTarget) : '' })"
      :cancel-text="t('common.cancel')"
      :confirm-text="t('common.confirm')"
      tone="danger"
      :loading="cancelling"
      @cancel="closeCancelConfirm"
      @confirm="confirmCancel"
    />
  </div>
</template>

<style scoped>
.provision-widget {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 110;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
}

.widget-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  background: #ffffff;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.15);
  cursor: pointer;
  font-size: 0.8rem;
  font-weight: 600;
  color: #334155;
  max-width: 280px;
}

.widget-pill:hover {
  border-color: #cbd5e1;
  background: #f8fafc;
}

.widget-pill-alert {
  border-color: #fecaca;
  color: #b91c1c;
}

.widget-pill-progress {
  font-variant-numeric: tabular-nums;
}

.widget-pill-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 999px;
  background: #0f172a;
  color: #ffffff;
  font-size: 0.7rem;
}

.widget-pill-task {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
  color: #64748b;
}

.widget-panel {
  width: min(380px, calc(100vw - 40px));
  max-height: min(520px, calc(100vh - 40px));
  display: flex;
  flex-direction: column;
  padding: 14px 16px;
  background: #ffffff;
  border-radius: 14px;
  box-shadow: 0 20px 50px rgba(15, 23, 42, 0.25);
}

.widget-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.widget-header h3 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 700;
  color: #0f172a;
}

.widget-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #64748b;
  cursor: pointer;
}

.widget-icon-btn:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.widget-hint {
  margin: 0 0 6px;
  font-size: 0.78rem;
  color: #64748b;
}

.widget-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
}

.widget-job {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #f8fafc;
}

.widget-job-error {
  border-color: #fecaca;
  background: #fef2f2;
}

.widget-job-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.widget-job-name {
  font-size: 0.85rem;
  font-weight: 700;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.widget-job-stage {
  flex-shrink: 0;
  font-size: 0.72rem;
  font-weight: 600;
  color: #475569;
}

.widget-job-progress {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.widget-job-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.72rem;
  color: #64748b;
}

.widget-job-percent {
  font-weight: 700;
  color: var(--color-primary-600, #0284c7);
  font-variant-numeric: tabular-nums;
}

.widget-job-message {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.widget-job-success {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
  color: #15803d;
}

.widget-job-error-box {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 0.78rem;
  color: #b91c1c;
  line-height: 1.5;
  word-break: break-all;
}

.widget-job-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.widget-btn-secondary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  color: #475569;
  padding: 5px 12px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 0.75rem;
  cursor: pointer;
}

.widget-btn-secondary:hover:not(:disabled) {
  background: #f8fafc;
  border-color: #cbd5e1;
}

.widget-btn-secondary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.widget-btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: var(--color-primary-600, #0284c7);
  color: #ffffff;
  padding: 5px 14px;
  border-radius: 8px;
  font-weight: 650;
  font-size: 0.75rem;
  cursor: pointer;
}

.widget-btn-primary:hover {
  background: var(--color-primary-700, #0369a1);
}

.widget-spin {
  animation: widget-spin 1s linear infinite;
  color: var(--color-primary-600, #0284c7);
}

.widget-alert-icon {
  color: #dc2626;
  flex-shrink: 0;
}

.widget-ok {
  color: #16a34a;
  flex-shrink: 0;
}

@keyframes widget-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
