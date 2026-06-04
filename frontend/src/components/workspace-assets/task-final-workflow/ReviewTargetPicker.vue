<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { Search, X } from 'lucide-vue-next'
import type { ReviewTarget, ReviewTargetRef, ReviewTargetType } from '@/types/workspaceAssets'

const props = defineProps<{
  modelValue: ReviewTargetRef[]
  targets: Record<ReviewTargetType, ReviewTarget[]>
}>()

const emit = defineEmits<{
  'update:modelValue': [value: ReviewTargetRef[]]
}>()

const targetTypes: ReviewTargetType[] = [
  'SPEC',
  'PLAN',
  'AI_CHANGE',
  'HUMAN_DELTA',
  'EVIDENCE',
  'DECISION',
  'TASK_FILE',
]

const { t } = useI18n()
const baseKey = 'workspace_assets.task_detail.final_workflow'
const activeType = shallowRef<ReviewTargetType>('SPEC')
const query = shallowRef('')

const targetLookup = computed(() => {
  const map = new Map<string, ReviewTarget>()
  for (const type of targetTypes) {
    for (const item of props.targets?.[type] ?? []) {
      map.set(toKey(item), item)
    }
  }
  return map
})

const selectedKeys = computed(() => new Set(props.modelValue.map((item) => toKey(item))))

const activeItems = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  const items = props.targets?.[activeType.value] ?? []
  if (!keyword) return items
  return items.filter((item) =>
    [item.label, item.status, item.subtitle, item.target_id]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(keyword)),
  )
})

const selectedTargets = computed(() =>
  props.modelValue.map((ref) => {
    const hydrated = targetLookup.value.get(toKey(ref))
    return {
      target_type: ref.target_type,
      target_id: ref.target_id,
      label: hydrated?.label ?? ref.label ?? ref.target_id,
      status: hydrated?.status ?? null,
      subtitle: hydrated?.subtitle ?? null,
      source_ref: hydrated?.source_ref ?? ref.source_ref ?? null,
    }
  }),
)

function toKey(item: Pick<ReviewTargetRef, 'target_type' | 'target_id'>) {
  return `${item.target_type}:${item.target_id}`
}

function toRef(item: ReviewTarget): ReviewTargetRef {
  return {
    target_type: item.target_type,
    target_id: item.target_id,
    label: item.label,
    source_ref: item.source_ref ?? null,
  }
}

function selectType(type: ReviewTargetType) {
  activeType.value = type
  query.value = ''
}

function toggleTarget(item: ReviewTarget) {
  const key = toKey(item)
  const next = props.modelValue.filter((ref) => toKey(ref) !== key)
  if (!selectedKeys.value.has(key)) {
    next.push(toRef(item))
  }
  emit('update:modelValue', next)
}

function removeTarget(ref: ReviewTargetRef) {
  const key = toKey(ref)
  emit('update:modelValue', props.modelValue.filter((item) => toKey(item) !== key))
}

function targetTypeLabel(type: ReviewTargetType) {
  return t(`${baseKey}.target_types.${type.toLowerCase()}`)
}
</script>

<template>
  <div class="target-picker">
    <div class="type-tabs" role="tablist" :aria-label="t(`${baseKey}.target_picker.type_tabs_label`)">
      <button
        v-for="type in targetTypes"
        :key="type"
        type="button"
        class="type-tab"
        :class="{ 'is-active': activeType === type }"
        @click="selectType(type)"
      >
        <span>{{ targetTypeLabel(type) }}</span>
        <small>{{ targets?.[type]?.length ?? 0 }}</small>
      </button>
    </div>

    <div class="picker-body">
      <section class="candidate-panel">
        <div class="candidate-toolbar">
          <div>
            <strong>{{ targetTypeLabel(activeType) }}</strong>
            <span>{{ t(`${baseKey}.target_picker.current_type_hint`) }}</span>
          </div>
          <el-input
            v-model="query"
            class="target-search"
            clearable
            :placeholder="t(`${baseKey}.target_picker.search_placeholder`)"
          >
            <template #prefix>
              <Search class="search-icon" />
            </template>
          </el-input>
        </div>

        <div v-if="activeItems.length" class="candidate-list">
          <button
            v-for="item in activeItems"
            :key="toKey(item)"
            type="button"
            class="candidate-item"
            :class="{ 'is-selected': selectedKeys.has(toKey(item)) }"
            @click="toggleTarget(item)"
          >
            <span class="candidate-check">
              {{ selectedKeys.has(toKey(item)) ? t(`${baseKey}.target_picker.selected`) : t(`${baseKey}.target_picker.select`) }}
            </span>
            <span class="candidate-main">
              <strong>{{ item.label }}</strong>
              <small>
                <span v-if="item.status">{{ item.status }}</span>
                <span v-if="item.subtitle">{{ item.subtitle }}</span>
                <span>{{ item.target_id }}</span>
              </small>
            </span>
          </button>
        </div>
        <div v-else class="empty-candidates">{{ t(`${baseKey}.target_picker.empty_candidates`) }}</div>
      </section>

      <aside class="selected-panel">
        <div class="selected-heading">
          <strong>{{ t(`${baseKey}.target_picker.selected_title`) }}</strong>
          <span>{{ selectedTargets.length }}</span>
        </div>
        <div v-if="selectedTargets.length" class="selected-list">
          <div v-for="item in selectedTargets" :key="toKey(item)" class="selected-item">
            <span>
              <strong>{{ targetTypeLabel(item.target_type) }}</strong>
              {{ item.label }}
            </span>
            <button type="button" class="remove-target" @click="removeTarget(item)">
              <X class="remove-icon" />
            </button>
          </div>
        </div>
        <p v-else class="empty-selected">{{ t(`${baseKey}.target_picker.empty_selected`) }}</p>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.target-picker {
  display: flex;
  width: 100%;
  flex-direction: column;
  gap: 12px;
}

