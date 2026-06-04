<script setup lang="ts">
import { computed, reactive } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import BaseSelect from '@/components/BaseSelect.vue'
import type { RequirementLinkedTask, RequirementSummary, TaskSummary } from '@/types/workspaceAssets'

const props = defineProps<{
  workspaceId: string
  requirement: RequirementSummary
  linkedTasks: readonly RequirementLinkedTask[]
  tasks: readonly TaskSummary[]
  loading?: boolean
}>()

const emit = defineEmits<{
  link: [payload: { taskId: string; relationType: 'RELATES_TO' | 'COVERS'; reason?: string | null }]
  unlink: [taskId: string]
}>()

const { t } = useI18n()
const form = reactive({
  taskId: '',
  relationType: 'RELATES_TO' as 'RELATES_TO' | 'COVERS',
  reason: '',
})

const linkedIds = computed(() => new Set(props.linkedTasks.map((item) => item.task_id)))
const taskOptions = computed(() => props.tasks.filter((task) => !linkedIds.value.has(task.id)))
const taskSelectOptions = computed(() => taskOptions.value.map((task) => ({ label: task.name, value: task.id })))
const relationTypeOptions = [
  { label: 'RELATES_TO', value: 'RELATES_TO' },
  { label: 'COVERS', value: 'COVERS' },
]

function submit() {
  if (!form.taskId || !props.requirement.can_link_task) return
  emit('link', {
    taskId: form.taskId,
    relationType: form.relationType,
    reason: form.reason || null,
  })
  form.taskId = ''
  form.reason = ''
}
</script>

<template>
  <section class="requirement-section">
    <header class="section-head">
      <div>
        <h4>{{ t('workspace_assets.requirements.related_tasks_title') }}</h4>
        <p>{{ t('workspace_assets.requirements.detail.related_tasks_body') }}</p>
      </div>
    </header>

    <el-alert
      v-if="!requirement.can_link_task"
      type="info"
      :closable="false"
      :title="t('workspace_assets.requirements.drawer.parent_link_blocked')"
      show-icon
    />

    <el-form class="link-form" :inline="true" @submit.prevent="submit">
      <el-form-item :label="t('workspace_assets.requirements.detail.select_task')">
        <BaseSelect
          v-model="form.taskId"
          :options="taskSelectOptions"
          :placeholder="t('workspace_assets.requirements.detail.select_task')"
          :disabled="!requirement.can_link_task"
          size="sm"
        />
      </el-form-item>
      <el-form-item :label="t('workspace_assets.requirements.drawer.relation_type')">
        <BaseSelect
          v-model="form.relationType"
          :options="relationTypeOptions"
          :disabled="!requirement.can_link_task"
          size="sm"
        />
      </el-form-item>
      <el-form-item :label="t('workspace_assets.requirements.fields.change_reason')">
        <el-input v-model="form.reason" clearable :disabled="!requirement.can_link_task" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :disabled="loading || !form.taskId || !requirement.can_link_task" @click="submit">
          {{ t('workspace_assets.requirements.actions.link_task') }}
        </el-button>
      </el-form-item>
    </el-form>

    <el-table v-if="linkedTasks.length" :data="linkedTasks" row-key="link_id" size="small">
      <el-table-column prop="task_name" :label="t('workspace_assets.requirements.drawer.task')" min-width="220">
        <template #default="{ row }">
          <RouterLink :to="`/ws/${workspaceId}/assets/tasks/${row.task_id}`">{{ row.task_name }}</RouterLink>
        </template>
      </el-table-column>
      <el-table-column prop="relation_type" :label="t('workspace_assets.requirements.drawer.relation_type')" width="140" />
      <el-table-column prop="coverage_status" :label="t('workspace_assets.requirements.fields.coverage')" width="170" />
      <el-table-column :label="t('workspace_assets.requirements.table.operations')" width="140">
        <template #default="{ row }">
          <el-button size="small" type="danger" plain :disabled="loading" @click="emit('unlink', row.task_id)">
            {{ t('workspace_assets.requirements.actions.unlink_task') }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-else :description="t('workspace_assets.requirements.related_tasks_empty')" />
  </section>
</template>

<style scoped>
.requirement-section {
  display: grid;
  gap: 12px;
}

.section-head h4 {
  margin: 0 0 4px;
  font-family: 'Poppins', sans-serif;
  font-size: 1.1rem;
  color: #1e3a8a;
}

.section-head p {
  margin: 0;
  color: #94a3b8;
  font-size: 0.875rem;
  line-height: 1.5;
}

.link-form {
  padding: 16px;
  border-radius: 12px;
  background: #f8fafc;
  margin: 16px 0;
  border: 1px solid #f1f5f9;
}

.link-form :deep(.base-select) {
  width: 200px;
}
</style>
