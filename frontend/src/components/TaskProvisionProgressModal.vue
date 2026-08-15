<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { AlertTriangle, CheckCircle2, Loader2, X } from 'lucide-vue-next'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import { useProvisioningStore } from '@/stores/provisioning'

type ProvisionJobStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED'

type ProvisionJob = {
  job_id: string
  job_type: string
  status: ProvisionJobStatus
  progress: number
  stage: string
  message?: string | null
  error_message?: string | null
}

const props = defineProps<{
  show: boolean
  jobId: string
  taskId: string
  workspaceId: string
}>()

const emit = defineEmits<{
  close: []
  openSession: []
}>()

const { t } = useI18n()
const provisioningStore = useProvisioningStore()

const job = ref<ProvisionJob | null>(null)
const errorText = ref('')
const polling = ref(false)
const ready = ref(false)
const enteringSession = ref(false)
let timer: number | null = null

const stageText = computed(() => {
  const stage = String(job.value?.stage || '').toUpperCase()
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
    COMPLETED: t('provisioning.stage_completed'),
    FAILED: t('provisioning.stage_failed'),
  }
  return map[stage] || stage || t('provisioning.stage_running')
})

const progressValue = computed(() => Math.max(0, Math.min(Number(job.value?.progress || 0), 100)))
const isFailed = computed(() => job.value?.status === 'FAILED' || Boolean(errorText.value))
const hasFinished = computed(() => isFailed.value || ready.value)

const clearTimer = () => {
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
}

/** 上传创建任务时暂存的 spec / 诊断文档（job 成功后执行） */
const uploadPendingFiles = async () => {
  const jobId = String(props.jobId || '').trim()
  if (!jobId) return

  const pendingSpec = provisioningStore.consumePendingTaskSpec(jobId)
  if (pendingSpec) {
    const formData = new FormData()
    formData.append('file', pendingSpec.file)
    try {
      await api.post(
        `/workspaces/${pendingSpec.workspaceId}/tasks/${pendingSpec.taskId}/upload-spec`,
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      )
    } catch (err) {
      ElMessage.warning(formatApiError(err, t('provisioning.spec_upload_failed'), t))
    }
  }

  const pendingDocs = provisioningStore.consumePendingTaskDocs(jobId)
  if (pendingDocs && pendingDocs.files.length > 0) {
    for (const file of pendingDocs.files) {
      const formData = new FormData()
      formData.append('file', file)
      try {
        await api.post(
          `/workspaces/${pendingDocs.workspaceId}/tasks/${pendingDocs.taskId}/upload-diagnosis-doc`,
          formData,
          { headers: { 'Content-Type': 'multipart/form-data' } },
        )
      } catch (err) {
        ElMessage.warning(formatApiError(err, t('provisioning.docs_upload_failed'), t))
      }
    }
  }
}

const fetchJob = async () => {
  const jobId = String(props.jobId || '').trim()
  if (!jobId || polling.value) return
  polling.value = true
  try {
    const res = await api.get(`/provision-jobs/${jobId}`)
    job.value = res.data as ProvisionJob
    if (job.value.status === 'SUCCESS') {
      clearTimer()
      ready.value = true
      await uploadPendingFiles()
    } else if (job.value.status === 'FAILED') {
      clearTimer()
      errorText.value = String(job.value.error_message || job.value.message || t('provisioning.failed_fallback'))
    }
  } catch (err) {
    clearTimer()
    errorText.value = formatApiError(err, t('provisioning.load_failed'), t)
  } finally {
    polling.value = false
  }
}

const handleOpenSession = () => {
  if (enteringSession.value) return
  enteringSession.value = true
  emit('openSession')
}

const handleClose = () => {
  clearTimer()
  emit('close')
}

watch(
  () => props.show,
  (visible) => {
    if (!visible) {
      clearTimer()
      return
    }
    if (!props.jobId) {
      errorText.value = t('provisioning.invalid_job_id')
      return
    }
    ready.value = false
    enteringSession.value = false
    errorText.value = ''
    job.value = null
    void fetchJob()
    timer = window.setInterval(fetchJob, 1200)
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  clearTimer()
})
</script>

