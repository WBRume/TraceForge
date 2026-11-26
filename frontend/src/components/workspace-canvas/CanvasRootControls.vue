<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseSelect from '@/components/BaseSelect.vue'
import { TASK_STATUSES, taskStatusKey } from '@/utils/taskStatus'
import type { CanvasRootFilters, CanvasRootKind, FiscalQuarter } from './model'

const props = defineProps<{
  quarter: FiscalQuarter
  filters: CanvasRootFilters
  kinds: readonly CanvasRootKind[]
  next: boolean
  empty: boolean
  busy: boolean
  userId?: string
}>()
const emit = defineEmits<{ filter: [filters: CanvasRootFilters] }>()
const { t } = useI18n()
const kind = shallowRef<CanvasRootKind | ''>('')
const slice = shallowRef('')
const taskType = shallowRef('')
const status = shallowRef('')
const mine = shallowRef(false)
const query = shallowRef('')

watch(() => props.filters, filters => {
  kind.value = filters.kind ?? ''
  slice.value = filters.slice ?? ''
  taskType.value = filters.task_type ?? ''
  status.value = filters.status ?? ''
  mine.value = Boolean(filters.creator_id)
  query.value = filters.q ?? ''
}, { immediate: true })

const weeks = computed(() => {
  const day = 86_400_000
  const start = Date.parse(`${props.quarter.start}T00:00:00Z`)
  const end = Date.parse(`${props.quarter.end}T00:00:00Z`)
  return Array.from({ length: Math.floor((end - start) / (day * 7)) + 1 }, (_, index) => ({
    id: `W${index + 1}`, number: index + 1,
    start: new Date(start + day * 7 * index).toISOString().slice(5, 10),
    end: new Date(Math.min(end, start + day * (7 * index + 6))).toISOString().slice(5, 10),
  }))
})

const kindsOptions = computed(() => [
  { label: t('workspace_canvas.tree.all_roots'), value: '' },
  ...props.kinds.map(value => ({ label: t(`workspace_canvas.kind.${value}`), value })),
])
const timeOptions = computed(() => [
  { label: t('workspace_canvas.quarter.whole_branch'), value: '' },
  ...props.quarter.months.map(month => ({
    label: t('workspace_canvas.quarter.relative_month', { number: month.index }), value: month.id,
    detail: `${month.start.slice(5)} — ${month.end.slice(5)}`,
  })),
  ...weeks.value.map(week => ({
    label: t('workspace_canvas.quarter.relative_week', { number: week.number }), value: week.id,
    detail: `${week.start} — ${week.end}`,
  })),
])
const taskTypes = computed(() => [
  { label: t('workspace_canvas.quarter.all_task_types'), value: '' },
  { label: t('workspace_canvas.kind.task'), value: 'DEVELOPMENT' },
  { label: t('workspace_canvas.kind.diagnosis_task'), value: 'DIAGNOSIS' },
])
const taskStatuses = computed(() => [
  { label: t('workspace_canvas.quarter.all_statuses'), value: '' },
  ...TASK_STATUSES.map(value => ({ label: t(taskStatusKey(value)), value })),
])

function apply() {
  if (!kind.value) query.value = ''
  if (kind.value !== 'task') {
    taskType.value = ''
    status.value = ''
    mine.value = false
  }
  emit('filter', {
    kind: kind.value || undefined, slice: slice.value || undefined, task_type: taskType.value || undefined,
    status: status.value || undefined, creator_id: mine.value ? props.userId : undefined, q: query.value.trim() || undefined,
  })
}
</script>

<template>
  <div class="root-controls" role="group" data-testid="canvas-root-controls" :aria-label="t('workspace_canvas.tree.root_filter')">
    <BaseSelect v-model="kind" class="root-field" :options="kindsOptions" :disabled="busy"
      :aria-label="t('workspace_canvas.tree.root_filter')" @update:model-value="apply" />
    <BaseSelect v-model="slice" class="root-field" :options="timeOptions" :disabled="busy"
      :aria-label="t('workspace_canvas.quarter.time_filter')" @update:model-value="apply" />
    <template v-if="kind === 'task'">
      <BaseSelect v-model="taskType" class="root-field" :options="taskTypes" :disabled="busy"
        :aria-label="t('workspace_canvas.quarter.task_type')" @update:model-value="apply" />
      <BaseSelect v-model="status" class="root-field" :options="taskStatuses" :disabled="busy"
        :aria-label="t('workspace_canvas.quarter.task_status')" @update:model-value="apply" />
      <el-checkbox v-if="userId" v-model="mine" :disabled="busy" @change="apply">{{ t('workspace_canvas.quarter.my_tasks') }}</el-checkbox>
    </template>
    <el-input v-if="kind" v-model="query" class="root-query" :disabled="busy" clearable maxlength="120"
      :aria-label="t('workspace_canvas.tree.title_filter')" :placeholder="t('workspace_canvas.tree.title_filter')"
      @change="apply" @keyup.enter="apply" />
    <span v-if="empty && !busy" class="root-empty" role="status">{{ t(next ? 'workspace_canvas.tree.no_roots_yet' : 'workspace_canvas.tree.no_roots') }}</span>
  </div>
</template>

<style scoped>
.root-controls { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; min-width: 0; }
.root-field { width: 144px; max-width: 100%; }
.root-query { width: 184px; max-width: 100%; }
.root-empty { color: #64748b; font-size: 12px; }
</style>
