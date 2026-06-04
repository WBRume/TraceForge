<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { CircleHelp } from 'lucide-vue-next'
import { formatApiError } from '@/utils/error'
import { useProvisioningStore } from '@/stores/provisioning'
import BaseSelect from '@/components/BaseSelect.vue'
import {
  fetchQueueJobs,
  openQueueJobTarget,
  type QueueListParams,
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
} from '@/composables/queue/queueJobPresentation'
import type {
  QueueJobItem,
  QueueSource,
  QueueStatus,
  QueueView,
} from '@/types/queue'

type WorkspaceOption = {
  id?: string
  name?: string
}

const props = defineProps<{
  workspaces: WorkspaceOption[]
}>()

const { locale, t } = useI18n()
const route = useRoute()
const router = useRouter()
const provisioningStore = useProvisioningStore()

const queueItems = ref<QueueJobItem[]>([])
const queueTotal = ref(0)
const queuePage = ref(1)
const queuePageSize = ref(10)
const queueLoading = ref(false)
const queueError = ref('')
const queueView = ref<QueueView>('mine')
const queueSource = ref<'all' | QueueSource>('all')
const queueStatus = ref<'all' | QueueStatus>('all')
const queueWorkspaceId = ref('')
const queueActioningKey = ref('')
const queueRequestInFlight = ref(false)
const syncingWorkspaceFromRoute = ref(false)
let queuePollTimer: number | null = null

const queueTotalPages = computed(() => {
  const total = Math.max(0, Number(queueTotal.value || 0))
  return Math.max(1, Math.ceil(total / queuePageSize.value))
})

const focusedJobId = computed(() => String(route.query.focus || '').trim())

const queueSourceOptions = computed(() => [
  { value: 'all', label: t('workspaces.queue.source_all') },
  { value: 'provision', label: t('workspaces.queue.source_provision') },
  { value: 'api_mock', label: t('workspaces.queue.source_api_mock') },
  { value: 'bootstrap', label: t('workspaces.queue.source_bootstrap') },
  { value: 'skill_analysis', label: t('workspaces.queue.source_skill_analysis') },
])

const queueStatusOptions = computed(() => [
  { value: 'all', label: t('workspaces.queue.status_all') },
  { value: 'PENDING', label: t('workspaces.queue.status.pending') },
  { value: 'RUNNING', label: t('workspaces.queue.status.running') },
  { value: 'SUCCESS', label: t('workspaces.queue.status.success') },
  { value: 'FAILED', label: t('workspaces.queue.status.failed') },
])

const queueViewOptions = computed(() => [
  { value: 'mine', label: t('workspaces.queue.view_mine') },
  { value: 'workspace_all', label: t('workspaces.queue.view_workspace_all') },
])

const workspaceFilterOptions = computed(() => [
  { value: '', label: t('workspaces.queue.workspace_all') },
  ...props.workspaces.map((ws) => ({
    value: String(ws.id || ''),
    label: String(ws.name || ws.id || ''),
  })),
])
const workspaceNameMap = computed<Record<string, string>>(() => {
  const pairs = props.workspaces.map((ws) => [String(ws.id || ''), String(ws.name || ws.id || '')] as const)
  return Object.fromEntries(pairs.filter((pair) => pair[0]))
})

const formatQueueDate = (value?: string | null) => {
  if (!value) return '-'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return '-'
  return dt.toLocaleString(locale.value)
}

const queueScopeTip = (item: QueueJobItem) => {
  const jobId = String(item.job_id || '-')
  const workspaceId = String(item.workspace_id || '-')
  const taskId = String(item.task_id || '-')
  return `${t('queue_ops.debug_job')}: ${jobId} | ${t('queue_ops.debug_workspace')}: ${workspaceId} | ${t('queue_ops.debug_task')}: ${taskId}`
}

