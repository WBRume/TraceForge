<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useTaskInspection } from '@/composables/useTaskInspection'
import TaskRepositoryDetails from './TaskRepositoryDetails.vue'

const props = withDefaults(defineProps<{
  workspaceId: string
  taskId: string
  showDescription?: boolean
}>(), { showDescription: true })
const { t } = useI18n()
const { detail, loading, failed, reload } = useTaskInspection(() => props.workspaceId, () => props.taskId)
</script>

<template>
  <section class="task-detail-panel" :aria-busy="loading">
    <p v-if="loading" class="detail-status" role="status">{{ t('task_inspection.loading') }}</p>
    <div v-else-if="failed" class="detail-status" role="alert">
      <span>{{ t('task_inspection.load_failed') }}</span>
      <button type="button" class="retry-button" @click="reload">{{ t('task_inspection.retry') }}</button>
    </div>
    <template v-else-if="detail">
      <div class="task-basics">
        <h3 v-if="showDescription" class="task-name">{{ detail.task.name }}</h3>
        <p v-if="showDescription && detail.task.description" class="task-description">{{ detail.task.description }}</p>
        <dl class="task-fields">
          <div><dt>{{ t('task_inspection.task_id') }}</dt><dd>{{ detail.task.id }}</dd></div>
          <div><dt>{{ t('task_inspection.status') }}</dt><dd>{{ detail.task.status }}</dd></div>
          <div><dt>{{ t('task_inspection.creator') }}</dt><dd>{{ detail.task.creator_name || detail.task.creator_id }}</dd></div>
          <div><dt>{{ t('task_inspection.created_at') }}</dt><dd>{{ detail.task.created_at }}</dd></div>
          <div><dt>{{ t('task_inspection.execution_location') }}</dt><dd>{{ t(detail.task.execution_location === 'LOCAL' ? 'task_inspection.local' : 'task_inspection.server') }}</dd></div>
          <div class="full-width"><dt>{{ t('task_inspection.task_path') }}</dt><dd>{{ detail.project_path || t('task_inspection.not_recorded') }}</dd></div>
        </dl>
      </div>
      <TaskRepositoryDetails :repositories="detail.repositories" />
    </template>
  </section>
</template>

<style scoped>
.task-detail-panel { min-width: 0; color: var(--color-text-main, #1e293b); }
.task-basics { margin-bottom: 24px; }
.task-name { margin: 0 0 8px; font-size: 16px; overflow-wrap: anywhere; }
.task-description { margin: 0 0 16px; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 13px; line-height: 1.6; }
.task-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 24px; margin: 0; font-size: 12px; line-height: 1.6; }
.task-fields dt { color: var(--color-text-muted, #64748b); margin-bottom: 3px; }
.task-fields dd { margin: 0; overflow-wrap: anywhere; user-select: text; }
.full-width { grid-column: 1 / -1; }
.detail-status { min-height: 100px; display: flex; align-items: center; justify-content: center; gap: 12px; color: #64748b; font-size: 13px; }
.retry-button { padding: 5px 12px; border: 1px solid #cbd5e1; border-radius: 6px; background: white; cursor: pointer; }
@media (max-width: 560px) { .task-fields { grid-template-columns: minmax(0, 1fr); } }
</style>
