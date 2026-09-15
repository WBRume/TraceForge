<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { ArrowLeft } from 'lucide-vue-next'
import { useWorkspaceStore } from '@/stores/workspace'
import { formatApiError } from '@/utils/error'
import {
  confirmRagQueueCaseDownload,
  confirmRagQueueDownload,
  downloadRagQueueCase,
  downloadRagQueueZip,
  fetchRagQueue,
  fetchRagQueueCases,
} from '@/composables/rag/ragOutboxOps'
import type { RagQueueCaseItem, RagSyncQueueItem } from '@/types/rag'

const route = useRoute()
const router = useRouter()
const { locale, t } = useI18n()
const wsStore = useWorkspaceStore()

const queueId = computed(() => String(route.params.queueId || '').trim())

const queue = ref<RagSyncQueueItem | null>(null)
const detailCases = ref<RagQueueCaseItem[]>([])
const loading = ref(true)
const loadError = ref('')
const downloadingQueue = ref(false)
const downloadingCaseId = ref('')

let pollTimer: number | null = null
let fetching = false

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

const caseStatusText = (status: string): string => {
  const keyMap: Record<string, string> = {
    QUEUED: 'rag_queue.case_status_queued',
    EXPORTED: 'rag_queue.case_status_exported',
  }
  return keyMap[status] ? t(keyMap[status]) : status
}

const formatDate = (value?: string | null): string => {
  if (!value) return '-'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return '-'
  return dt.toLocaleString(locale.value)
}

const loadDetail = async ({ silent = false }: { silent?: boolean } = {}) => {
  if (!queueId.value || fetching) return
  fetching = true
  if (!silent) loading.value = true
  if (!silent) loadError.value = ''
  try {
    const [q, casePage] = await Promise.all([
      fetchRagQueue(queueId.value),
      fetchRagQueueCases(queueId.value, { page: 1, page_size: 200 }),
    ])
    queue.value = q
    detailCases.value = casePage.items ?? []
  } catch (err) {
    if (!silent) {
      queue.value = null
      detailCases.value = []
      loadError.value = formatApiError(err, t('rag_queue.detail_load_failed'), t)
    }
  } finally {
    loading.value = false
    fetching = false
  }
}

const downloadQueue = async () => {
  if (!queue.value || downloadingQueue.value) return
  downloadingQueue.value = true
  let savedLocally = false
  try {
    const save = await downloadRagQueueZip(queue.value.id, queue.value.name)
    if (save.canceled) {
      ElMessage.info(t('rag_queue.save_canceled'))
      return
    }
    savedLocally = true
    await confirmRagQueueDownload(queue.value.id)
    ElMessage.success(
      queue.value.status === 'CONSUMED'
        ? t('rag_queue.download_again_success')
        : t('rag_queue.download_success'),
    )
    await loadDetail({ silent: true })
  } catch {
    ElMessage.error(
      savedLocally ? t('rag_queue.mark_queue_failed') : t('rag_queue.download_failed'),
    )
  } finally {
    downloadingQueue.value = false
  }
}

