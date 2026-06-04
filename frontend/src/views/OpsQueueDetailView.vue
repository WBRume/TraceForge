<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { ExternalLink, Loader2, ServerCog } from 'lucide-vue-next'
import AppSidebar from '@/components/AppSidebar.vue'
import { formatApiError } from '@/utils/error'
import { useProvisioningStore } from '@/stores/provisioning'
import { useWorkspaceStore } from '@/stores/workspace'
import {
  fetchQueueJob,
  openQueueJobTarget,
  runQueueJobAction,
} from '@/composables/queue/queueJobOperations'
import {
  queueJobDescription,
  queueJobTypeLabel,
  queueOpenActionLabel,
  queueScopeLabel,
  queueSourceLabel,
  queueStageLabel,
  queueStatusLabel,
  shortQueueId,
} from '@/composables/queue/queueJobPresentation'
import type { QueueJobItem, QueueSource } from '@/types/queue'

const route = useRoute()
const router = useRouter()
const provisioningStore = useProvisioningStore()
const workspaceStore = useWorkspaceStore()
const { locale, t } = useI18n()

const job = ref<QueueJobItem | null>(null)
const loading = ref(true)
const loadingAction = ref('')
const errorMessage = ref('')
const fetching = ref(false)
let timer: number | null = null

const source = computed(() => String(route.params.source || '').trim() as QueueSource)
const jobId = computed(() => String(route.params.jobId || '').trim())

const isSupportedSource = computed(() => ['provision', 'api_mock', 'bootstrap', 'skill_analysis'].includes(source.value))

const workspaceNameMap = computed<Record<string, string>>(() => {
  const pairs = workspaceStore.workspaces.map((ws) => [String(ws.id || ''), String(ws.name || ws.id || '')] as const)
  return Object.fromEntries(pairs.filter((pair) => pair[0]))
})

const formatQueueDate = (value?: string | null) => {
  if (!value) return '-'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return '-'
  return dt.toLocaleString(locale.value)
}

const stopPolling = () => {
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
}

const startPolling = () => {
  stopPolling()
  timer = window.setInterval(() => {
    void loadJob({ silent: true })
  }, 1500)
}

const loadJob = async ({ silent = false }: { silent?: boolean } = {}) => {
  if (fetching.value || !isSupportedSource.value || !jobId.value) return
  fetching.value = true
  if (!silent) loading.value = true
  errorMessage.value = ''
  try {
    job.value = await fetchQueueJob(source.value, jobId.value)
  } catch (err) {
    job.value = null
    errorMessage.value = formatApiError(err, t('queue_ops.detail_load_failed'), t)
  } finally {
    loading.value = false
    fetching.value = false
  }
}

const goList = () => {
  router.push('/ops/queue')
}

const sidebarNavItems = computed(() => [
  {
    key: 'queue-ops-detail',
    label: t('queue_ops.detail_title'),
    icon: ServerCog,
    active: true,
    noClick: true,
  },
])

const runAction = async (action: 'stop' | 'retry') => {
  if (!job.value) return
  const actionKey = `${job.value.source}:${job.value.job_id}:${action}`
  loadingAction.value = actionKey
  try {
    const res = await runQueueJobAction(job.value.source, job.value.job_id, action)
    const message = String(res.message || '').trim()
    if (message) {
      ElMessage.success(message)
    }
    const newJobId = String(res.new_job_id || '').trim()
    if (action === 'retry' && newJobId) {
      await router.replace(`/ops/queue/${job.value.source}/${newJobId}`)
      await loadJob()
      return
    }
    await loadJob()
  } catch (err) {
    ElMessage.error(formatApiError(err, t('workspaces.queue.action_failed'), t))
  } finally {
    loadingAction.value = ''
  }
}

const openTarget = async () => {
  if (!job.value) return
  const actionKey = `${job.value.source}:${job.value.job_id}:open`
  loadingAction.value = actionKey
  try {
    const result = await openQueueJobTarget(job.value, {
      router,
      provisioningStore,
      t,
    })
    if (result.warningMessage) {
      ElMessage.warning(result.warningMessage)
    }
  } finally {
    loadingAction.value = ''
  }
}

