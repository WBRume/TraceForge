<script setup lang="ts">
import { shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import TaskAssetEmptyState from './TaskAssetEmptyState.vue'
import DecisionBackfillDialog from './DecisionBackfillDialog.vue'
import DecisionDetailDialog from './DecisionDetailDialog.vue'
import DecisionSourceLink from './DecisionSourceLink.vue'
import type {
  DecisionLight,
  HumanDeltaLight,
  EvidenceLight,
  TaskRequirementLink,
} from '@/types/workspaceAssets'

const props = defineProps<{
  decisions: DecisionLight[]
  workspaceId: string
  taskId: string
  requirementLinks?: TaskRequirementLink[]
  humanDeltas?: HumanDeltaLight[]
  evidence?: EvidenceLight[]
  total?: number
  page?: number
  pageSize?: number
}>()

const emit = defineEmits<{
  mutated: []
  'page-change': [payload: { page: number; pageSize: number }]
}>()

const { t } = useI18n()
const showBackfillDialog = shallowRef(false)
const detailVisible = shallowRef(false)
const detailDecisionId = shallowRef<string | null>(null)

function openDetail(row: DecisionLight) {
  detailDecisionId.value = row.id
  detailVisible.value = true
}

const statusTagType = (status: string) => {
  const s = (status || '').toUpperCase()
  if (s === 'ACCEPTED') return 'success'
  if (s === 'PROPOSED') return ''
  if (s === 'REJECTED') return 'danger'
  if (s === 'SUPERSEDED') return 'info'
  return 'info'
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
        <span class="eyebrow">{{ t('workspace_assets.task_detail.workbench.decisions.eyebrow') }}</span>
        <h2>{{ t('workspace_assets.task_detail.workbench.decisions.title') }}</h2>
        <p>{{ t('workspace_assets.task_detail.workbench.decisions.description') }}</p>
      </div>
      <el-button type="primary" plain @click="showBackfillDialog = true">
        {{ t('workspace_assets.task_detail.workbench.decisions.backfill') }}
      </el-button>
    </header>

    <TaskAssetEmptyState
      v-if="!decisions.length"
      :title="t('workspace_assets.task_detail.workbench.decisions.empty_title')"
      :message="t('workspace_assets.task_detail.workbench.decisions.empty')"
    />

    <el-table v-else :data="decisions" row-key="id" border class="clickable-table" @row-click="openDetail">
      <el-table-column prop="title" :label="t('workspace_assets.task_detail.workbench.fields.title')" min-width="220" />
      <el-table-column :label="t('workspace_assets.task_detail.workbench.fields.source')" min-width="190">
        <template #default="{ row }">
          <DecisionSourceLink :source="row.source" :workspace-id="workspaceId" :task-id="taskId" />
        </template>
      </el-table-column>
      <el-table-column prop="impact_scope" :label="t('workspace_assets.task_detail.workbench.fields.impact_scope')" min-width="180" />
      <el-table-column :label="t('workspace_assets.task_detail.workbench.fields.status')" width="130">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)" effect="dark" size="small">
            {{ row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('workspace_assets.task_detail.workbench.fields.promote_candidate')" width="140">
        <template #default="{ row }">
          <el-tag :type="row.promote_candidate ? 'success' : 'info'" effect="plain">
            {{ row.promote_candidate ? t('common.yes') : t('common.no') }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>

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

    <DecisionDetailDialog
      v-model:visible="detailVisible"
      :decision-id="detailDecisionId"
      :workspace-id="workspaceId"
      :task-id="taskId"
    />

    <DecisionBackfillDialog
      v-model:visible="showBackfillDialog"
      :workspace-id="workspaceId"
      :task-id="taskId"
      :requirement-links="requirementLinks"
      :human-deltas="humanDeltas"
      :evidence="evidence"
      @mutated="emit('mutated')"
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
  gap: 12px;
  padding-bottom: 14px;
  border-bottom: 1px solid #e2e8f0;
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

.clickable-table :deep(.el-table__body tr) {
  cursor: pointer;
  transition: background-color 0.15s;
}

.clickable-table :deep(.el-table__body tr:hover > td) {
  background-color: #f0f7ff;
}

.section-pagination {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