const downloadCase = async (row: RagQueueCaseItem) => {
  if (!queue.value || downloadingCaseId.value) return
  downloadingCaseId.value = row.id
  const safeTitle = (row.title || row.doc_key || 'case').replace(/[\\/:*?"<>|]+/g, '_').slice(0, 120)
  let savedLocally = false
  try {
    const save = await downloadRagQueueCase(
      queue.value.id,
      row.id,
      `${safeTitle || 'case'}.md`,
    )
    if (save.canceled) {
      ElMessage.info(t('rag_queue.save_case_canceled'))
      return
    }
    savedLocally = true
    await confirmRagQueueCaseDownload(queue.value.id, row.id)
    ElMessage.success(t('rag_queue.download_case_success'))
    await loadDetail({ silent: true })
  } catch {
    ElMessage.error(
      savedLocally ? t('rag_queue.mark_case_failed') : t('rag_queue.download_case_failed'),
    )
  } finally {
    downloadingCaseId.value = ''
  }
}

const goBack = () => {
  if (window.history.length > 1) {
    router.back()
  } else {
    router.push('/ops/rag-queue')
  }
}

onMounted(async () => {
  await wsStore.fetchWorkspaces()
  void loadDetail()
  pollTimer = window.setInterval(() => {
    void loadDetail({ silent: true })
  }, 5000)
})

onBeforeUnmount(() => {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
})

watch(queueId, () => {
  queue.value = null
  detailCases.value = []
  void loadDetail()
})
</script>

<template>
  <div class="queue-detail-page">
    <!-- 头部布局与产品详情页保持一致：返回按钮内嵌于页头、置于标题上方，带返回图标 -->
    <div class="mgmt-page-header">
      <div>
        <button type="button" class="btn-secondary mgmt-back" @click="goBack">
          <ArrowLeft class="w-4 h-4" />
          {{ t('rag_queue.back') }}
        </button>
        <h2 v-if="queue" class="mgmt-detail-title">
          {{ queue.name }}
          <span
            class="queue-status"
            :class="`status-${String(queue.status || '').toLowerCase()}`"
          >
            {{ queueStatusText(queue.status) }}
          </span>
        </h2>
        <h2 v-else class="mgmt-detail-title">{{ t('rag_queue.detail_title') }}</h2>
        <p class="mgmt-subtitle">
          {{ queue ? t('rag_queue.detail_subtitle', { id: queue.id }) : t('rag_queue.loading') }}
        </p>
      </div>
    </div>

    <div v-if="loading" class="loading-state glass-panel">{{ t('rag_queue.loading') }}</div>

    <div v-else-if="loadError" class="glass-panel queue-panel">
      <p class="create-error">{{ loadError }}</p>
    </div>

    <template v-else-if="queue">
      <div class="queue-panel glass-panel queue-meta">
        <div class="queue-meta-top">
          <span class="queue-detail-counts">
            {{
              queue.workspace_id
                ? workspaceNameMap[queue.workspace_id] || queue.workspace_id
                : t('rag_queue.workspace_unassigned')
            }}
            ·
            {{ t('rag_queue.col_case_count') }}: {{ queue.case_count ?? 0 }} ·
            {{ t('rag_queue.col_exported_count') }}: {{ queue.exported_count ?? 0 }}
          </span>
        </div>
        <div class="queue-meta-bottom">
          <div class="queue-meta-item">
            <span class="meta-label">{{ t('rag_queue.col_created') }}</span>
            <span class="meta-value">{{ formatDate(queue.created_at) }}</span>
          </div>
          <div class="queue-meta-item">
            <span class="meta-label">{{ t('rag_queue.col_consumed') }}</span>
            <span class="meta-value">{{ formatDate(queue.consumed_at) }}</span>
          </div>
          <button
            type="button"
            class="btn-queue btn-queue-primary"
            :disabled="downloadingQueue"
            @click="downloadQueue"
          >
            {{
              queue.status === 'CONSUMED'
                ? t('rag_queue.download_again')
                : t('rag_queue.download')
            }}
          </button>
        </div>
        <p v-if="queue.status === 'CONSUMED'" class="queue-detail-hint">
          {{ t('rag_queue.consume_hint') }}
        </p>
      </div>

      <div class="queue-panel glass-panel">
        <p v-if="loadError" class="create-error">{{ loadError }}</p>

        <div v-if="detailCases.length === 0" class="empty-state queue-empty">
          <h3>{{ t('rag_queue.cases_empty') }}</h3>
        </div>

        <div v-else class="queue-table-wrap">
          <table class="queue-table">
            <thead>
              <tr>
                <th>{{ t('rag_queue.col_case_title') }}</th>
                <th>{{ t('rag_queue.col_workspace') }}</th>
                <th>{{ t('rag_queue.col_version') }}</th>
                <th>{{ t('rag_queue.col_case_status') }}</th>
                <th>{{ t('rag_queue.col_exported_at') }}</th>
                <th>{{ t('rag_queue.col_actions') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in detailCases" :key="row.id">
                <td>
                  <span class="queue-cell-primary">{{ row.title || row.doc_key }}</span>
                </td>
                <td>{{ workspaceNameMap[row.workspace_id || ''] || '-' }}</td>
                <td>{{ row.version ?? '-' }}</td>
                <td>
                  <span
                    class="queue-status"
                    :class="`status-${String(row.status || '').toLowerCase()}`"
                  >
                    {{ caseStatusText(row.status) }}
                  </span>
                </td>
                <td>{{ formatDate(row.exported_at) }}</td>
                <td>
                  <div class="queue-actions">
                    <button
                      type="button"
                      class="btn-queue"
                      :disabled="!!downloadingCaseId"
                      @click="downloadCase(row)"
                    >
                      {{ t('rag_queue.download_case') }}
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.queue-detail-page {
  width: 100%;
}

/* 返回按钮：与产品/项目详情页一致（mgmt-back 主色胶囊 + 返回图标） */
.mgmt-back {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  border-radius: 9999px;
  border: 1px solid rgba(37, 99, 235, 0.35);
  color: #2563eb;
  padding: 0.4rem 0.85rem;
  font-size: 0.8rem;
  font-weight: 600;
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.08), rgba(59, 130, 246, 0.02));
  transition: all 0.2s ease;
  margin-bottom: 0.75rem;
  cursor: pointer;
}

.mgmt-back:hover {
  border-color: #2563eb;
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.18), rgba(59, 130, 246, 0.06));
  transform: translateX(-3px);
}

.w-4 {
  width: 1rem;
  height: 1rem;
}

/* mgmt-page-header 的 h2 渐变文字会把 -webkit-text-fill-color: transparent
   继承给标题内徽标，需显式恢复为 currentColor（与产品详情页做法一致） */
.mgmt-detail-title .queue-status {
  -webkit-text-fill-color: currentColor;
}

.queue-panel {
  padding: 2rem;
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 1.5rem;
  box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05), 0 8px 10px -6px rgba(0, 0, 0, 0.01);
  transition: all 0.3s ease;
}

.queue-meta {
  margin-bottom: 1.5rem;
}

.queue-meta-top {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
  margin-bottom: 1rem;
}

.queue-detail-counts {
  color: #475569;
  font-size: 0.875rem;
  font-weight: 500;
}

.queue-meta-bottom {
  display: flex;
  align-items: center;
  gap: 2rem;
  flex-wrap: wrap;
}

.queue-meta-item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.meta-label {
  color: #64748b;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.meta-value {
  color: #0f172a;
  font-size: 0.875rem;
  font-weight: 500;
}

.queue-detail-hint {
  margin-top: 1rem;
  color: #947a00;
  font-size: 0.8125rem;
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
  min-width: 860px;
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
  margin-left: auto;
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

.create-error {
  margin: 0;
  color: #b91c1c;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: var(--radius-md);
  padding: 10px 12px;
  font-size: 0.875rem;
}

.loading-state {
  padding: 4rem 2rem;
  text-align: center;
  color: #64748b;
  font-size: 0.95rem;
}
</style>