const isActionLoading = (action: 'stop' | 'retry' | 'open') => {
  if (!job.value) return false
  return loadingAction.value === `${job.value.source}:${job.value.job_id}:${action}`
}

onMounted(async () => {
  await workspaceStore.fetchWorkspaces()
  if (!isSupportedSource.value) {
    errorMessage.value = t('queue_ops.invalid_source')
    loading.value = false
    return
  }
  await loadJob()
  startPolling()
})

onBeforeUnmount(() => {
  stopPolling()
})

watch(
  () => [route.params.source, route.params.jobId],
  async () => {
    if (!isSupportedSource.value) {
      errorMessage.value = t('queue_ops.invalid_source')
      job.value = null
      loading.value = false
      return
    }
    await loadJob()
  },
)
</script>

<template>
  <div class="queue-detail-page">
    <AppSidebar
      :title="t('queue_ops.detail_title')"
      :back-title="t('queue_ops.back_list')"
      :nav-items="sidebarNavItems"
      @back="goList"
    />

    <main class="queue-detail-main">
      <div class="detail-wrap">
        <header class="detail-header" v-if="job">
          <div class="header-left">
            <h1>{{ queueJobTypeLabel(job, t) }} - {{ shortQueueId(job.job_id) }}</h1>
          </div>

        <div class="header-actions" v-if="job">
          <button
            v-if="job.actions?.can_stop"
            type="button"
            class="btn-action btn-danger"
            :disabled="isActionLoading('stop')"
            @click="runAction('stop')"
          >
            {{ $t('workspaces.queue.actions.stop') }}
          </button>
          <button
            v-if="job.actions?.can_retry"
            type="button"
            class="btn-action btn-warning"
            :disabled="isActionLoading('retry')"
            @click="runAction('retry')"
          >
            {{ $t('workspaces.queue.actions.retry') }}
          </button>
          <button
            v-if="job.actions?.can_open"
            type="button"
            class="btn-action btn-primary"
            :disabled="isActionLoading('open')"
            @click="openTarget"
          >
            <ExternalLink class="w-4 h-4" />
            <span>{{ queueOpenActionLabel(job, t) }}</span>
          </button>
        </div>
      </header>

      <div v-if="loading" class="state-panel glass-panel">
        <Loader2 class="spin w-6 h-6 text-primary" />
        <span>{{ $t('workspaces.queue.loading') }}</span>
      </div>

      <div v-else-if="errorMessage" class="state-panel error-panel glass-panel">
        <p>{{ errorMessage }}</p>
      </div>

      <div v-else-if="job" class="content-grid">
        <!-- Main Content -->
        <div class="main-column">
          <!-- Hero Progress Card -->
          <section class="hero-card glass-panel">
            <div class="hero-top">
              <span class="queue-status-hero" :class="`status-${String(job.status || '').toLowerCase()}`">
                {{ queueStatusLabel(job.status, t) }}
              </span>
              <span class="hero-stage">{{ queueStageLabel(job, t) }}</span>
            </div>

            <div class="hero-progress">
              <div class="progress-bar-wrap">
                <div class="progress-fill" :style="{ width: `${Math.max(0, Math.min(100, Number(job.progress || 0)))}%` }"></div>
              </div>
              <div class="progress-text">{{ Math.max(0, Math.min(100, Number(job.progress || 0))) }}%</div>
            </div>

            <div v-if="job.error_message || job.message" class="hero-message" :class="{ 'is-error': !!job.error_message }">
              <p>{{ job.error_message || job.message }}</p>
            </div>
          </section>

          <!-- Business Context Card -->
          <section class="context-card glass-panel">
            <div class="context-header">
              <h2>{{ $t('queue_ops.business_desc') }}</h2>
            </div>
            <div class="context-desc">
              <p class="business-text">{{ queueJobDescription(job, t) }}</p>
            </div>

            <div class="context-meta-grid">
              <div class="meta-item">
                <span class="meta-label">{{ $t('workspaces.queue.columns.source') }}</span>
                <span class="meta-value badge-source">{{ queueSourceLabel(job.source, t) }}</span>
              </div>
              <div class="meta-item">
                <span class="meta-label">{{ $t('workspaces.queue.columns.business') }}</span>
                <span class="meta-value text-bold">{{ queueJobTypeLabel(job, t) }}</span>
              </div>
              <div class="meta-item">
                <span class="meta-label">{{ $t('workspaces.queue.columns.scope') }}</span>
                <span class="meta-value">{{ queueScopeLabel(job, t, workspaceNameMap) }}</span>
              </div>
              <div class="meta-item">
                <span class="meta-label">{{ $t('workspaces.queue.columns.updated_at') }}</span>
                <span class="meta-value text-muted">{{ formatQueueDate(job.updated_at || job.created_at) }}</span>
              </div>
            </div>
          </section>
        </div>

        <!-- Tech Trace Column -->
        <div class="tech-column">
          <section class="trace-card glass-panel">
            <h3>{{ $t('queue_ops.debug_ids') }}</h3>
            <div class="terminal-block">
              <div class="term-line">
                <span class="term-prompt">❯</span>
                <span class="term-key">JOB_ID</span>
                <span class="term-val">{{ job.job_id }}</span>
              </div>
              <div class="term-line">
                <span class="term-prompt">❯</span>
                <span class="term-key">WORKSPACE_ID</span>
                <span class="term-val">{{ job.workspace_id || '-' }}</span>
              </div>
              <div class="term-line">
                <span class="term-prompt">❯</span>
                <span class="term-key">TASK_ID</span>
                <span class="term-val">{{ job.task_id || '-' }}</span>
              </div>
            </div>
          </section>
        </div>
      </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Open+Sans:wght@300;400;500;600;700&family=Poppins:wght@400;500;600;700&display=swap');

