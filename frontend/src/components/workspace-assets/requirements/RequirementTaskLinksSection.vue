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
      </div>
    </header>

    <div v-if="linkedTasks.length" class="linked-task-cards">
      <article v-for="task in linkedTasks" :key="task.link_id" class="linked-task-card">
        <RouterLink class="linked-task-main" :to="`/workspaces/${workspaceId}/chat/${task.task_id}`" :aria-disabled="task.task_status === 'PROVISIONING' || undefined" @click="task.task_status === 'PROVISIONING' && $event.preventDefault()">
          <strong>{{ task.task_name }}</strong><span class="linked-task-status">{{ task.task_status }}<span v-if="task.current_phase"> · {{ task.current_phase }}</span></span>
          <small>{{ task.creator_name || t('task_rail.owner_unknown') }} · {{ ((task.total_duration_ms || 0) / 60000).toFixed(1) }} min</small>
        </RouterLink>
        <el-button size="small" type="danger" plain :disabled="loading" @click="emit('unlink', task.task_id)">{{ t('workspace_assets.requirements.actions.unlink_task') }}</el-button>
      </article>
    </div>
    <el-empty v-else :description="t('workspace_assets.requirements.related_tasks_empty')" />

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

  </section>
</template>

<style scoped>
.linked-task-cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(260px,100%),1fr)); gap:10px; }
.linked-task-card { display:flex; align-items:center; gap:12px; padding:14px; border:1px solid var(--color-primary-100); border-radius:10px; }
.linked-task-main { flex:1; min-width:0; display:grid; gap:6px; color:var(--color-text-body); text-decoration:none; }
.linked-task-main strong { overflow:hidden; text-overflow:ellipsis; font-size:.85rem; }
.linked-task-main small, .linked-task-status { color:var(--color-text-muted); font-size:.75rem; }
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
