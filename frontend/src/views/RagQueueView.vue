<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { useWorkspaceStore } from '@/stores/workspace'
import BaseSelect from '@/components/BaseSelect.vue'
import { formatApiError } from '@/utils/error'
import {
  confirmRagQueueDownload,
  downloadRagQueueZip,
  fetchRagQueues,
  type RagQueueListParams,
} from '@/composables/rag/ragOutboxOps'
import type {
  RagQueueStatus,
  RagSyncQueueItem,
} from '@/types/rag'

const { locale, t } = useI18n()
const router = useRouter()
const wsStore = useWorkspaceStore()

const queues = ref<RagSyncQueueItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const loadError = ref('')
const selectedWorkspaceId = ref('')
const selectedStatus = ref<'all' | RagQueueStatus>('all')
const downloadingQueueId = ref('')

let pollTimer: number | null = null

const totalPages = computed(() => {
  const ttl = Math.max(0, Number(total.value || 0))
  return Math.max(1, Math.ceil(ttl / pageSize.value))
})

const statusOptions = computed(() => [
  { value: 'all', label: t('rag_queue.status_all') },
  { value: 'RUNNING', label: t('rag_queue.status_running') },
  { value: 'CONSUMED', label: t('rag_queue.status_consumed') },
])

const workspaceOptions = computed(() => [
  { value: '', label: t('rag_queue.workspace_all') },
  ...(wsStore.workspaces || []).map((ws: any) => ({
    value: String(ws.id || ''),
    label: String(ws.name || ws.id || ''),
  })),
])

const workspaceNameMap = computed<Record<string, string>>(() => {
  const map: Record<string, string> = {}
  ;(wsStore.workspaces || []).forEach((ws: any) => {
    if (ws?.id) map[String(ws.id)] = String(ws.name || ws.id)
  })
  return map
})

const queueStatusText = (status: string): string => {
  const keyMap: Record<string, string> = {
    RUNNING: 'rag_queue.status_running',
    CONSUMED: 'rag_queue.status_consumed',
  }
  return keyMap[status] ? t(keyMap[status]) : status
}

const formatDate = (value?: string | null): string => {
  if (!value) return '-'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return '-'
  return dt.toLocaleString(locale.value)
}

const loadQueues = async ({ silent = false }: { silent?: boolean } = {}) => {
  if (loading.value) return
  if (!silent) loading.value = true
  if (!silent) loadError.value = ''
  try {
    const params: RagQueueListParams = { page: page.value, page_size: pageSize.value }
    if (selectedWorkspaceId.value) params.workspace_id = selectedWorkspaceId.value
    if (selectedStatus.value !== 'all') params.status = selectedStatus.value
    const data = await fetchRagQueues(params)
    queues.value = data.items ?? []
    total.value = Number(data.total ?? 0)
  } catch (err) {
    if (!silent) {
      queues.value = []
      total.value = 0
      loadError.value = formatApiError(err, t('rag_queue.load_failed'), t)
    }
  } finally {
    if (!silent) loading.value = false
  }
}

const onFilterChanged = () => {
  page.value = 1
  void loadQueues()
}

const goQueuePage = (nextPage: number) => {
  const safePage = Math.max(1, Math.min(nextPage, totalPages.value))
  if (safePage === page.value) return
  page.value = safePage
  void loadQueues()
}

const downloadQueue = async (queue: RagSyncQueueItem) => {
  if (downloadingQueueId.value) return
  downloadingQueueId.value = queue.id
  let savedLocally = false
  try {
    const save = await downloadRagQueueZip(queue.id, queue.name)
    if (save.canceled) {
      ElMessage.info(t('rag_queue.save_canceled'))
      return
    }
    savedLocally = true
    // 文件已保存到本地后才标记状态，避免「点击下载但文件尚未保存」时状态已被修改
    await confirmRagQueueDownload(queue.id)
    ElMessage.success(
      queue.status === 'CONSUMED'
        ? t('rag_queue.download_again_success')
        : t('rag_queue.download_success'),
    )
    await loadQueues({ silent: true })
  } catch {
    ElMessage.error(
      savedLocally ? t('rag_queue.mark_queue_failed') : t('rag_queue.download_failed'),
    )
  } finally {
    downloadingQueueId.value = ''
  }
}

const goDetail = (queue: RagSyncQueueItem) => {
  router.push(`/ops/rag-queue/${encodeURIComponent(queue.id)}`)
}

onMounted(async () => {
  await wsStore.fetchWorkspaces()
  void loadQueues()
  pollTimer = window.setInterval(() => {
    void loadQueues({ silent: true })
  }, 5000)
})

