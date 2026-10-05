<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { BookMarked, ChevronDown, ChevronUp, Loader2 } from '@/components/icons'
import CaseStatusPill from './CaseStatusPill.vue'
import CaseCategoryTag from './CaseCategoryTag.vue'
import CasePriorityTag from './CasePriorityTag.vue'
import type { CaseListItem, CaseSort } from '@/types/caseCenter'

const props = defineProps<{
  items: CaseListItem[]
  loading: boolean
  error: string
  filtered: boolean
  selectedCases: Record<string, string>
  promotionWorkspace: string
  sortBy: CaseSort['sort_by']
  sortOrder: CaseSort['sort_order']
}>()
const emit = defineEmits<{
  open: [item: CaseListItem]
  toggle: [id: string, workspaceId: string]
  'toggle-page': [items: CaseListItem[]]
  sort: [sort: CaseSort]
}>()
const { t } = useI18n()

interface TableColumn {
  key: string
  label: string
  width: string
  sortBy?: CaseSort['sort_by']
  pinned?: 'title' | 'actions'
}
const columns: TableColumn[] = [
  { key: 'title', label: '案例', width: 'auto', sortBy: 'title', pinned: 'title' },
  { key: 'category', label: '分类', width: '84px' },
  { key: 'priority', label: '优先级', width: '88px', sortBy: 'priority' },
  { key: 'status', label: '状态', width: '112px' },
  { key: 'product', label: '产品 / 版本', width: '148px' },
  { key: 'site', label: '局点', width: '112px' },
  { key: 'workspace', label: '工作区', width: '120px' },
  { key: 'creator', label: '创建人', width: '96px' },
  { key: 'created_at', label: '创建时间', width: '152px', sortBy: 'created_at' },
  { key: 'updated_at', label: '更新时间', width: '152px', sortBy: 'updated_at' },
  { key: 'promotion', label: '晋升状态', width: '112px' },
  { key: 'actions', label: '操作', width: '76px', pinned: 'actions' },
]
const canSelect = (item: CaseListItem) => item.status === 'APPROVED' && item.my_can_manage
  && (!props.promotionWorkspace || props.promotionWorkspace === item.workspace_id)
const selectablePage = computed(() => {
  const eligible = props.items.filter(canSelect)
  const workspace = props.promotionWorkspace || eligible[0]?.workspace_id
  return eligible.filter(item => item.workspace_id === workspace)
})
const allSelected = computed(() => selectablePage.value.length > 0
  && selectablePage.value.every(item => Boolean(props.selectedCases[item.id])))
const someSelected = computed(() => !allSelected.value
  && selectablePage.value.some(item => Boolean(props.selectedCases[item.id])))
const ariaSort = (field?: CaseSort['sort_by']) => {
  if (!field) return undefined
  if (props.sortBy !== field) return 'none'
  return props.sortOrder === 'asc' ? 'ascending' : 'descending'
}
const sortColumn = (field?: CaseSort['sort_by']) => {
  if (!field) return
  const initialOrder = field === 'priority' || field === 'title' ? 'asc' : 'desc'
  emit('sort', {
    sort_by: field,
    sort_order: props.sortBy === field ? (props.sortOrder === 'asc' ? 'desc' : 'asc') : initialOrder,
  })
}
const formatTime = (value?: string | null) => {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString()
}
</script>