const updateQueueRouteQuery = async (patch: Record<string, string | undefined>) => {
  const nextQuery: Record<string, any> = { ...route.query }
  Object.entries(patch).forEach(([key, value]) => {
    if (value === undefined || value === '') {
      delete nextQuery[key]
      return
    }
    nextQuery[key] = value
  })
  await router.replace({ path: '/ops/queue', query: nextQuery })
}

const stopQueuePolling = () => {
  if (queuePollTimer !== null) {
    window.clearInterval(queuePollTimer)
    queuePollTimer = null
  }
}

const startQueuePolling = () => {
  stopQueuePolling()
  queuePollTimer = window.setInterval(() => {
    void loadQueueJobs({ silent: true })
  }, 1500)
}

const loadQueueJobs = async ({ silent = false }: { silent?: boolean } = {}) => {
  if (queueRequestInFlight.value) return
  queueRequestInFlight.value = true
  if (!silent) {
    queueLoading.value = true
  }
  queueError.value = ''
  try {
    const params: QueueListParams = {
      view: queueView.value,
      page: queuePage.value,
      page_size: queuePageSize.value,
    }
    if (queueSource.value !== 'all') params.source = queueSource.value
    if (queueStatus.value !== 'all') params.status = queueStatus.value
    if (queueWorkspaceId.value) params.workspace_id = queueWorkspaceId.value
    const data = await fetchQueueJobs(params)
    queueItems.value = Array.isArray(data?.items) ? data.items : []
    queueTotal.value = Number(data?.total || 0)
  } catch (err) {
    queueError.value = formatApiError(err, t('workspaces.queue.load_failed'), t)
  } finally {
    queueLoading.value = false
    queueRequestInFlight.value = false
  }
}

const onQueueFilterChanged = () => {
  queuePage.value = 1
  void loadQueueJobs()
}

const refreshQueueJobs = async () => {
  await loadQueueJobs()
}

const goQueuePage = (nextPage: number) => {
  const safePage = Math.max(1, Math.min(nextPage, queueTotalPages.value))
  if (safePage === queuePage.value) return
  queuePage.value = safePage
  void loadQueueJobs()
}

const isQueueActioning = (item: QueueJobItem, action: 'stop' | 'retry' | 'open') =>
  queueActioningKey.value === `${item.source}:${item.job_id}:${action}`

const openQueueJobDetail = (item: QueueJobItem) => {
  router.push(`/ops/queue/${item.source}/${item.job_id}`)
}

const runQueueAction = async (item: QueueJobItem, action: 'stop' | 'retry') => {
  const actionKey = `${item.source}:${item.job_id}:${action}`
  queueActioningKey.value = actionKey
  try {
    const res = await runQueueJobAction(item.source, item.job_id, action)
    const message = String(res?.message || '').trim()
    if (message) {
      ElMessage.success(message)
    }
    const newJobId = String(res?.new_job_id || '').trim()
    if (action === 'retry' && newJobId) {
      await router.push(`/ops/queue/${item.source}/${newJobId}`)
    }
    await loadQueueJobs()
  } catch (err) {
    ElMessage.error(formatApiError(err, t('workspaces.queue.action_failed'), t))
  } finally {
    queueActioningKey.value = ''
  }
}

const openQueueTarget = async (item: QueueJobItem) => {
  const targetPath = String(item.target_path || '').trim()
  if (!targetPath) return

  const actionKey = `${item.source}:${item.job_id}:open`
  queueActioningKey.value = actionKey
  try {
    const result = await openQueueJobTarget(item, {
      router,
      provisioningStore,
      t,
    })
    if (result.warningMessage) {
      ElMessage.warning(result.warningMessage)
    }
  } finally {
    queueActioningKey.value = ''
  }
}

onMounted(async () => {
  queueWorkspaceId.value = String(route.query.workspace_id || '').trim()
  await loadQueueJobs()
  startQueuePolling()
})

onBeforeUnmount(() => {
  stopQueuePolling()
})

watch(
  () => route.query.workspace_id,
  (value) => {
    const nextValue = String(value || '').trim()
    if (nextValue === queueWorkspaceId.value) return
    syncingWorkspaceFromRoute.value = true
    queueWorkspaceId.value = nextValue
  },
)