onBeforeUnmount(() => {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<template>
  <div class="queue-list-page">
    <div class="mgmt-page-header">
      <div>
        <h2>{{ t('rag_queue.title') }}</h2>
        <p class="mgmt-subtitle">{{ t('rag_queue.subtitle') }}</p>
      </div>
    </div>

    <div class="queue-panel glass-panel">
      <div class="queue-toolbar">
        <div class="queue-filters">
          <label class="queue-filter-item">
            <span>{{ t('rag_queue.filter_workspace') }}</span>
            <BaseSelect
              v-model="selectedWorkspaceId"
              :options="workspaceOptions"
              size="sm"
              @update:model-value="onFilterChanged"
            />
          </label>

          <label class="queue-filter-item">
            <span>{{ t('rag_queue.filter_status') }}</span>
            <BaseSelect
              v-model="selectedStatus"
              :options="statusOptions"
              size="sm"
              @update:model-value="onFilterChanged"
            />
          </label>
        </div>
        <button type="button" class="btn-secondary" :disabled="loading" @click="loadQueues()">
          {{ t('rag_queue.refresh') }}
        </button>
      </div>

      <p v-if="loadError" class="create-error">{{ loadError }}</p>

      <div v-if="loading" class="loading-state">{{ t('rag_queue.loading') }}</div>
      <div v-else-if="queues.length === 0" class="empty-state queue-empty">
        <h3>{{ t('rag_queue.empty') }}</h3>
        <p>{{ t('rag_queue.empty_hint') }}</p>
      </div>

      <div v-else class="queue-table-wrap">
        <table class="queue-table">
          <thead>
            <tr>
              <th>{{ t('rag_queue.col_name') }}</th>
              <th>{{ t('rag_queue.col_workspace') }}</th>
              <th>{{ t('rag_queue.col_status') }}</th>
              <th>{{ t('rag_queue.col_case_count') }}</th>
              <th>{{ t('rag_queue.col_exported_count') }}</th>
              <th>{{ t('rag_queue.col_created') }}</th>
              <th>{{ t('rag_queue.col_consumed') }}</th>
              <th>{{ t('rag_queue.col_actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="queue in queues" :key="queue.id">
              <td>
                <span class="queue-cell-primary">{{ queue.name }}</span>
              </td>
              <td>
                <span class="queue-cell-secondary">
                  {{
                    queue.workspace_id
                      ? workspaceNameMap[queue.workspace_id] || queue.workspace_id
                      : t('rag_queue.workspace_unassigned')
                  }}
                </span>
              </td>
              <td>
                <span
                  class="queue-status"
                  :class="`status-${String(queue.status || '').toLowerCase()}`"
                >
                  {{ queueStatusText(queue.status) }}
                </span>
              </td>
              <td>{{ queue.case_count ?? 0 }}</td>
              <td>{{ queue.exported_count ?? 0 }}</td>
              <td>{{ formatDate(queue.created_at) }}</td>
              <td>{{ formatDate(queue.consumed_at) }}</td>
              <td>
                <div class="queue-actions">
                  <button type="button" class="btn-queue" @click="goDetail(queue)">
                    {{ t('rag_queue.detail') }}
                  </button>
                  <button
                    type="button"
                    class="btn-queue btn-queue-primary"
                    :disabled="!!downloadingQueueId"
                    @click="downloadQueue(queue)"
                  >
                    {{
                      queue.status === 'CONSUMED'
                        ? t('rag_queue.download_again')
                        : t('rag_queue.download')
                    }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="queue-pagination">
        <button
          v-if="totalPages > 1 && page > 1"
          type="button"
          class="btn-secondary mini"
          :disabled="loading"
          @click="goQueuePage(page - 1)"
        >
          {{ t('rag_queue.prev_page') }}
        </button>
        <div class="pagination-info">
          <span class="queue-page-info">
            {{ t('rag_queue.page_info', { page, total: totalPages }) }}
          </span>
          <span v-if="total > 0" class="queue-total-info">
            {{ t('rag_queue.total', { total }) }}
          </span>
        </div>
        <button
          v-if="totalPages > 1 && page < totalPages"
          type="button"
          class="btn-secondary mini"
          :disabled="loading"
          @click="goQueuePage(page + 1)"
        >
          {{ t('rag_queue.next_page') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
/* ---- visual language mirrors WorkspaceQueueTab (ops queue) ---- */
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

.queue-cell-primary {
  color: #0f172a;
  font-weight: 600;
  word-break: break-all;
}

.queue-cell-secondary {
  color: #64748b;
  word-break: break-all;
  font-size: 0.8125rem;
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

.queue-status.status-running {
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
}

.queue-status.status-consumed,
.queue-status.status-exported {
  background: #f0fdf4;
  color: #166534;
  border: 1px solid #bbf7d0;
}

.queue-status.status-queued {
  background: #fef9c3;
  color: #854d0e;
  border: 1px solid #fef08a;
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