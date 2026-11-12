<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Download } from '@/components/icons'
import FileTypeBadge from '@/components/file-preview/FileTypeBadge.vue'
import { formatFileSize } from '@/components/file-preview/fileTypes'

defineProps<{ path: string; size?: number; pending: boolean; removed?: boolean }>()
const emit = defineEmits<{ download: [] }>()
const { t } = useI18n()
</script>

<template>
  <header class="task-preview-bar">
    <FileTypeBadge :path="path" />
    <strong :title="path">{{ path.split('/').at(-1) }}</strong>
    <small v-if="size !== undefined">{{ formatFileSize(size) }}</small>
    <small v-if="removed">{{ t('task_deliverables.removed') }}</small>
    <button type="button" class="btn-primary btn-xs" :disabled="pending || size === undefined" @click="emit('download')">
      <Download :size="14" />{{ t(removed ? 'task_deliverables.export_previous' : 'task_deliverables.export_current') }}
    </button>
  </header>
</template>

<style scoped>
.task-preview-bar { display: flex; flex: none; align-items: center; gap: 7px; min-height: 38px; padding: 5px 12px; background: #fff; border-bottom: 1px solid #e2e8f0; color: #0f172a; font-size: 12px; }
.task-preview-bar strong { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-preview-bar small { flex: none; color: #64748b; }
.task-preview-bar button { display: inline-flex; align-items: center; gap: 5px; flex: none; white-space: nowrap; }
@media (max-width: 440px) { .task-preview-bar small { display: none; } }
</style>
