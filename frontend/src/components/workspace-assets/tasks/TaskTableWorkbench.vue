<script setup lang="ts">
import { reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseSelect from '@/components/BaseSelect.vue'
import type { TaskListQuery, TaskSummary, TaskListSummaryStats } from '@/types/workspaceAssets'

const props = defineProps<{
  items: readonly TaskSummary[]
  total: number
  page: number
  pageSize: number
  loading?: boolean
  stats?: TaskListSummaryStats | null
}>()

const emit = defineEmits<{
  queryChange: [query: TaskListQuery]
  open: [task: TaskSummary]
}>()

const { t } = useI18n()

const filters = reactive({
  q: '',
  requirement_q: '',
  status: '',
  current_phase: '',
  sort_by: 'updated_at' as NonNullable<TaskListQuery['sort_by']>,
  sort_order: 'desc' as NonNullable<TaskListQuery['sort_order']>,
  page: props.page || 1,
  page_size: props.pageSize || 20,
})

const statusOptions = ['PENDING', 'RUNNING', 'DONE', 'FAILED'].map(opt => ({ label: opt, value: opt }))
const phaseOptions = [
  'REQUIREMENT_CLARIFICATION',
  'AI_SOLUTION',
  'CODING',
  'COMPILE',
  'PACKAGE',
  'DEVICE_TEST',
  'INTEGRATION',
  'OTHER'
].map(opt => ({ label: opt, value: opt }))

watch(
  () => [props.page, props.pageSize] as const,
  ([page, pageSize]) => {
    filters.page = page || 1
    filters.page_size = pageSize || 20
  },
)

function compactQuery(): TaskListQuery {
  return {
    q: filters.q.trim() || undefined,
    requirement_q: filters.requirement_q.trim() || undefined,
    status: filters.status || undefined,
    current_phase: filters.current_phase || undefined,
    sort_by: filters.sort_by,
    sort_order: filters.sort_order,
    page: filters.page,
    page_size: filters.page_size,
  }
}

function submitQuery() {
  filters.page = 1
  emit('queryChange', compactQuery())
}

function resetQuery() {
  filters.q = ''
  filters.requirement_q = ''
  filters.status = ''
  filters.current_phase = ''
  filters.sort_by = 'updated_at'
  filters.sort_order = 'desc'
  filters.page = 1
  emit('queryChange', compactQuery())
}

function handleSortChange(event: { prop?: string; order?: 'ascending' | 'descending' | null }) {
  if (!event.prop) return
  filters.sort_by = event.prop as NonNullable<TaskListQuery['sort_by']>
  filters.sort_order = event.order === 'ascending' ? 'asc' : 'desc'
  filters.page = 1
  emit('queryChange', compactQuery())
}

function handlePageChange(page: number) {
  filters.page = page
  emit('queryChange', compactQuery())
}

function handlePageSizeChange(pageSize: number) {
  filters.page_size = pageSize
  filters.page = 1
  emit('queryChange', compactQuery())
}

function getStatusType(status: string) {
  if (status === 'DONE') return 'success'
  if (status === 'FAILED') return 'danger'
  if (status === 'RUNNING') return 'primary'
  return 'info'
}

function handleRowClick(row: TaskSummary) {
  emit('open', row)
}
</script>

<template>
  <section class="asset-table-workbench">
    <header class="table-toolbar">
      <p class="eyebrow">{{ t('workspace_assets.tasks.table.eyebrow') }}</p>
    </header>

    <el-form class="query-bar" label-position="top" @submit.prevent="submitQuery">
      <div class="query-grid">
        <el-form-item :label="t('workspace_assets.tasks.table.search')" class="search-field">
          <el-input
            v-model="filters.q"
            clearable
            :placeholder="t('workspace_assets.tasks.table.search_placeholder')"
            @keyup.enter="submitQuery"
            @clear="submitQuery"
          />
        </el-form-item>

        <el-form-item :label="t('workspace_assets.tasks.fields.requirement_q')" class="search-field">
          <el-input
            v-model="filters.requirement_q"
            clearable
            :placeholder="t('workspace_assets.tasks.fields.requirement_q_placeholder')"
            @keyup.enter="submitQuery"
            @clear="submitQuery"
          />
        </el-form-item>

        <el-form-item :label="t('workspace_assets.tasks.fields.status')" class="select-field">
          <BaseSelect
            v-model="filters.status"
            :options="statusOptions"
            :placeholder="t('workspace_assets.tasks.fields.status')"
            @update:model-value="submitQuery"
          />
        </el-form-item>

        <el-form-item :label="t('workspace_assets.tasks.fields.current_phase')" class="select-field">
          <BaseSelect
            v-model="filters.current_phase"
            :options="phaseOptions"
            :placeholder="t('workspace_assets.tasks.fields.current_phase')"
            @update:model-value="submitQuery"
          />
        </el-form-item>

        <div class="query-actions">
          <div class="inline-metrics" v-if="props.stats">
            <div class="metric-pill">
              <span class="label">{{ t('workspace_assets.tasks.summary.review_pending') }}</span>
              <strong class="value">{{ props.stats.review_pending_count }}</strong>
            </div>
            <div class="metric-pill">
              <span class="label">{{ t('workspace_assets.tasks.summary.evidence_missing') }}</span>
              <strong class="value">{{ props.stats.evidence_missing_count }}</strong>
            </div>
            <div class="metric-pill">
              <span class="label">{{ t('workspace_assets.tasks.summary.human_delta') }}</span>
              <strong class="value">{{ props.stats.human_delta_count }}</strong>
            </div>
            <div class="metric-pill">
              <span class="label">{{ t('workspace_assets.tasks.summary.clarification_pending') }}</span>
              <strong class="value">{{ props.stats.clarification_pending_count }}</strong>
            </div>
          </div>
          <el-button type="primary" native-type="submit" class="action-btn">
            {{ t('workspace_assets.tasks.table.search_action') }}
          </el-button>
          <el-button class="action-btn secondary" @click="resetQuery">
            {{ t('workspace_assets.tasks.table.reset_action') }}
          </el-button>
        </div>
      </div>
    </el-form>

    <el-table
      ref="tableRef"
      v-loading="props.loading"
      :data="props.items"
      row-key="id"
      class="asset-table"
      empty-text=""
      @row-click="handleRowClick"
      @sort-change="handleSortChange"
    >
      <el-table-column prop="name" class-name="title-column" :label="t('workspace_assets.tasks.table.task_name')" min-width="300" sortable="custom">
        <template #default="{ row }">
          <div class="title-cell">
            <span class="title-text">{{ row.name }}</span>
            <span v-if="row.description" class="parent-hint">{{ row.description }}</span>
          </div>
        </template>
      </el-table-column>

      <el-table-column prop="status" :label="t('workspace_assets.tasks.fields.status')" width="110" sortable="custom">
        <template #default="{ row }">
          <el-tag :type="getStatusType(row.status)" effect="light">{{ row.status }}</el-tag>
        </template>
      </el-table-column>

      <el-table-column prop="current_phase" :label="t('workspace_assets.tasks.fields.current_phase')" width="160" sortable="custom">
        <template #default="{ row }">
          <el-tag v-if="row.current_phase" type="info" effect="light">{{ row.current_phase }}</el-tag>
          <span v-else>-</span>
        </template>
      </el-table-column>

      <el-table-column prop="requirement_count" :label="t('workspace_assets.tasks.table.requirement_count')" width="130" sortable="custom" />
      <el-table-column prop="evidence_count" :label="t('workspace_assets.tasks.table.evidence_count')" width="130" sortable="custom" />

      <el-table-column :label="t('workspace_assets.tasks.table.coverage')" width="160">
        <template #default="{ row }">
          <div class="coverage-cell">
            <el-tag type="warning" effect="light">{{ row.coverage_status || 'not_available' }}</el-tag>
            <small>{{ t('workspace_assets.tasks.table.coverage_readonly') }}</small>
          </div>
        </template>
      </el-table-column>

      <el-table-column prop="updated_at" :label="t('workspace_assets.tasks.table.updated_at')" width="160" sortable="custom">
        <template #default="{ row }">
          <span>{{ row.updated_at || row.created_at }}</span>
        </template>
      </el-table-column>

      <el-table-column :label="t('workspace_assets.tasks.table.operations')" width="120" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click.stop="emit('open', row)">
            {{ t('workspace_assets.tasks.table.view_detail') }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <footer class="pagination-row">
      <span>{{ t('workspace_assets.tasks.table.total', { total: props.total }) }}</span>
      <el-pagination
        background
        layout="sizes, prev, pager, next"
        :total="props.total"
        :current-page="filters.page"
        :page-size="filters.page_size"
        :page-sizes="[10, 20, 50, 100]"
        @current-change="handlePageChange"
        @size-change="handlePageSizeChange"
      />
    </footer>
  </section>
</template>

<style scoped>
@import '../asset-table-workbench.css';

/* ── Task-specific: parent-hint truncation ── */
.parent-hint {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── Task-specific: inline metrics strip ── */
.inline-metrics {
  display: flex;
  align-items: center;
  gap: 12px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 0 16px;
  height: 42px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

.metric-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.metric-pill:not(:last-child)::after {
  content: '';
  display: block;
  width: 1px;
  height: 14px;
  background-color: #cbd5e1;
  margin-left: 12px;
}

.metric-pill .label {
  color: #64748b;
  font-weight: 500;
}

.metric-pill .value {
  color: #0ea5e9;
  font-weight: 700;
  font-size: 15px;
  font-family: 'Poppins', sans-serif;
}
</style>
