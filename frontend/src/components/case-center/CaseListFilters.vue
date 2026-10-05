<script setup lang="ts">
import { computed, reactive, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDown, RefreshCw, Search } from '@/components/icons'
import BaseSelect from '@/components/BaseSelect.vue'
import type { CaseListFilters } from '@/types/caseCenter'
import { createCaseListFilters } from '@/types/caseCenter'

const props = defineProps<{
  modelValue: CaseListFilters
  workspaceId: string
  workspaceOptions: { label: string; value: string }[]
  loading: boolean
}>()
const emit = defineEmits<{
  apply: [filters: CaseListFilters]
  'update:workspaceId': [workspaceId: string]
  refresh: []
}>()
const { t } = useI18n()
const draft = reactive({ ...props.modelValue })
const advancedOpen = shallowRef(false)
const criteriaKeys = Object.keys(createCaseListFilters()).filter(key => !key.startsWith('sort_')) as (keyof CaseListFilters)[]
watch(
  () => criteriaKeys.map(key => props.modelValue[key]),
  () => Object.assign(draft, Object.fromEntries(criteriaKeys.map(key => [key, props.modelValue[key]]))),
)

const statusOptions = computed(() => ['ALL', 'TECHNICALLY_VERIFIED', 'DRAFT', 'PENDING_REVIEW', 'IN_REVIEW', 'APPROVED', 'REJECTED'].map(value => ({
  value, label: value === 'ALL' ? t('case_center.status_all') : value === 'TECHNICALLY_VERIFIED' ? '物理验证归档' : t(`case_center.status.${value}`),
})))
const categoryOptions = computed(() => ['ALL', 'PUBLIC', 'PRODUCT', 'SITE', 'TEMPORARY'].map(value => ({
  value, label: value === 'ALL' ? '全部分类' : t(`case_center.category.${value}`),
})))
const priorityOptions = ['ALL', 'P0', 'P1', 'P2', 'P3'].map(value => ({ value, label: value === 'ALL' ? '全部优先级' : value }))
const promotionOptions = [{ value: 'ALL', label: '全部' }, { value: 'true', label: '已晋升规程' }, { value: 'false', label: '未晋升规程' }]
const textFields = [
  { key: 'product_name', label: '产品', placeholder: '输入产品名称' },
  { key: 'product_version', label: '版本', placeholder: '输入版本号' },
  { key: 'site_name', label: '局点', placeholder: '输入局点名称' },
  { key: 'creator_name', label: '创建人', placeholder: '输入创建人姓名' },
] as const
const advancedCount = computed(() => textFields.filter(field => draft[field.key].trim()).length
  + Number(Boolean(draft.created_from || draft.created_to)) + Number(draft.has_playbook !== 'ALL'))
const dateError = computed(() => draft.created_from && draft.created_to && draft.created_from > draft.created_to
  ? '开始日期不能晚于结束日期' : '')
const submit = () => {
  if (!dateError.value) emit('apply', {
    ...draft,
    sort_by: props.modelValue.sort_by,
    sort_order: props.modelValue.sort_order,
  })
}
const reset = () => {
  const defaults = createCaseListFilters()
  Object.assign(draft, defaults)
  emit('apply', defaults)
}
</script>

