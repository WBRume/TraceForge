<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import TaskDetailPanel from './TaskDetailPanel.vue'

defineProps<{ workspaceId: string; taskId: string }>()
const open = defineModel<boolean>({ default: false })
const { t } = useI18n()
</script>

<template>
  <el-dialog v-model="open" :title="t('task_inspection.title')" width="min(780px, calc(100vw - 32px))" top="6vh" append-to-body destroy-on-close>
    <div class="task-detail-scroll">
      <TaskDetailPanel v-if="open" :workspace-id="workspaceId" :task-id="taskId" />
    </div>
  </el-dialog>
</template>

<style scoped>
.task-detail-scroll { max-height: 72vh; overflow-y: auto; padding-right: 8px; }
</style>