.queue-detail-page {
  display: flex;
  height: 100vh;
  background-color: var(--color-bg-base);
  font-family: 'Open Sans', sans-serif;
  color: #1e3a8a;
  overflow: hidden;
}

.queue-detail-main {
  flex-grow: 1;
  overflow-y: auto;
  padding: 2rem 1.5rem;
}

.detail-wrap {
  max-width: 1100px;
  margin: 0 auto;
}

/* Glass Panel Base */
.glass-panel {
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.7);
  border-radius: 1.5rem;
  box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05), 0 8px 10px -6px rgba(0, 0, 0, 0.01);
}

/* Header Area */
.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 2rem;
  flex-wrap: wrap;
  gap: 1rem;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.detail-header h1 {
  margin: 0;
  font-size: 1.5rem;
  font-family: 'Poppins', sans-serif;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.5px;
}



/* Action Buttons */
.header-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.btn-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  border: none;
  border-radius: 8px;
  padding: 0.6rem 1.2rem;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}

.btn-action:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 8px 15px -3px rgba(0, 0, 0, 0.1);
}

.btn-action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.btn-primary {
  background-color: #0ea5e9;
  color: white;
}
.btn-primary:hover:not(:disabled) {
  background-color: #0284c7;
  box-shadow: 0 8px 15px -3px rgba(14, 165, 233, 0.3);
}

.btn-warning {
  background-color: #f59e0b;
  color: white;
}
.btn-warning:hover:not(:disabled) {
  background-color: #d97706;
  box-shadow: 0 8px 15px -3px rgba(245, 158, 11, 0.3);
}

.btn-danger {
  background-color: #ef4444;
  color: white;
}
.btn-danger:hover:not(:disabled) {
  background-color: #dc2626;
  box-shadow: 0 8px 15px -3px rgba(239, 68, 68, 0.3);
}

/* States */
.state-panel {
  padding: 4rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  color: #475569;
  font-size: 1.1rem;
  font-weight: 500;
}

.error-panel p {
  color: #b91c1c;
}

