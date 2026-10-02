<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, useRoute } from 'vue-router'
import { ArrowLeft } from '@/components/icons'
import TaskFinalWorkflowPanel from '@/components/workspace-assets/task-final-workflow/TaskFinalWorkflowPanel.vue'

const route = useRoute()
const { t } = useI18n()

const wsId = computed(() => String(route.params.wsId || ''))
const taskId = computed(() => String(route.params.taskId || ''))
const taskDetailRoute = computed(() => ({
  name: 'workspaceAssetTaskDetail',
  params: { wsId: wsId.value, taskId: taskId.value },
  query: { section: 'finalWorkflow' },
}))
</script>

<template>
  <div class="task-final-workflow-view">
    <div class="view-header-bar">
      <RouterLink class="back-link" :to="taskDetailRoute">
        <ArrowLeft class="back-icon" />
        <span>{{ t('workspace_assets.task_detail.final_workflow.route.back_to_task_detail') }}</span>
      </RouterLink>
      <div class="view-title">
        <h1>{{ t('workspace_assets.task_detail.final_workflow.route.title') }}</h1>
      </div>
    </div>

    <main class="workflow-shell">
      <TaskFinalWorkflowPanel :workspace-id="wsId" :task-id="taskId" />
    </main>
  </div>
</template>

<style scoped>
.task-final-workflow-view {
  min-height: 100vh;
  padding: 32px 40px;
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  color: #0f172a;
}

.view-header-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 24px;
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #ffffff;
  color: #475569;
  font-size: 0.84rem;
  font-weight: 700;
  text-decoration: none;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
  transition: all 0.2s ease;
}

.back-link:hover {
  border-color: #bae6fd;
  color: #0284c7;
  transform: translateX(-2px);
  box-shadow: 0 4px 10px rgba(2, 132, 199, 0.08);
}

.back-icon {
  width: 16px;
  height: 16px;
}

.view-title {
  text-align: right;
}

.view-title h1 {
  margin: 0;
  color: #0f172a;
  font-size: 1.45rem;
  font-weight: 800;
  letter-spacing: -0.01em;
  line-height: 1.2;
}

.workflow-shell {
  padding: 32px;
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(16px);
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.04);
}

@media (max-width: 900px) {
  .task-final-workflow-view {
    padding: 20px;
  }

  .workflow-shell {
    padding: 20px;
    border-radius: 20px;
  }
}

@media (max-width: 700px) {
  .view-header-bar {
    align-items: flex-start;
    flex-direction: column;
    gap: 12px;
  }

  .view-title {
    text-align: left;
  }
}
</style>
