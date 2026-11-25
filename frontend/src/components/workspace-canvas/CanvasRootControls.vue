<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronLeft, ChevronRight } from '@/components/icons'
import { TASK_STATUSES, taskStatusKey } from '@/utils/taskStatus'
import type { CanvasRootFilters, CanvasRootKind, FiscalQuarter } from './model'

const props = defineProps<{
  quarter: FiscalQuarter
  filters: CanvasRootFilters
  kinds: readonly CanvasRootKind[]
  next: boolean
  previous: boolean
  empty: boolean
  busy: boolean
  userId?: string
}>()
const emit = defineEmits<{ filter: [filters: CanvasRootFilters]; next: []; previous: [] }>()
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
  <nav class="root-controls" data-testid="canvas-root-controls" :aria-label="t('workspace_canvas.tree.root_filter')">
    <select v-model="kind" :disabled="busy" :aria-label="t('workspace_canvas.tree.root_filter')" @change="apply">
      <option value="">{{ t('workspace_canvas.tree.all_roots') }}</option>
      <option v-for="item in kinds" :key="item" :value="item">{{ t(`workspace_canvas.kind.${item}`) }}</option>
    </select>
    <select v-model="slice" :disabled="busy" :aria-label="t('workspace_canvas.quarter.time_filter')" @change="apply">
      <option value="">{{ t('workspace_canvas.quarter.whole_branch') }}</option>
      <optgroup :label="t('workspace_canvas.quarter.months')">
        <option v-for="month in quarter.months" :key="month.id" :value="month.id">
          {{ t('workspace_canvas.quarter.relative_month', { number: month.index }) }} ({{ month.start.slice(5) }} — {{ month.end.slice(5) }})
        </option>
      </optgroup>
      <optgroup :label="t('workspace_canvas.quarter.weeks')">
        <option v-for="week in weeks" :key="week.id" :value="week.id">
          {{ t('workspace_canvas.quarter.relative_week', { number: week.number }) }} ({{ week.start }} — {{ week.end }})
        </option>
      </optgroup>
    </select>
    <template v-if="kind === 'task'">
      <select v-model="taskType" :disabled="busy" :aria-label="t('workspace_canvas.quarter.task_type')" @change="apply">
        <option value="">{{ t('workspace_canvas.quarter.all_task_types') }}</option>
        <option value="DEVELOPMENT">{{ t('workspace_canvas.kind.task') }}</option>
        <option value="DIAGNOSIS">{{ t('workspace_canvas.kind.diagnosis_task') }}</option>
      </select>
      <select v-model="status" :disabled="busy" :aria-label="t('workspace_canvas.quarter.task_status')" @change="apply">
        <option value="">{{ t('workspace_canvas.quarter.all_statuses') }}</option>
        <option v-for="item in TASK_STATUSES" :key="item" :value="item">{{ t(taskStatusKey(item)) }}</option>
      </select>
      <label v-if="userId"><input v-model="mine" :disabled="busy" type="checkbox" @change="apply" />
        {{ t('workspace_canvas.quarter.my_tasks') }}</label>
    </template>
    <input v-if="kind" v-model="query" :disabled="busy" type="search" maxlength="120"
      :aria-label="t('workspace_canvas.tree.title_filter')" :placeholder="t('workspace_canvas.tree.title_filter')"
      @change="apply" @keydown.enter.prevent="apply" />
    <button v-if="previous" :disabled="busy" type="button" @click="emit('previous')">
      <ChevronLeft :size="14" />{{ t('workspace_canvas.tree.previous_roots') }}
    </button>
    <button v-if="next" :disabled="busy" type="button" @click="emit('next')">
      {{ t('workspace_canvas.tree.next_roots') }}<ChevronRight :size="14" />
    </button>
    <span v-if="empty && !busy" class="root-empty" role="status">{{ t(next ? 'workspace_canvas.tree.no_roots_yet' : 'workspace_canvas.tree.no_roots') }}</span>
  </nav>
</template>

<style scoped>
.root-controls { display: flex; align-items: center; flex-wrap: wrap; gap: 5px; color: #47627b; font-size: 12px; }
.root-controls :is(select, button, input[type='search']) { min-height: 30px; border: 1px solid #dbe7f2; border-radius: 7px;
  padding: 4px 7px; background: #f8fbfe; color: #355a77; font: inherit; }
.root-controls :is(button, label) { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }
.root-controls button { cursor: pointer; }
.root-controls input[type='search'] { width: 122px; }
.root-controls button:disabled { opacity: .55; cursor: default; }
.root-empty { margin-inline-start: 4px; color: #596d81; }
</style>