<template>
  <form class="case-filters" aria-label="案例检索" @submit.prevent="submit">
    <div class="filter-toolbar">
      <div class="search-box">
        <Search :size="16" class="search-icon" />
        <input v-model="draft.keyword" type="search" class="search-input" aria-label="案例关键词" :placeholder="t('case_center.search_placeholder')" />
      </div>
      <button type="submit" class="btn-primary" :disabled="Boolean(dateError)">{{ t('case_center.search') }}</button>
      <button type="button" class="btn-secondary" @click="reset">重置</button>
      <button type="button" class="advanced-toggle" :aria-expanded="advancedOpen" aria-controls="case-advanced-filters" @click="advancedOpen = !advancedOpen">
        高级筛选<span v-if="advancedCount" class="filter-count">{{ advancedCount }}</span>
        <ChevronDown :size="14" :class="{ rotated: advancedOpen }" />
      </button>
      <button type="button" class="refresh-btn" :disabled="loading" :title="t('common.refresh')" aria-label="刷新案例" @click="emit('refresh')"><RefreshCw :size="16" :class="{ spin: loading }" /></button>
    </div>
    <div class="quick-filters">
      <div v-if="workspaceOptions.length" class="filter-field workspace-field">
        <span class="filter-label">工作区</span>
        <BaseSelect :model-value="workspaceId" :options="workspaceOptions" searchable aria-label="工作区" @update:model-value="emit('update:workspaceId', String($event || ''))" />
      </div>
      <div class="filter-field"><span class="filter-label">状态</span><BaseSelect v-model="draft.status" :options="statusOptions" aria-label="状态" @update:model-value="submit" /></div>
      <div class="filter-field"><span class="filter-label">分类</span><BaseSelect v-model="draft.category" :options="categoryOptions" aria-label="分类" @update:model-value="submit" /></div>
      <div class="filter-field"><span class="filter-label">优先级</span><BaseSelect v-model="draft.priority" :options="priorityOptions" aria-label="优先级" @update:model-value="submit" /></div>
    </div>
    <div v-show="advancedOpen" id="case-advanced-filters" class="advanced-filters">
      <label v-for="field in textFields" :key="field.key" class="filter-field">
        <span class="filter-label">{{ field.label }}</span>
        <input v-model="draft[field.key]" type="text" class="filter-input" :placeholder="field.placeholder" />
      </label>
      <label class="filter-field"><span class="filter-label">创建开始日期</span><input v-model="draft.created_from" type="date" class="filter-input" :max="draft.created_to || undefined" /></label>
      <label class="filter-field"><span class="filter-label">创建结束日期</span><input v-model="draft.created_to" type="date" class="filter-input" :min="draft.created_from || undefined" /></label>
      <div class="filter-field"><span class="filter-label">晋升状态</span><BaseSelect v-model="draft.has_playbook" :options="promotionOptions" aria-label="晋升状态" /></div>
      <div class="advanced-actions"><button type="submit" class="btn-primary" :disabled="Boolean(dateError)">应用筛选</button></div>
    </div>
    <p v-if="dateError" class="filter-error" role="alert">{{ dateError }}</p>
  </form>
</template>

<style scoped>
.case-filters { display: flex; flex-direction: column; gap: 14px; padding: 14px 16px; background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; }
.filter-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.search-box { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 220px; border: 1px solid #e2e8f0; border-radius: 8px; padding: 0 12px; background: #fff; }
.search-box:focus-within { border-color: #0ea5e9; box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.1); }
.search-icon { color: #94a3b8; flex-shrink: 0; }
.search-input { width: 100%; min-width: 0; height: 40px; border: none; outline: none; font: inherit; font-size: 0.85rem; background: transparent; }
.quick-filters, .advanced-filters { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }
.advanced-filters { padding-top: 14px; border-top: 1px solid #f1f5f9; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
.filter-field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.filter-label { color: #64748b; font-size: 0.75rem; font-weight: 500; }
.filter-input { width: 100%; min-width: 0; height: 42px; padding: 0 12px; border: 1px solid #e2e8f0; border-radius: 8px; font: inherit; font-size: 0.85rem; color: #0f172a; background: #fff; outline: none; }
.filter-input:focus { border-color: #0ea5e9; box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.1); }
.filter-input::placeholder { color: #94a3b8; }
.advanced-toggle, .refresh-btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: none; background: transparent; color: #64748b; cursor: pointer; font: inherit; font-size: 0.85rem; }
.advanced-toggle:hover, .refresh-btn:hover { color: #0284c7; }
.advanced-toggle svg { transition: transform 0.2s; }
.rotated { transform: rotate(180deg); }
.filter-count { padding: 1px 6px; border-radius: 999px; color: #0284c7; background: #e0f2fe; font-size: 0.75rem; }
.refresh-btn { width: 36px; height: 36px; flex-shrink: 0; }
.refresh-btn:disabled { opacity: 0.5; cursor: wait; }
.advanced-actions { display: flex; align-items: flex-end; }
.filter-error { margin: 0; color: #dc2626; font-size: 0.8rem; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) { .search-box { flex-basis: 100%; min-width: 0; } }
@media (max-width: 640px) { .quick-filters, .advanced-filters { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