.type-tabs {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding-bottom: 2px;
}

.type-tab {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  padding: 6px 10px;
  border: 1px solid #dbe4ee;
  border-radius: 8px;
  background: #ffffff;
  color: #475569;
  cursor: pointer;
  font-size: 0.78rem;
  font-weight: 700;
  white-space: nowrap;
}

.type-tab small {
  color: #94a3b8;
  font-size: 0.68rem;
}

.type-tab.is-active {
  border-color: #2563eb;
  background: #eff6ff;
  color: #1d4ed8;
}

.picker-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 360px;
}

.candidate-panel,
.selected-panel {
  min-width: 0;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #ffffff;
}

.candidate-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border-bottom: 1px solid #e2e8f0;
}

.candidate-toolbar strong,
.selected-heading strong {
  display: block;
  color: #0f172a;
  font-size: 0.84rem;
}

.candidate-toolbar span {
  display: block;
  margin-top: 3px;
  color: #64748b;
  font-size: 0.74rem;
}

.target-search {
  max-width: 240px;
}

.search-icon {
  width: 14px;
  height: 14px;
}

.candidate-list {
  display: flex;
  max-height: 300px;
  flex-direction: column;
  overflow: auto;
}

.candidate-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  width: 100%;
  padding: 11px 12px;
  border: 0;
  border-bottom: 1px solid #f1f5f9;
  background: transparent;
  color: #0f172a;
  cursor: pointer;
  text-align: left;
}

.candidate-item:hover,
.candidate-item.is-selected {
  background: #f8fafc;
}

.candidate-check {
  flex: 0 0 auto;
  min-width: 42px;
  padding: 3px 7px;
  border: 1px solid #dbe4ee;
  border-radius: 999px;
  color: #64748b;
  font-size: 0.68rem;
  font-weight: 800;
  text-align: center;
}

.candidate-item.is-selected .candidate-check {
  border-color: #bfdbfe;
  background: #dbeafe;
  color: #1d4ed8;
}

.candidate-main {
  display: block;
  min-width: 0;
}

.candidate-main strong,
.candidate-main small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.candidate-main strong {
  color: #0f172a;
  font-size: 0.82rem;
}

.candidate-main small {
  margin-top: 3px;
  color: #64748b;
  font-size: 0.72rem;
}

.candidate-main small span + span::before {
  content: " / ";
}

.selected-panel {
  display: flex;
  flex-direction: column;
  position: sticky;
  bottom: 0;
  z-index: 1;
}

.selected-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px;
  border-bottom: 1px solid #e2e8f0;
}

.selected-heading span {
  color: #64748b;
  font-size: 0.78rem;
  font-weight: 800;
}

.selected-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px;
}

.selected-item {
  display: flex;
  flex: 1 1 220px;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  padding: 9px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  color: #334155;
  font-size: 0.78rem;
  line-height: 1.35;
}

.selected-item strong {
  display: block;
  margin-bottom: 2px;
  color: #0f172a;
  font-size: 0.72rem;
}

.remove-target {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #64748b;
  cursor: pointer;
}

.remove-target:hover {
  background: #e2e8f0;
  color: #0f172a;
}

.remove-icon {
  width: 14px;
  height: 14px;
}

.empty-candidates,
.empty-selected {
  padding: 16px;
  color: #94a3b8;
  font-size: 0.8rem;
}

@media (max-width: 820px) {
  .candidate-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .target-search {
    max-width: none;
  }
}
</style>