<template>
  <div v-if="show" class="provision-overlay">
    <div class="provision-modal glass-panel">
      <div class="provision-header">
        <Loader2 v-if="!hasFinished" class="w-5 h-5 provision-spin text-primary" />
        <CheckCircle2 v-else-if="ready" class="w-5 h-5 provision-ok" />
        <AlertTriangle v-else class="w-5 h-5 provision-error" />
        <h3>{{ t('provisioning.task_provision_title') }}</h3>
        <button class="provision-close" type="button" :title="t('common.close')" @click="handleClose">
          <X class="w-4 h-4" />
        </button>
      </div>

      <div class="provision-body">
        <div v-if="errorText" class="provision-error-box">
          <AlertTriangle class="w-4 h-4" />
          <span>{{ errorText }}</span>
        </div>

        <template v-else>
          <div class="provision-stage-row">
            <span class="provision-stage">{{ stageText }}</span>
            <span class="provision-percent">{{ progressValue }}%</span>
          </div>
          <el-progress
            :percentage="progressValue"
            :status="ready ? 'success' : undefined"
            :stroke-width="8"
          />
          <p v-if="job?.message" class="provision-message">{{ job.message }}</p>
          <p v-else class="provision-message">{{ t('provisioning.task_provision_waiting') }}</p>
        </template>
      </div>

      <div class="provision-actions">
        <button type="button" class="provision-btn-secondary" @click="handleClose">
          {{ t('common.cancel') }}
        </button>
        <button
          v-if="ready"
          type="button"
          class="provision-btn-primary"
          :disabled="enteringSession"
          @click="handleOpenSession"
        >
          <Loader2 v-if="enteringSession" class="w-4 h-4 provision-spin" />
          <span v-else>{{ t('provisioning.task_provision_enter_session') }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.provision-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 120;
}

.provision-modal {
  width: min(480px, 92vw);
  padding: 18px 20px;
  background: #ffffff;
  border-radius: 14px;
  box-shadow: 0 20px 50px rgba(15, 23, 42, 0.25);
}

.provision-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.provision-header h3 {
  flex: 1;
  margin: 0;
  font-size: 1.05rem;
  font-weight: 700;
  color: #0f172a;
}

.provision-spin {
  animation: provision-spin 1s linear infinite;
  color: var(--color-primary-600, #0284c7);
}

.provision-ok {
  color: #16a34a;
}

.provision-error {
  color: #dc2626;
}

.provision-close {
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

.provision-close:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.provision-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.provision-stage-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.85rem;
}

.provision-stage {
  font-weight: 600;
  color: #334155;
}

.provision-percent {
  font-weight: 700;
  color: var(--color-primary-600, #0284c7);
  font-variant-numeric: tabular-nums;
}

.provision-message {
  margin: 0;
  font-size: 0.78rem;
  color: #64748b;
  line-height: 1.5;
}

.provision-error-box {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 10px 12px;
  border: 1px solid #fecaca;
  border-radius: 8px;
  background: #fef2f2;
  color: #b91c1c;
  font-size: 0.82rem;
  line-height: 1.5;
}

.provision-error-box svg {
  flex-shrink: 0;
  margin-top: 1px;
}

.provision-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid #f1f5f9;
}

.provision-btn-secondary {
  border: 1px solid #e2e8f0;
  background: #ffffff;
  color: #475569;
  padding: 7px 16px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 0.82rem;
  cursor: pointer;
}

.provision-btn-secondary:hover {
  background: #f8fafc;
  border-color: #cbd5e1;
}

.provision-btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: var(--color-primary-600, #0284c7);
  color: #ffffff;
  padding: 7px 18px;
  border-radius: 8px;
  font-weight: 650;
  font-size: 0.82rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.provision-btn-primary:hover:not(:disabled) {
  background: var(--color-primary-700, #0369a1);
  transform: translateY(-1px);
}

.provision-btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

@keyframes provision-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
