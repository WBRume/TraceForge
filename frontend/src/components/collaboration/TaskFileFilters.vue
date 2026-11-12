<script setup lang="ts">
import { useI18n } from 'vue-i18n'

defineProps<{
  counts: Record<'all' | 'reports' | 'code', number>
  checked: boolean
  partial: boolean
  canSelect: boolean
}>()
const filter = defineModel<'all' | 'reports' | 'code'>({ required: true })
const emit = defineEmits<{ selectAll: [checked: boolean] }>()
const { t } = useI18n()
const categories = ['all', 'reports', 'code'] as const
</script>

<template>
  <div class="task-file-filters">
    <nav :aria-label="t('task_deliverables.category')">
      <button v-for="category in categories" :key="category" type="button" :aria-pressed="filter === category" @click="filter = category">
        {{ t(`task_deliverables.${category}`) }} <small>{{ counts[category] }}</small>
      </button>
    </nav>
    <label v-if="canSelect" class="select-files">
      <input type="checkbox" :checked="checked" :indeterminate="partial" @change="emit('selectAll', ($event.target as HTMLInputElement).checked)">
      {{ t('task_deliverables.select_all') }}
    </label>
  </div>
</template>

<style scoped>
.task-file-filters { display: grid; gap: 7px; flex: none; }
.task-file-filters nav { display: grid; grid-template-columns: repeat(3, 1fr); gap: 2px; padding: 3px; background: #edf2f7; border-radius: 7px; }
.task-file-filters button { padding: 5px 2px; min-width: 0; border: 0; border-radius: 5px; background: transparent; color: #475569; font-size: 11px; white-space: nowrap; cursor: pointer; }
.task-file-filters button[aria-pressed="true"] { background: #fff; color: #0369a1; font-weight: 600; box-shadow: 0 1px 3px #0f172a14; }
.task-file-filters small { color: #64748b; font-size: 10px; }
.select-files { display: flex; align-items: center; gap: 6px; padding: 1px 3px; color: #475569; font-size: 11px; }
.select-files input { accent-color: #0284c7; }
</style>