/* Layout Grid */
.content-grid {
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: 1.5rem;
  align-items: start;
}

@media (max-width: 900px) {
  .content-grid {
    grid-template-columns: 1fr;
  }
}

/* Hero Progress Card */
.hero-card {
  padding: 2rem;
  margin-bottom: 1.5rem;
}

.hero-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 2rem;
}

.queue-status-hero {
  display: inline-flex;
  align-items: center;
  border-radius: 9999px;
  padding: 0.4rem 1rem;
  font-family: 'Poppins', sans-serif;
  font-weight: 600;
  font-size: 1rem;
  letter-spacing: 0.02em;
}

.status-pending { background: #fef9c3; color: #854d0e; border: 1px solid #fef08a; }
.status-running { background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; }
.status-success { background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; }
.status-failed { background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }

.hero-stage {
  font-family: 'Poppins', sans-serif;
  font-weight: 600;
  font-size: 1.25rem;
  color: #0f172a;
}

.hero-progress {
  display: flex;
  align-items: center;
  gap: 1.5rem;
}

.progress-bar-wrap {
  flex: 1;
  height: 16px;
  border-radius: 9999px;
  background: #e2e8f0;
  overflow: hidden;
  box-shadow: inset 0 2px 4px rgba(0,0,0,0.05);
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #0ea5e9 0%, #3b82f6 100%);
  border-radius: 9999px;
  transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

.progress-text {
  font-family: 'Poppins', sans-serif;
  font-weight: 700;
  font-size: 2rem;
  background: linear-gradient(135deg, #0ea5e9 0%, #3b82f6 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  min-width: 80px;
  text-align: right;
}

.hero-message {
  margin-top: 1.5rem;
  padding: 1rem 1.25rem;
  border-radius: 12px;
  background: #f8fafc;
  border-left: 4px solid #94a3b8;
  color: #334155;
  font-size: 0.95rem;
  line-height: 1.5;
}

.hero-message.is-error {
  background: #fef2f2;
  border-left-color: #ef4444;
  color: #991b1b;
}

/* Business Context Card */
.context-card {
  padding: 2rem;
}

.context-header h2 {
  font-family: 'Poppins', sans-serif;
  font-size: 1.25rem;
  font-weight: 600;
  color: #0f172a;
  margin: 0 0 1rem 0;
}

.business-text {
  font-size: 1.05rem;
  color: #475569;
  line-height: 1.6;
  margin-bottom: 2rem;
}

.context-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1.5rem;
}

@media (max-width: 600px) {
  .context-meta-grid {
    grid-template-columns: 1fr;
  }
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.meta-label {
  font-size: 0.8125rem;
  color: #64748b;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.meta-value {
  font-size: 0.95rem;
  color: #0f172a;
}

.badge-source {
  display: inline-block;
  padding: 0.2rem 0.6rem;
  background: #f1f5f9;
  color: #334155;
  border-radius: 6px;
  font-weight: 600;
  font-size: 0.85rem;
  width: fit-content;
}

.text-bold { font-weight: 600; }
.text-muted { color: #64748b; }

/* Technical Trace Card */
.trace-card {
  padding: 1.5rem;
  background: #0f172a;
  border-color: #1e293b;
  color: #f8fafc;
}

.trace-card h3 {
  font-family: 'Poppins', sans-serif;
  font-size: 1.1rem;
  font-weight: 600;
  color: #e2e8f0;
  margin: 0 0 1rem 0;
}

.terminal-block {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  font-family: 'Fira Code', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.85rem;
}

.term-line {
  display: flex;
  gap: 0.75rem;
  line-height: 1.4;
}

.term-prompt {
  color: #10b981;
  user-select: none;
}

.term-key {
  color: #38bdf8;
  font-weight: 500;
  min-width: 100px;
}

.term-val {
  color: #cbd5e1;
  word-break: break-all;
}

/* Utils */
.spin { animation: spin 1s linear infinite; }
@keyframes spin { 100% { transform: rotate(360deg); } }
</style>
