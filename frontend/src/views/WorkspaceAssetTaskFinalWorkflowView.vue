<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, useRoute } from 'vue-router'
import { ArrowLeft } from 'lucide-vue-next'
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
        <p>{{ t('workspace_assets.task_detail.final_workflow.route.eyebrow') }}</p>
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
  padding: 32px;
  background: #f8fafc;
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
  padding: 8px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #ffffff;
  color: #475569;
  font-size: 0.84rem;
  font-weight: 700;
  text-decoration: none;
}

.back-link:hover {
  border-color: #bfdbfe;
  color: #2563eb;
}

.back-icon {
  width: 17px;
  height: 17px;
}

.view-title {
  text-align: right;
}

.view-title p {
  margin: 0 0 4px;
  color: #64748b;
  font-size: 0.72rem;
  font-weight: 800;
  text-transform: uppercase;
}

.view-title h1 {
  margin: 0;
  color: #0f172a;
  font-size: 1.45rem;
  line-height: 1.2;
}

.workflow-shell {
  padding: 24px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #ffffff;
}

@media (max-width: 700px) {
  .task-final-workflow-view {
    padding: 16px;
  }

  .view-header-bar {
    align-items: flex-start;
    flex-direction: column;
  }

  .view-title {
    text-align: left;
  }

  .workflow-shell {
    padding: 16px;
  }
}
</style>
