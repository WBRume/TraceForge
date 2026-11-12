<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { FileArchive, Loader2 } from '@/components/icons'

defineProps<{ count: number; pending: boolean }>()
const emit = defineEmits<{ download: [] }>()
const { t } = useI18n()
</script>

<template>
  <Transition name="batch">
    <footer v-if="count" class="batch-export">
      <span role="status">{{ t('task_deliverables.selected', { count }) }}</span>
      <button type="button" class="btn-primary btn-xs" :disabled="pending" @click="emit('download')">
        <Loader2 v-if="pending" :size="14" class="spin" /><FileArchive v-else :size="14" />
        {{ t('task_deliverables.export_zip') }}
      </button>
    </footer>
  </Transition>
</template>

<style scoped>
.batch-export { display: flex; flex: none; align-items: center; justify-content: space-between; gap: 8px; padding: 8px; border: 1px solid #dbeafe; border-radius: 8px; background: #ffffffeb; box-shadow: 0 4px 14px #0c4a6e13; color: #334155; font-size: 11px; backdrop-filter: blur(8px); }
.batch-export button { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
.batch-enter-active, .batch-leave-active { transition: opacity .18s ease, transform .18s ease; }
.batch-enter-from, .batch-leave-to { opacity: 0; transform: translateY(7px); }
@media (prefers-reduced-motion: reduce) { .batch-enter-active, .batch-leave-active { transition: none; } }
</style>
