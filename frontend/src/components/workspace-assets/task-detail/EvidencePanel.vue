<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Plus } from 'lucide-vue-next'
import TaskAssetEmptyState from './TaskAssetEmptyState.vue'
import EvidenceCard from './EvidenceCard.vue'
import EvidenceMountDialog from './EvidenceMountDialog.vue'
import EvidenceDetailDialog from './EvidenceDetailDialog.vue'
import { useTaskDetailAssets } from '@/composables/useTaskDetailAssets'
import type { EvidenceLight, EvidenceMutationPayload } from '@/types/workspaceAssets'

const props = defineProps<{
  evidence: EvidenceLight[]
  workspaceId: string
  taskId: string
  taskStatus?: string
  total?: number
  page?: number
  pageSize?: number
}>()

const emit = defineEmits<{
  mutated: []
  'page-change': [payload: { page: number; pageSize: number }]
}>()

const { t } = useI18n()
const taskAssets = useTaskDetailAssets()

const mountDialogVisible = ref(false)
const detailVisible = ref(false)
const detailEvidenceId = ref<string | null>(null)

const isRunning = computed(() => {
  const s = (props.taskStatus || '').toUpperCase()
  return Boolean(s && s !== 'DONE' && s !== 'FAILED')
})

const isDone = computed(() => (props.taskStatus || '').toUpperCase() === 'DONE')
const isFailed = computed(() => (props.taskStatus || '').toUpperCase() === 'FAILED')

const canMount = computed(() => isDone.value || isFailed.value)

function openMountDialog() {
  mountDialogVisible.value = true
}

function openDetail(evidenceId: string) {
  detailEvidenceId.value = evidenceId
  detailVisible.value = true
}

async function handleMountSubmit(payload: EvidenceMutationPayload) {
  const result = await taskAssets.createEvidence(props.workspaceId, props.taskId, payload)
  if (!result) return
  mountDialogVisible.value = false
  emit('mutated')
  ElMessage.success(t('workspace_assets.task_detail.workbench.evidence_mount.success'))
}

function handleCurrentChange(newPage: number) {
  emit('page-change', { page: newPage, pageSize: props.pageSize || 10 })
}

function handleSizeChange(newSize: number) {
  emit('page-change', { page: 1, pageSize: newSize })
}
</script>

<template>
  <section class="panel-shell">
    <header class="panel-head">
      <div>
        <span class="eyebrow">{{ t('workspace_assets.task_detail.workbench.evidence.eyebrow') }}</span>
        <h2>{{ t('workspace_assets.task_detail.workbench.evidence.title') }}</h2>
        <p>{{ t('workspace_assets.task_detail.workbench.evidence.description') }}</p>
      </div>
      <button
        v-if="canMount"
        class="mount-btn"
        :class="isFailed ? 'mount-btn--fail' : 'mount-btn--success'"
        @click="openMountDialog"
      >
        <Plus :size="16" />
        {{ t('workspace_assets.task_detail.workbench.evidence_mount.open') }}
      </button>
    </header>

    <el-alert
      v-if="isRunning"
      class="phase-alert"
      type="info"
      :closable="false"
      :title="t('workspace_assets.task_detail.workbench.evidence.task_running_hint')"
    />

    <TaskAssetEmptyState
      v-if="!evidence.length"
      :title="t('workspace_assets.task_detail.workbench.evidence.empty_title')"
      :message="t('workspace_assets.task_detail.workbench.evidence.empty')"
    />

    <div v-else class="evidence-grid">
      <EvidenceCard
        v-for="ev in evidence"
        :key="ev.id"
        :evidence="ev"
        :readonly="isRunning"
        @view-detail="openDetail"
      />
    </div>

    <EvidenceMountDialog
      :show="mountDialogVisible"
      :task-status="taskStatus || ''"
      :saving="taskAssets.saving.value"
      @close="mountDialogVisible = false"
      @submit="handleMountSubmit"
    />

    <EvidenceDetailDialog
      v-model:visible="detailVisible"
      :evidence-id="detailEvidenceId"
      :workspace-id="workspaceId"
      :task-id="taskId"
    />

    <el-pagination
      v-if="(props.total ?? 0) > 0"
      class="section-pagination"
      :current-page="props.page || 1"
      :page-size="props.pageSize || 10"
      :total="props.total || 0"
      :page-sizes="[10, 20, 50]"
      layout="total, sizes, prev, pager, next, jumper"
      :total-text="t('workspace_assets.task_detail.workbench.pagination.total', { total: props.total || 0 })"
      :page-size-text="t('workspace_assets.task_detail.workbench.pagination.page_size')"
      @current-change="handleCurrentChange"
      @size-change="handleSizeChange"
    />
  </section>
</template>

<style scoped>
.panel-shell {
  display: grid;
  gap: 14px;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid #e2e8f0;
}

.panel-head > div {
  flex: 1;
}

.eyebrow {
  color: #2563eb;
  font-size: 0.75rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.panel-head h2 {
  margin: 5px 0 0;
  color: #0f172a;
  font-family: 'Poppins', sans-serif;
  font-size: 1.5rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.panel-head p {
  margin: 8px 0 0;
  color: #64748b;
  font-size: 0.95rem;
  line-height: 1.6;
}

.mount-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 1.25rem;
  font-size: 0.8125rem;
  font-weight: 600;
  border: none;
  border-radius: 0.75rem;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  white-space: nowrap;
  flex-shrink: 0;
}

.mount-btn--success {
  color: #ffffff;
  background: linear-gradient(to bottom, #10b981, #059669);
  box-shadow: 0 1px 2px 0 rgba(16, 185, 129, 0.2);
}

.mount-btn--success:hover {
  background: linear-gradient(to bottom, #059669, #047857);
  transform: translateY(-1px);
  box-shadow: 0 4px 6px -1px rgba(16, 185, 129, 0.2);
}

.mount-btn--fail {
  color: #ffffff;
  background: linear-gradient(to bottom, #ef4444, #dc2626);
  box-shadow: 0 1px 2px 0 rgba(239, 68, 68, 0.2);
}

.mount-btn--fail:hover {
  background: linear-gradient(to bottom, #dc2626, #b91c1c);
  transform: translateY(-1px);
  box-shadow: 0 4px 6px -1px rgba(239, 68, 68, 0.2);
}

.phase-alert {
  border-radius: 8px;
}

.evidence-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 0.75rem;
}

@media (max-width: 920px) {
  .evidence-grid {
    grid-template-columns: 1fr;
  }
}

.section-pagination {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
