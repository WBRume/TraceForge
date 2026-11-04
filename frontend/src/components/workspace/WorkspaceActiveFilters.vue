<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { X } from '@/components/icons'
import type { ActiveWorkspaceFilter, WorkspaceFilterKey, WorkspaceFilterOption } from '@/composables/useWorkspaceFilters'

/**
 * 已生效高级过滤条件的标签列表：逐个移除或整体重置，避免过滤生效后无从查看。
 */
const props = defineProps<{
  activeFilters: ActiveWorkspaceFilter[]
  projectOptions: WorkspaceFilterOption[]
  productOptions: WorkspaceFilterOption[]
  repositoryOptions: WorkspaceFilterOption[]
  ownerOptions: WorkspaceFilterOption[]
}>()

const emit = defineEmits<{
  clear: [key: WorkspaceFilterKey, value?: string]
  reset: []
}>()

const { t } = useI18n()

const FIELD_LABEL_KEYS: Record<Exclude<WorkspaceFilterKey, 'onlyMine'>, string> = {
  project: 'workspaces.filters.project',
  product: 'workspaces.filters.product',
  repository: 'workspaces.filters.repository',
  owner: 'workspaces.filters.owner',
  createdWithin: 'workspaces.filters.created',
}

const RANGE_LABEL_KEYS: Record<string, string> = {
  '7D': 'workspaces.filters.created_7d',
  '30D': 'workspaces.filters.created_30d',
  '90D': 'workspaces.filters.created_90d',
}

const optionSets = computed<Record<string, WorkspaceFilterOption[]>>(() => ({
  project: props.projectOptions,
  product: props.productOptions,
  repository: props.repositoryOptions,
  owner: props.ownerOptions,
}))

const valueLabel = (filter: ActiveWorkspaceFilter) => {
  if (filter.key === 'createdWithin') return t(RANGE_LABEL_KEYS[filter.value] || 'workspaces.filters.created_all')
  return optionSets.value[filter.key]?.find((option) => option.value === filter.value)?.label || filter.value
}

const chips = computed(() => props.activeFilters.map((filter) => {
  if (filter.key === 'onlyMine') {
    const label = t('workspaces.filters.only_mine')
    return { key: `${filter.key}-${filter.value}`, filter, field: '', label }
  }
  return {
    key: `${filter.key}-${filter.value}`,
    filter,
    field: t(FIELD_LABEL_KEYS[filter.key]),
    label: valueLabel(filter),
  }
}))
</script>

<template>
  <div class="ws-active-filters" role="group" :aria-label="t('workspaces.filters.active_label')">
    <span class="ws-active-filters-label">{{ t('workspaces.filters.active_label') }}</span>
    <button
      v-for="chip in chips"
      :key="chip.key"
      type="button"
      class="ws-active-chip"
      :title="t('workspaces.filters.remove_chip', { label: `${chip.field} ${chip.label}`.trim() })"
      :aria-label="t('workspaces.filters.remove_chip', { label: `${chip.field} ${chip.label}`.trim() })"
      @click="emit('clear', chip.filter.key, chip.filter.value)"
    >
      <span class="ws-active-chip-field" v-if="chip.field">{{ chip.field }}</span>
      <span class="ws-active-chip-label">{{ chip.label }}</span>
      <X class="ws-active-chip-icon" aria-hidden="true" />
    </button>
    <button type="button" class="ws-active-reset" @click="emit('reset')">
      {{ t('workspaces.filters.reset') }}
    </button>
  </div>
</template>

<style scoped>
.ws-active-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 0.875rem;
}

.ws-active-filters-label {
  margin-right: 2px;
  color: #94a3b8;
  font-size: 0.72rem;
}

.ws-active-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: 240px;
  height: 24px;
  padding: 0 6px 0 8px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  color: #334155;
  background: #ffffff;
  font: inherit;
  font-size: 0.72rem;
  cursor: pointer;
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.ws-active-chip:hover {
  border-color: #cbd5e1;
  background: #f8fafc;
}

.ws-active-chip:focus-visible,
.ws-active-reset:focus-visible {
  outline: 2px solid var(--color-primary-500, #0ea5e9);
  outline-offset: 2px;
}

.ws-active-chip-field {
  flex-shrink: 0;
  color: #94a3b8;
}

.ws-active-chip-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}

.ws-active-chip-icon {
  width: 11px;
  height: 11px;
  flex-shrink: 0;
  color: #94a3b8;
  transition: color 0.15s ease;
}

.ws-active-chip:hover .ws-active-chip-icon {
  color: #ef4444;
}

.ws-active-reset {
  padding: 2px 6px;
  border: 0;
  border-radius: 6px;
  color: #64748b;
  background: transparent;
  font: inherit;
  font-size: 0.72rem;
  cursor: pointer;
}

.ws-active-reset:hover {
  color: #1e293b;
  background: #f1f5f9;
}
</style>