<template>
  <div class="cc-list" :aria-busy="loading">
    <div class="cc-table-scroll" tabindex="0" role="region" aria-label="案例表格，可横向滚动">
      <table class="cc-table" aria-label="排查案例库">
        <colgroup>
          <col style="width: 44px" />
          <col v-for="column in columns" :key="column.key" :style="{ width: column.width }" />
        </colgroup>
        <thead>
          <tr>
            <th scope="col" class="selection-cell pinned-selection">
              <input
                type="checkbox"
                aria-label="选择本页可晋升案例"
                title="选择本页同一工作区中可晋升的案例"
                :checked="allSelected"
                :indeterminate="someSelected"
                :disabled="loading || selectablePage.length === 0"
                @change="emit('toggle-page', selectablePage)"
              />
            </th>
            <th
              v-for="column in columns"
              :key="column.key"
              scope="col"
              :class="column.pinned ? 'pinned-' + column.pinned : undefined"
              :aria-sort="ariaSort(column.sortBy)"
            >
              <button
                v-if="column.sortBy"
                type="button"
                class="sort-header"
                :class="{ active: sortBy === column.sortBy }"
                :aria-label="'按' + (column.label === '案例' ? '标题' : column.label) + '排序'"
                @click="sortColumn(column.sortBy)"
              >
                <span>{{ column.label }}</span>
                <span class="sort-arrows" aria-hidden="true">
                  <ChevronUp :size="12" :class="{ selected: sortBy === column.sortBy && sortOrder === 'asc' }" />
                  <ChevronDown :size="12" :class="{ selected: sortBy === column.sortBy && sortOrder === 'desc' }" />
                </span>
              </button>
              <span v-else>{{ column.label }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="items.length === 0">
            <td :colspan="columns.length + 1" class="empty-cell">
              <div class="cc-state" role="status">
                <Loader2 v-if="loading" :size="20" class="spin" />
                <BookMarked v-else :size="24" />
                <span>{{ loading ? t('common.loading') : error ? t('case_center.load_failed') : filtered ? '未找到匹配的案例，请调整筛选条件' : t('case_center.empty') }}</span>
              </div>
            </td>
          </tr>
          <tr v-for="item in items" :key="item.id" class="cc-row" :class="{ 'is-selected': selectedCases[item.id] }">
            <td class="selection-cell pinned-selection">
              <input
                type="checkbox"
                :aria-label="'选择案例：' + item.title"
                :title="!canSelect(item) ? '仅可选择同一工作区中有管理权限且已入库的案例晋升规程' : '选择案例'"
                :checked="Boolean(selectedCases[item.id])"
                :disabled="loading || !canSelect(item)"
                @change="emit('toggle', item.id, item.workspace_id)"
              />
            </td>
            <td class="pinned-title">
              <div class="case-title-cell">
                <button type="button" class="case-title-link" :title="item.title" @click="emit('open', item)">{{ item.title }}</button>
                <span v-if="item.problem_description" class="case-description ellipsis" :title="item.problem_description">{{ item.problem_description }}</span>
                <span v-if="item.source_task_name" class="case-source ellipsis" :title="item.source_task_name">来源任务：{{ item.source_task_name }}</span>
              </div>
            </td>
            <td><CaseCategoryTag :category="item.category" /></td>
            <td><CasePriorityTag :priority="item.priority" /></td>
            <td>
              <div class="stacked-cell">
                <CaseStatusPill :status="item.status" />
                <span v-if="item.review_round > 1" class="secondary-text">{{ t('case_center.review_round', { round: item.review_round }) }}</span>
              </div>
            </td>
            <td>
              <div class="stacked-cell">
                <span class="ellipsis" :title="item.product_name || undefined">{{ item.product_name || '-' }}</span>
                <span class="secondary-text ellipsis" :title="item.product_version || undefined">{{ item.product_version || '-' }}</span>
              </div>
            </td>
            <td><span class="ellipsis" :title="item.site_name || undefined">{{ item.site_name || '-' }}</span></td>
            <td><span class="ellipsis" :title="item.workspace_name || undefined">{{ item.workspace_name || '-' }}</span></td>
            <td><span class="ellipsis" :title="item.creator_name || undefined">{{ item.creator_name || '-' }}</span></td>
            <td class="time-cell">{{ formatTime(item.created_at) }}</td>
            <td class="time-cell">{{ formatTime(item.updated_at) }}</td>
            <td><span class="promotion-state" :class="{ promoted: item.has_playbook }">{{ item.has_playbook ? '已晋升规程' : '未晋升' }}</span></td>
            <td class="pinned-actions"><button type="button" class="detail-action" :aria-label="'查看案例：' + item.title" @click="emit('open', item)">详情</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="loading && items.length" class="cc-loading-overlay" role="status"><Loader2 :size="20" class="spin" /><span>{{ t('common.loading') }}</span></div>
  </div>
</template>

<style scoped>
.cc-list { position: relative; min-width: 0; border: 1px solid #e2e8f0; border-radius: 12px; background: #fff; overflow: hidden; }
.cc-table-scroll { overflow: auto; max-height: 65vh; scrollbar-gutter: stable; }
.cc-table-scroll:focus-visible { outline: 2px solid #0ea5e9; outline-offset: -2px; }
.cc-table { width: 100%; min-width: 1636px; table-layout: fixed; border-collapse: separate; border-spacing: 0; color: #334155; font-size: 0.8125rem; }
.cc-table th, .cc-table td { padding: 12px; text-align: left; vertical-align: middle; border-bottom: 1px solid #eef2f7; background: #fff; }
.cc-table th { position: sticky; top: 0; z-index: 3; height: 44px; padding-top: 8px; padding-bottom: 8px; color: #64748b; background: #f8fafc; font-size: 0.75rem; font-weight: 600; white-space: nowrap; }
.cc-table tr:last-child td { border-bottom: none; }
.cc-row:hover td { background: #f8fbff; }
.cc-row.is-selected td { background: #f0f9ff; }
.cc-table .pinned-selection { position: sticky; left: 0; z-index: 2; }
.cc-table .pinned-title { position: sticky; left: 44px; z-index: 2; box-shadow: 5px 0 7px -7px rgba(15, 23, 42, 0.3); }
.cc-table .pinned-actions { position: sticky; right: 0; z-index: 2; box-shadow: -5px 0 7px -7px rgba(15, 23, 42, 0.3); text-align: center; }
.cc-table th.pinned-selection, .cc-table th.pinned-title, .cc-table th.pinned-actions { z-index: 4; }
.cc-table .selection-cell { padding: 12px 14px; }
.case-title-cell, .stacked-cell { display: flex; flex-direction: column; align-items: flex-start; gap: 5px; min-width: 0; }
.case-title-link { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; padding: 0; border: none; background: none; color: #1e293b; font: inherit; font-weight: 600; line-height: 1.5; text-align: left; cursor: pointer; }
.case-title-link:hover, .detail-action:hover { color: #0284c7; }
.case-description, .case-source, .secondary-text { color: #64748b; font-size: 0.75rem; }
.ellipsis { display: block; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.case-description, .case-source { width: 100%; }
.time-cell { color: #64748b; font-size: 0.75rem; font-variant-numeric: tabular-nums; }
.promotion-state { color: #64748b; white-space: nowrap; font-size: 0.75rem; }
.promotion-state.promoted { color: #0369a1; background: #e0f2fe; border-radius: 6px; padding: 2px 6px; }
.detail-action { padding: 4px 0; border: none; background: transparent; color: #0284c7; font: inherit; font-size: 0.8125rem; cursor: pointer; }
.sort-header { display: inline-flex; align-items: center; gap: 6px; width: 100%; padding: 0; border: none; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; }
.sort-header:hover, .sort-header.active { color: #0284c7; }
.sort-arrows { display: flex; flex-direction: column; color: #cbd5e1; }
.sort-arrows svg + svg { margin-top: -4px; }
.sort-arrows .selected { color: #0284c7; }
.sort-header:focus-visible, .case-title-link:focus-visible, .detail-action:focus-visible { outline: 2px solid #0ea5e9; outline-offset: 3px; border-radius: 3px; }
.cc-table input[type="checkbox"] { appearance: none; -webkit-appearance: none; width: 16px; height: 16px; margin: 0; vertical-align: middle; border-radius: 4px; border: 1.5px solid #cbd5e1; background-color: #fff; background-repeat: no-repeat; background-position: center; background-size: 11px 11px; cursor: pointer; }
.cc-table input[type="checkbox"]:hover:not(:disabled) { border-color: #38bdf8; }
.cc-table input[type="checkbox"]:checked { border-color: #0ea5e9; background-color: #0ea5e9; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 14 14' fill='none'%3E%3Cpath d='M2.5 7L5.5 10L11.5 4' stroke='%23ffffff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E"); }
.cc-table input[type="checkbox"]:indeterminate { border-color: #0ea5e9; background-color: #0ea5e9; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 14 14' fill='none'%3E%3Cpath d='M3 7H11' stroke='%23ffffff' stroke-width='2' stroke-linecap='round'/%3E%3C/svg%3E"); }
.cc-table input[type="checkbox"]:focus-visible { outline: 2px solid #0ea5e9; outline-offset: 2px; }
.cc-table input[type="checkbox"]:disabled { opacity: 0.4; cursor: not-allowed; }
.empty-cell { height: 180px; }
.cc-state { position: absolute; top: 44px; left: 0; right: 0; display: flex; align-items: center; justify-content: center; gap: 10px; min-height: 156px; padding: 12px; color: #64748b; }
.cc-loading-overlay { position: absolute; inset: 0; z-index: 5; display: flex; align-items: center; justify-content: center; gap: 8px; background: rgba(255, 255, 255, 0.72); color: #64748b; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
@media (max-width: 900px) { .cc-table .pinned-title { position: static; box-shadow: none; } }
@media (max-width: 640px) { .cc-table .pinned-actions { position: static; box-shadow: none; } }
</style>