watch([queueView, queueSource, queueStatus], () => {
  onQueueFilterChanged()
})

watch(
  queueWorkspaceId,
  async (nextValue, prevValue) => {
    if (nextValue === prevValue) return
    if (syncingWorkspaceFromRoute.value) {
      syncingWorkspaceFromRoute.value = false
      queuePage.value = 1
      await loadQueueJobs()
      return
    }
    queuePage.value = 1
    await updateQueueRouteQuery({ workspace_id: queueWorkspaceId.value || undefined })
    await loadQueueJobs()
  },
)
</script>

<template>
  <div class="queue-panel glass-panel">
    <div class="queue-toolbar">
      <div class="queue-filters">
        <label class="queue-filter-item">
          <span>{{ $t('workspaces.queue.filter_view') }}</span>
          <BaseSelect v-model="queueView" :options="queueViewOptions" size="sm" />
        </label>

        <label class="queue-filter-item">
          <span>{{ $t('workspaces.queue.filter_workspace') }}</span>
          <BaseSelect v-model="queueWorkspaceId" :options="workspaceFilterOptions" size="sm" />
        </label>

        <label class="queue-filter-item">
          <span>{{ $t('workspaces.queue.filter_source') }}</span>
          <BaseSelect v-model="queueSource" :options="queueSourceOptions" size="sm" />
        </label>

        <label class="queue-filter-item">
          <span>{{ $t('workspaces.queue.filter_status') }}</span>
          <BaseSelect v-model="queueStatus" :options="queueStatusOptions" size="sm" />
        </label>
      </div>
      <button type="button" class="btn-secondary" :disabled="queueLoading" @click="refreshQueueJobs">
        {{ $t('workspaces.queue.refresh') }}
      </button>
    </div>

    <p v-if="queueError" class="create-error">{{ queueError }}</p>

    <div v-if="queueLoading" class="loading-state">{{ $t('workspaces.queue.loading') }}</div>
    <div v-else-if="queueItems.length === 0" class="empty-state queue-empty">
      <h3>{{ $t('workspaces.queue.empty') }}</h3>
      <p>{{ $t('workspaces.queue.empty_hint') }}</p>
    </div>

    <div v-else class="queue-table-wrap">
      <table class="queue-table">
        <thead>
          <tr>
            <th>{{ $t('workspaces.queue.columns.source') }}</th>
            <th>{{ $t('workspaces.queue.columns.business') }}</th>
            <th>{{ $t('workspaces.queue.columns.status') }}</th>
            <th>{{ $t('workspaces.queue.columns.progress') }}</th>
            <th>{{ $t('workspaces.queue.columns.scope') }}</th>
            <th>{{ $t('workspaces.queue.columns.updated_at') }}</th>
            <th>{{ $t('workspaces.queue.columns.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in queueItems"
            :key="`${item.source}:${item.job_id}`"
            :class="{ focused: focusedJobId && focusedJobId === item.job_id }"
          >
            <td>
              <div class="queue-cell-main">
                <span class="queue-cell-primary">{{ queueSourceLabel(item.source, t) }}</span>
                <el-tooltip :content="queueStageLabel(item, t)" placement="top">
                  <CircleHelp class="queue-tip-icon" />
                </el-tooltip>
              </div>
            </td>
            <td>
              <div class="queue-cell-main">
                <span class="queue-cell-primary">{{ queueJobTypeLabel(item, t) }}</span>
                <el-tooltip :content="queueJobDescription(item, t)" placement="top">
                  <CircleHelp class="queue-tip-icon" />
                </el-tooltip>
              </div>
            </td>
            <td>
              <span class="queue-status" :class="`status-${String(item.status || '').toLowerCase()}`">
                {{ queueStatusLabel(item.status, t) }}
              </span>
            </td>
            <td>
              <div class="queue-progress">
                <div class="queue-progress-track">
                  <div class="queue-progress-fill" :style="{ width: `${Math.max(0, Math.min(100, Number(item.progress || 0)))}%` }"></div>
                </div>
                <span>{{ Math.max(0, Math.min(100, Number(item.progress || 0))) }}%</span>
              </div>
              <div class="queue-cell-secondary">{{ item.error_message || item.message || '-' }}</div>
            </td>
            <td>
              <div class="queue-cell-main">
                <span class="queue-cell-primary">
                  {{ queueScopeLabel(item, t, workspaceNameMap) }}
                </span>
                <el-tooltip :content="queueScopeTip(item)" placement="top">
                  <CircleHelp class="queue-tip-icon" />
                </el-tooltip>
              </div>
            </td>
            <td>{{ formatQueueDate(item.updated_at || item.created_at) }}</td>
            <td>
              <div class="queue-actions">
                <button
                  type="button"
                  class="btn-queue"
                  @click="openQueueJobDetail(item)"
                >
                  {{ $t('queue_ops.detail_title') }}
                </button>
                <button
                  v-if="item.actions?.can_stop"
                  type="button"
                  class="btn-queue btn-queue-danger"
                  :disabled="isQueueActioning(item, 'stop')"
                  @click="runQueueAction(item, 'stop')"
                >
                  {{ $t('workspaces.queue.actions.stop') }}
                </button>
                <button
                  v-if="item.actions?.can_retry"
                  type="button"
                  class="btn-queue btn-queue-warning"
                  :disabled="isQueueActioning(item, 'retry')"
                  @click="runQueueAction(item, 'retry')"
                >
                  {{ $t('workspaces.queue.actions.retry') }}
                </button>
                <button
                  v-if="item.actions?.can_open"
                  type="button"
                  class="btn-queue btn-queue-primary"
                  :disabled="isQueueActioning(item, 'open')"
                  @click="openQueueTarget(item)"
                >
                  {{ queueOpenActionLabel(item, t) }}
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="queue-pagination">
      <button
        v-if="queueTotalPages > 1 && queuePage > 1"
        type="button"
        class="btn-secondary mini"
        :disabled="queueLoading"
        @click="goQueuePage(queuePage - 1)"
      >
        {{ $t('workspaces.queue.prev_page') }}
      </button>
      <div class="pagination-info">
        <span class="queue-page-info">
          {{ $t('workspaces.queue.page_info', { page: queuePage, total: queueTotalPages }) }}
        </span>
        <span v-if="queueTotal > 0" class="queue-total-info">
          {{ $t('workspaces.queue.total', { total: queueTotal }) }}
        </span>
      </div>
      <button
        v-if="queueTotalPages > 1 && queuePage < queueTotalPages"
        type="button"
        class="btn-secondary mini"
        :disabled="queueLoading"
        @click="goQueuePage(queuePage + 1)"
      >
        {{ $t('workspaces.queue.next_page') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.queue-panel {
  padding: 2rem;
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 1.5rem;
  box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05), 0 8px 10px -6px rgba(0, 0, 0, 0.01);
  transition: all 0.3s ease;
}

.queue-toolbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 1.5rem;
  flex-wrap: wrap;
  margin-bottom: 1.5rem;
  padding-bottom: 1.5rem;
  border-bottom: 1px solid #f1f5f9;
}

.queue-filters {
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
}

.queue-filter-item {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  min-width: 180px;
}

.queue-filter-item span {
  color: #64748b;
  font-size: 0.8125rem;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.queue-empty {
  padding: 4rem 2rem;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  background: #f8fafc;
  border-radius: 1rem;
  border: 1px dashed #cbd5e1;
}

.empty-state h3 {
  font-family: 'Poppins', sans-serif;
  color: #0f172a;
  margin-bottom: 0.5rem;
}

.empty-state p {
  color: #64748b;
}

.queue-table-wrap {
  overflow: auto;
  border: 1px solid #e2e8f0;
  border-radius: 1rem;
  background: #ffffff;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.02);
}

.queue-table {
  width: 100%;
  border-collapse: collapse;
  min-width: 980px;
}

.queue-table th,
.queue-table td {
  border-bottom: 1px solid #f1f5f9;
  text-align: left;
  padding: 1rem 1.25rem;
  vertical-align: middle;
  font-size: 0.875rem;
}

.queue-table th {
  color: #475569;
  background: #f8fafc;
  font-weight: 600;
  font-size: 0.8125rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  position: sticky;
  top: 0;
  z-index: 1;
}

.queue-table tbody tr {
  transition: all 0.2s;
}

.queue-table tbody tr:hover {
  background: #f8fafc;
}

.queue-table tr.focused {
  background: #eff6ff;
  box-shadow: inset 2px 0 0 #3b82f6;
}

.queue-cell-primary {
  color: #0f172a;
  font-weight: 600;
  word-break: break-all;
}

.queue-cell-main {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}

.queue-cell-secondary {
  color: #64748b;
  margin-top: 0.25rem;
  word-break: break-all;
  font-size: 0.8125rem;
}

.queue-tip-icon {
  width: 1rem;
  height: 1rem;
  color: #94a3b8;
  cursor: help;
  flex-shrink: 0;
  transition: color 0.2s;
}

.queue-tip-icon:hover {
  color: #0ea5e9;
}

.queue-status {
  display: inline-flex;
  align-items: center;
  border-radius: 9999px;
  padding: 0.25rem 0.75rem;
  font-weight: 600;
  font-size: 0.75rem;
  letter-spacing: 0.02em;
  white-space: nowrap;
}

.queue-status.status-pending {
  background: #fef9c3;
  color: #854d0e;
  border: 1px solid #fef08a;
}

.queue-status.status-running {
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
}

.queue-status.status-success {
  background: #f0fdf4;
  color: #166534;
  border: 1px solid #bbf7d0;
}

.queue-status.status-failed {
  background: #fef2f2;
  color: #991b1b;
  border: 1px solid #fecaca;
}

.queue-progress {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.queue-progress-track {
  width: 120px;
  height: 8px;
  border-radius: 9999px;
  background: #e2e8f0;
  overflow: hidden;
}

.queue-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #0ea5e9 0%, #3b82f6 100%);
  transition: width 0.3s ease;
}

.queue-progress span {
  font-weight: 600;
  font-size: 0.8125rem;
  color: #334155;
}

.queue-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.btn-queue {
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #334155;
  border-radius: 6px;
  padding: 0.35rem 0.75rem;
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.btn-queue:hover:not(:disabled) {
  border-color: #94a3b8;
  background: #f8fafc;
  transform: translateY(-1px);
}

.btn-queue-primary {
  border-color: #3b82f6;
  color: #1d4ed8;
  background: #eff6ff;
}

.btn-queue-primary:hover:not(:disabled) {
  background: #dbeafe;
  border-color: #2563eb;
}

.btn-queue-danger {
  border-color: #fca5a5;
  color: #dc2626;
  background: #fef2f2;
}

.btn-queue-danger:hover:not(:disabled) {
  background: #fee2e2;
  border-color: #ef4444;
}

.btn-queue-warning {
  border-color: #fcd34d;
  color: #b45309;
  background: #fffbeb;
}

.btn-queue-warning:hover:not(:disabled) {
  background: #fef3c7;
  border-color: #f59e0b;
}

.btn-queue:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
}

.queue-pagination {
  margin-top: 1.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  padding-top: 1rem;
  border-top: 1px solid #f1f5f9;
}

.pagination-info {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.queue-page-info {
  color: #64748b;
  font-size: 0.875rem;
  font-weight: 500;
  padding: 0.4rem 1rem;
  background: rgba(241, 245, 249, 0.8);
  border-radius: var(--radius-full);
  border: 1px solid rgba(226, 232, 240, 0.5);
}

.queue-total-info {
  color: #94a3b8;
  font-size: 0.8rem;
}

.create-error {
  margin: 0;
  color: #b91c1c;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: var(--radius-md);
  padding: 10px 12px;
  font-size: 0.875rem;
}
</style>
