<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Loader2, AlertTriangle, CheckCircle2 } from 'lucide-vue-next'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import { useWorkspaceStore } from '@/stores/workspace'
import { useProvisioningStore } from '@/stores/provisioning'

type ProvisionJobType = 'CREATE_WORKSPACE' | 'CREATE_TASK'
type ProvisionJobStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED'

type ProvisionJob = {
  job_id: string
  job_type: ProvisionJobType
  status: ProvisionJobStatus
  progress: number
  stage: string
  message?: string | null
  error_message?: string | null
  workspace_id?: string | null
  task_id?: string | null
}

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const wsStore = useWorkspaceStore()
const provisioningStore = useProvisioningStore()

const job = ref<ProvisionJob | null>(null)
const loading = ref(true)
const redirecting = ref(false)
const errorText = ref('')
const polling = ref(false)
let timer: number | null = null

const jobId = computed(() => String(route.params.jobId || '').trim())
const expectSpecUpload = computed(() => String(route.query.expectSpec || '') === '1')
const stageText = computed(() => {
  const stage = String(job.value?.stage || '').toUpperCase()
  const map: Record<string, string> = {
    QUEUED: t('provisioning.stage_queued'),
    VALIDATING_INPUT: t('provisioning.stage_validating'),
    WAITING_REPO_LOCK: t('provisioning.stage_waiting_lock'),
    WAITING_TASK_QUEUE: t('provisioning.stage_waiting_queue'),
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
const isFailed = computed(() => job.value?.status === 'FAILED')
const isSuccess = computed(() => job.value?.status === 'SUCCESS')
const hasFinished = computed(() => isFailed.value || isSuccess.value)

const clearTimer = () => {
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
}

const uploadPendingTaskSpecIfNeeded = async (currentJob: ProvisionJob) => {
  if (currentJob.job_type !== 'CREATE_TASK') return
  const currentJobId = String(currentJob.job_id || '').trim()
  const pending = provisioningStore.consumePendingTaskSpec(currentJobId)
  if (!pending) {
    if (expectSpecUpload.value) {
      ElMessage.warning(t('provisioning.spec_lost_warning'))
    }
    return
  }

  const formData = new FormData()
  formData.append('file', pending.file)
  try {
    await api.post(
      `/workspaces/${pending.workspaceId}/tasks/${pending.taskId}/upload-spec`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    )
  } catch (err) {
    ElMessage.warning(formatApiError(err, t('provisioning.spec_upload_failed'), t))
  }
}

const uploadPendingTaskDocsIfNeeded = async (currentJob: ProvisionJob) => {
  if (currentJob.job_type !== 'CREATE_TASK') return
  const currentJobId = String(currentJob.job_id || '').trim()
  const pending = provisioningStore.consumePendingTaskDocs(currentJobId)
  if (!pending || pending.files.length === 0) return

  for (const file of pending.files) {
    const formData = new FormData()
    formData.append('file', file)
    try {
      await api.post(
        `/workspaces/${pending.workspaceId}/tasks/${pending.taskId}/upload-diagnosis-doc`,
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      )
    } catch (err) {
      ElMessage.warning(formatApiError(err, t('provisioning.docs_upload_failed'), t))
    }
  }
}

const navigateOnSuccess = async (currentJob: ProvisionJob) => {
  if (redirecting.value) return
  redirecting.value = true
  clearTimer()

  if (currentJob.job_type === 'CREATE_WORKSPACE') {
    const workspaceId = String(currentJob.workspace_id || '').trim()
    if (!workspaceId) {
      router.replace('/workspaces')
      return
    }
    try {
      const workspaceRes = await api.get(`/workspaces/${workspaceId}`)
      wsStore.setCurrent(workspaceRes.data)
    } catch {
      // Keep redirecting even if current workspace refresh fails.
    }
    router.replace(`/ws/${workspaceId}/dashboard`)
    return
  }

  if (currentJob.job_type === 'CREATE_TASK') {
    await uploadPendingTaskSpecIfNeeded(currentJob)
    await uploadPendingTaskDocsIfNeeded(currentJob)
    const workspaceId = String(currentJob.workspace_id || '').trim()
    const taskId = String(currentJob.task_id || '').trim()
    if (workspaceId && taskId) {
      router.replace(`/ws/${workspaceId}/chat/${taskId}`)
      return
    }
  }

  router.replace('/workspaces')
}

const fetchJob = async () => {
  if (!jobId.value || polling.value) return
  polling.value = true
  try {
    const res = await api.get(`/provision-jobs/${jobId.value}`)
    job.value = res.data as ProvisionJob
    errorText.value = ''
    if (job.value.status === 'SUCCESS') {
      await navigateOnSuccess(job.value)
    } else if (job.value.status === 'FAILED') {
      clearTimer()
      errorText.value = String(job.value.error_message || job.value.message || t('provisioning.failed_fallback'))
    }
  } catch (err) {
    clearTimer()
    errorText.value = formatApiError(err, t('provisioning.load_failed'), t)
  } finally {
    loading.value = false
    polling.value = false
  }
}

const goBack = () => {
  const fallbackWorkspace = String(job.value?.workspace_id || '').trim()
  if (fallbackWorkspace) {
    router.replace(`/ws/${fallbackWorkspace}/dashboard`)
    return
  }
  router.replace('/workspaces')
}

onMounted(async () => {
  if (!jobId.value) {
    errorText.value = t('provisioning.invalid_job_id')
    loading.value = false
    return
  }
  await fetchJob()
  if (!hasFinished.value) {
    timer = window.setInterval(fetchJob, 1200)
  }
})

onBeforeUnmount(() => {
  clearTimer()
})
</script>

<template>
  <div class="provision-page">
    <section class="provision-card glass-panel">
      <header class="card-header">
        <Loader2 v-if="!hasFinished" class="spin h-5 w-5 text-primary" />
        <CheckCircle2 v-else-if="isSuccess" class="h-5 w-5 text-success" />
        <AlertTriangle v-else class="h-5 w-5 text-danger" />
        <h1>{{ $t('provisioning.title') }}</h1>
      </header>

      <p class="subtitle" v-if="loading">{{ $t('provisioning.loading') }}</p>
      <p class="subtitle" v-else-if="errorText">{{ errorText }}</p>
      <p class="subtitle" v-else>
        {{ job?.message || $t('provisioning.running') }}
      </p>

      <div class="stage-block" v-if="job && !errorText">
        <div class="stage-row">
          <span>{{ $t('provisioning.stage_label') }}</span>
          <strong>{{ stageText }}</strong>
        </div>
        <div class="progress-track">
          <div class="progress-value" :style="{ width: `${progressValue}%` }"></div>
        </div>
        <div class="progress-text">{{ progressValue }}%</div>
      </div>

      <div class="actions" v-if="errorText || isFailed">
        <button class="btn-secondary" type="button" @click="goBack">{{ $t('provisioning.back') }}</button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.provision-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: radial-gradient(circle at top, #e0f2fe 0%, #eef2ff 48%, #f8fafc 100%);
}

.provision-card {
  width: min(560px, 100%);
  padding: 28px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(148, 163, 184, 0.25);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.card-header h1 {
  margin: 0;
  font-size: 1.25rem;
  color: #0f172a;
}

.subtitle {
  margin: 12px 0 0;
  color: #475569;
  line-height: 1.5;
}

.stage-block {
  margin-top: 18px;
}

.stage-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.875rem;
  color: #475569;
}

.stage-row strong {
  color: #0f172a;
}

.progress-track {
  margin-top: 10px;
  height: 8px;
  border-radius: 999px;
  background: #e2e8f0;
  overflow: hidden;
}

.progress-value {
  height: 100%;
  background: linear-gradient(90deg, #0ea5e9, #2563eb);
  transition: width 0.35s ease;
}

.progress-text {
  margin-top: 8px;
  text-align: right;
  font-size: 0.8rem;
  color: #64748b;
}

.actions {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}

.btn-secondary {
  border: 1px solid #cbd5e1;
  background: #fff;
  color: #334155;
  border-radius: 10px;
  padding: 8px 14px;
}

.spin {
  animation: spin 1s linear infinite;
}

.text-primary { color: #0ea5e9; }
.text-success { color: #16a34a; }
.text-danger { color: #dc2626; }
.h-5 { width: 1.25rem; height: 1.25rem; }
.w-5 { width: 1.25rem; height: 1.25rem; }

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
