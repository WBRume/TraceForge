<script setup lang="ts">
import { computed, reactive, watch, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { TableInstance } from 'element-plus'
import BaseSelect from '@/components/BaseSelect.vue'
import RequirementTaskProgress from './RequirementTaskProgress.vue'
import RequirementPendingItems from './RequirementPendingItems.vue'
import RequirementActionColumn from './RequirementActionColumn.vue'
import { Layers } from '@/components/icons'
import { requirementCoverageKey, requirementStatuses, requirementStatusKey } from '@/utils/requirementStatus'
import type { RequirementListQuery, RequirementSummary, RequirementWorkScope } from '@/types/workspaceAssets'

const props = withDefaults(defineProps<{
  canCreateTask?: boolean
  canManage?: boolean
  userId?: string
  claimingId?: string | null
  query?: RequirementListQuery
  items: readonly RequirementSummary[]
  total: number
  page: number
  pageSize: number
  loading?: boolean
}>(), { canManage: true })

const emit = defineEmits<{
  queryChange: [query: RequirementListQuery]
  open: [requirement: RequirementSummary]
  create: []
  createChild: [requirement: RequirementSummary]
  edit: [requirement: RequirementSummary]
  split: [requirement: RequirementSummary]
  createTask: [requirement: RequirementSummary]
  claim: [requirement: RequirementSummary, clarify: boolean]
}>()

const tableRef = ref<TableInstance>()

const { t } = useI18n()

const filters = reactive({
  q: props.query?.q || '',
  status: props.query?.status || '',
  priority: props.query?.priority || '',
  source_kind: props.query?.source_kind || '',
  work_scope: (props.query?.work_scope || 'all') as RequirementWorkScope,
  sort_by: props.query?.sort_by || 'updated_at' as NonNullable<RequirementListQuery['sort_by']>,
  sort_order: props.query?.sort_order || 'desc' as NonNullable<RequirementListQuery['sort_order']>,
  page: props.page || 1,
  page_size: props.pageSize || 20,
})
const workScopeOptions = computed(() => (['all', 'claimable', 'mine', 'clarify'] as const)
  .map(value => ({ label: t('workspace_assets.delivery.' + value), value })))

const statusOptions = computed(() => requirementStatuses.map(value => ({ label: t(requirementStatusKey(value)), value })))
const priorityOptions = ['P0', 'P1', 'P2', 'P3', 'High', 'Medium', 'Low'].map(opt => ({ label: opt, value: opt }))
const sourceOptions = ['document', 'manual', 'pasted_text', 'source_link', 'issue', 'ticket', 'split'].map(opt => ({ label: opt, value: opt }))

function collectNestedChildIds(items: readonly RequirementSummary[]): Set<string> {
  const childIds = new Set<string>()
  const visit = (item: RequirementSummary) => {
    for (const child of item.children || []) {
      childIds.add(child.id)
      visit(child)
    }
  }
  items.forEach(visit)
  return childIds
}

function normalizeRequirementRows(items: readonly RequirementSummary[]): RequirementSummary[] {
  const nestedChildIds = collectNestedChildIds(items)
  const seenIds = new Set<string>()

  const normalize = (item: RequirementSummary): RequirementSummary | null => {
    if (seenIds.has(item.id)) return null
    seenIds.add(item.id)
    const children = (item.children || [])
      .map((child) => normalize(child))
      .filter((child): child is RequirementSummary => Boolean(child))
    return {
      ...item,
      children,
    }
  }

  return items
    .filter((item) => !nestedChildIds.has(item.id))
    .map((item) => normalize(item))
    .filter((item): item is RequirementSummary => Boolean(item))
}

const tableRows = computed(() => normalizeRequirementRows(props.items))

watch(
  () => [props.page, props.pageSize] as const,
  ([page, pageSize]) => {
    filters.page = page || 1
    filters.page_size = pageSize || 20
  },
)

function compactQuery(): RequirementListQuery {
  return {
    q: filters.q.trim() || undefined,
    status: filters.status || undefined,
    priority: filters.priority || undefined,
    source_kind: filters.source_kind || undefined,
    work_scope: filters.work_scope,
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
  filters.status = ''
  filters.priority = ''
  filters.source_kind = ''
  filters.work_scope = 'all'
  filters.sort_by = 'updated_at'
  filters.sort_order = 'desc'
  filters.page = 1
  emit('queryChange', compactQuery())
}

function handleSortChange(event: { prop?: string; order?: 'ascending' | 'descending' | null }) {
  if (!event.prop) return
  filters.sort_by = event.prop as NonNullable<RequirementListQuery['sort_by']>
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

function sourceLabel(row: RequirementSummary): string {
  return row.source_ref || row.source_kind || t('workspace_assets.requirements.detail.source_pending')
}

function priorityLabel(priority: string) {
  const label = priority.trim()
  return /^p\d+$/i.test(label) ? label.toUpperCase() : label
}

function priorityTagType(priority: string) {
  const level = priority.trim().toUpperCase()
  if (level === 'P0') return 'danger'
  if (level === 'P1' || level === 'HIGH') return 'warning'
  if (level === 'P2' || level === 'MEDIUM') return 'primary'
  return 'info'
}

function childCount(row: RequirementSummary) {
  return row.child_count || row.children?.length || 0
}

function handleRowClick(row: RequirementSummary) {
  if (row.children && row.children.length > 0) {
    tableRef.value?.toggleRowExpansion(row)
  }
}
</script>

<template>
  <section class="requirement-table-workbench">
    <header class="table-toolbar">
      <h3>{{ t('workspace_assets.nav.requirements') }}</h3>
      <el-button v-if="canManage" type="primary" @click="emit('create')">
        {{ t('workspace_assets.requirements.actions.new') }}
      </el-button>
    </header>

    <el-form class="query-bar" label-position="top" @submit.prevent="submitQuery">
      <el-radio-group
        v-model="filters.work_scope"
        class="requirement-scope"
        :aria-label="t('workspace_assets.delivery.scope_label')"
        @change="submitQuery"
      >
        <el-radio-button v-for="option in workScopeOptions" :key="option.value" :value="option.value">
          {{ option.label }}
        </el-radio-button>
      </el-radio-group>
      <div class="query-grid">
        <el-form-item :label="t('workspace_assets.requirements.table.search')" class="search-field">
          <el-input
            v-model="filters.q"
            clearable
            :placeholder="t('workspace_assets.requirements.table.search_placeholder')"
            @keyup.enter="submitQuery"
            @clear="submitQuery"
          />
        </el-form-item>

        <el-form-item :label="t('workspace_assets.requirements.fields.status')" class="select-field">
          <BaseSelect v-model="filters.status" :options="statusOptions" :placeholder="t('workspace_assets.requirements.fields.status')" @update:model-value="submitQuery" />
        </el-form-item>

        <el-form-item :label="t('workspace_assets.requirements.fields.priority')" class="select-field">
          <BaseSelect v-model="filters.priority" :options="priorityOptions" :placeholder="t('workspace_assets.requirements.fields.priority')" @update:model-value="submitQuery" />
        </el-form-item>

        <el-form-item :label="t('workspace_assets.requirements.fields.source_kind')" class="select-field source-type">
          <BaseSelect v-model="filters.source_kind" :options="sourceOptions" :placeholder="t('workspace_assets.requirements.fields.source_kind')" @update:model-value="submitQuery" />
        </el-form-item>

        <div class="query-actions">
          <el-button type="primary" native-type="submit" class="action-btn">{{ t('workspace_assets.requirements.table.search_action') }}</el-button>
          <el-button class="action-btn secondary" @click="resetQuery">{{ t('workspace_assets.requirements.table.reset_action') }}</el-button>
        </div>
      </div>
    </el-form>

    <el-table
      ref="tableRef"
      v-loading="props.loading"
      :data="tableRows"
      row-key="id"
      :tree-props="{ children: 'children' }"
      class="requirements-table"
      empty-text=""
      @row-click="handleRowClick"
      @sort-change="handleSortChange"
    >
      <el-table-column prop="title" class-name="title-column" :label="t('workspace_assets.requirements.fields.title')" min-width="260" sortable="custom">
        <template #default="{ row }">
          <div class="title-cell" :class="{ 'is-child': !!row.parent_requirement_id }">
            <div class="title-line">
              <span class="title-text">{{ row.title }}</span>
              <el-tag
                v-if="row.priority?.trim()"
                class="priority-badge"
                :type="priorityTagType(row.priority)"
                effect="light"
                size="small"
              >
                {{ priorityLabel(row.priority) }}
              </el-tag>
              <el-tag
                v-if="childCount(row) > 0"
                class="child-count-badge"
                type="info"
                effect="light"
                size="small"
                :title="t('workspace_assets.requirements.table.child_count')"
                :aria-label="`${t('workspace_assets.requirements.table.child_count')} ${childCount(row)}`"
              >
                <Layers class="child-count-icon" />{{ childCount(row) }}
              </el-tag>
            </div>
            <span v-if="row.parent_title && !!row.parent_requirement_id" class="parent-hint">{{ row.parent_title }}</span>
            <span v-if="row.clarification_reason && filters.work_scope === 'clarify'" class="parent-hint">
              {{ row.clarification_reason === 'predecessor'
                ? t('workspace_assets.delivery.blocked', { title: row.predecessor_title })
                : t('workspace_assets.delivery.clarify_scope') }}
            </span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="status" :label="t('workspace_assets.requirements.fields.status')" width="110" sortable="custom">
        <template #default="{ row }">
          <el-tag :type="row.status === 'VERIFIED' ? 'success' : row.status === 'PENDING_ACCEPTANCE' ? 'warning' : row.status === 'REJECTED' ? 'danger' : 'primary'" effect="light">
            {{ t(requirementStatusKey(row.status)) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('workspace_assets.requirements.owner')" width="120">
        <template #default="{ row }">
          <span>{{ row.owner_name || t('workspace_assets.requirements.owner_unassigned') }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="related_task_count" :label="t('workspace_assets.requirements.table.task_count')" width="185" sortable="custom">
        <template #default="{ row }">
          <div class="related-cell">
            <RequirementTaskProgress :requirement="row" />
            <RequirementPendingItems v-if="row.task_progress" :requirement="row" />
          </div>
        </template>
      </el-table-column>
      <el-table-column :label="t('workspace_assets.requirements.fields.coverage')" width="145">
        <template #default="{ row }">
          <div class="coverage-cell">
            <el-tag type="warning" effect="light">{{ t(requirementCoverageKey(row.coverage_summary?.coverage_status)) }}</el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column :label="t('workspace_assets.requirements.fields.source_reference')" min-width="120">
        <template #default="{ row }">
          <span>{{ sourceLabel(row) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="updated_at" :label="t('workspace_assets.requirements.table.updated_at')" width="160" sortable="custom">
        <template #default="{ row }">
          <span>{{ row.updated_at || row.created_at || t('workspace_assets.requirements.detail.time_pending') }}</span>
        </template>
      </el-table-column>
      <el-table-column
        :label="t('workspace_assets.requirements.table.operations')"
        fixed="right"
        width="150"
        class-name="operation-column"
      >
        <template #default="{ row }">
          <RequirementActionColumn
            :requirement="row"
            :user-id="userId"
            :can-manage="canManage"
            :can-create-task="canCreateTask"
            :claiming="claimingId === row.id"
            @open="emit('open', row)"
            @edit="emit('edit', row)"
            @create-task="emit('createTask', row)"
            @create-child="emit('createChild', row)"
            @split="emit('split', row)"
            @claim="(clarify: boolean) => emit('claim', row, clarify)"
          />
        </template>
      </el-table-column>
      <template #empty>
        <el-empty :description="t('workspace_assets.requirements.repository.empty_body')" />
      </template>
    </el-table>

    <footer class="pagination-row">
      <span>{{ t('workspace_assets.requirements.table.total', { total: props.total }) }}</span>
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
.related-cell { display: grid; gap: 5px; padding-block: 4px; }
.requirement-table-workbench {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
  padding: 20px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #ffffff;
  box-shadow: 0 16px 40px rgba(15, 23, 42, 0.06);
}

.table-toolbar,
.pagination-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.table-toolbar h3 {
  margin: 4px 0;
  color: #0f172a;
  font-size: 20px;
}

.table-toolbar p {
  margin: 0;
  color: #64748b;
  line-height: 1.55;
}

.table-body {
  max-width: 760px;
}

.eyebrow {
  color: #2563eb;
  font-size: 12px;
  font-weight: 800;
}

.query-bar {
  container-type: inline-size;
  padding: 1.25rem;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid rgba(226, 232, 240, 0.6);
}

.requirement-scope {
  --el-border-radius-base: var(--radius-md);
  margin-bottom: 16px;
}

.requirement-scope :deep(.el-radio-button) {
  --el-radio-button-checked-bg-color: var(--color-primary-500);
  --el-radio-button-checked-border-color: var(--color-primary-500);
  --el-radio-button-checked-text-color: #ffffff;
}

@container (max-width: 470px) {
  .requirement-scope {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px;
  }

  .requirement-scope :deep(.el-radio-button__inner) {
    width: 100%;
    height: 100%;
    padding-inline: 8px;
    border: 1px solid var(--el-border-color);
    border-radius: var(--radius-md);
    outline: none;
    white-space: normal;
    overflow-wrap: anywhere;
  }

  .requirement-scope :deep(.el-radio-button.is-active .el-radio-button__inner) {
    box-shadow: none;
  }

  .requirement-scope :deep(.el-radio-button__original-radio:focus-visible + .el-radio-button__inner) {
    outline: 2px solid var(--color-primary-600);
  }
}

.query-grid {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 1.25rem;
}

.search-field {
  flex: 1;
  min-width: min(100%, 320px);
  margin-bottom: 0 !important;
}

.select-field {
  width: 160px;
  margin-bottom: 0 !important;
}

.source-type {
  width: 200px;
}

.search-field :deep(.el-input__wrapper) {
  height: 42px;
  border-radius: 8px;
  box-shadow: 0 0 0 1px rgba(226, 232, 240, 0.8) inset;
}

.search-field :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px #0ea5e9 inset !important;
}

:deep(.el-form-item__label) {
  font-weight: 600;
  color: #475569;
  margin-bottom: 8px !important;
  font-size: 0.875rem;
  line-height: 1.2 !important;
  padding: 0 !important;
}

.query-actions {
  display: flex;
  gap: 0.75rem;
  margin-left: auto;
  padding-top: 28px; /* Offset for top labels to align with inputs */
}

.action-btn {
  height: 42px;
  padding: 0 1.5rem;
  border-radius: 8px;
  font-weight: 600;
  font-size: 0.875rem;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  align-items: center;
  justify-content: center;
}

.action-btn.secondary {
  background: white;
  border-color: #e2e8f0;
  color: #64748b;
}

.action-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}

.requirements-table :deep(th.el-table__cell .cell) {
  white-space: nowrap;
}

.requirements-table {
  width: 100%;
}

.requirements-table :deep(.title-column .cell) {
  display: flex;
  align-items: center;
}

.requirements-table :deep(.el-table__indent),
.requirements-table :deep(.el-table__expand-icon),
.requirements-table :deep(.el-table__placeholder) {
  flex-shrink: 0;
}

.title-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 0;
  flex: 1;
}

.title-text {
  font-weight: 600;
  color: #1e293b;
  font-size: 14px;
}

.priority-badge {
  margin-inline-start: 6px;
  vertical-align: baseline;
}

.child-count-badge {
  margin-inline-start: 6px;
  vertical-align: baseline;
}

.child-count-icon {
  width: 11px;
  height: 11px;
  margin-inline-end: 3px;
}

.is-child {
  padding-left: 22px;
  position: relative;
}

.is-child .title-text {
  font-weight: 500;
  color: #475569;
  font-size: 13px;
}

.is-child::before {
  content: "";
  position: absolute;
  left: 6px;
  top: -8px;
  bottom: 12px;
  width: 12px;
  border-left: 1px solid #cbd5e1;
  border-bottom: 1px solid #cbd5e1;
  border-bottom-left-radius: 4px;
}

.parent-hint {
  font-size: 11px;
  color: #94a3b8;
  font-weight: 400;
}

.coverage-cell {
  display: grid;
}

.requirements-table :deep(.operation-column .cell) {
  overflow: visible;
}

.pagination-row {
  flex-wrap: wrap;
  padding-top: 4px;
  color: #64748b;
  font-size: 13px;
}
</style>
