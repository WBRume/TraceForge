<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessageBox } from 'element-plus'
import { ArrowsRightLeftIcon, Link2, MoreHorizontal, Plus } from '@/components/icons'
import { taskDisplayStatus, taskStatusKey } from '@/utils/taskStatus'
import RequirementTaskLinkDialog from './RequirementTaskLinkDialog.vue'
import RequirementTaskProgress from './RequirementTaskProgress.vue'
import type {
  RequirementLinkedTask,
  RequirementSummary,
  RequirementTaskLinkPayload,
  RequirementTaskRelation,
  TaskSummary,
} from '@/types/workspaceAssets'

const props = defineProps<{
  workspaceId: string
  requirement: RequirementSummary
  linkedTasks: readonly RequirementLinkedTask[]
  tasks: readonly TaskSummary[]
  loading?: boolean
  canManage?: boolean
  linkTask?: (payload: RequirementTaskLinkPayload) => Promise<boolean>
}>()

const emit = defineEmits<{
  unlink: [taskId: string]
  changeRelation: [taskId: string, relation: RequirementTaskRelation]
}>()

const { t, locale } = useI18n()
const dialogVisible = shallowRef(false)
const minutes = computed(() => new Intl.NumberFormat(locale.value, {
  style: 'unit', unit: 'minute', unitDisplay: 'short', maximumFractionDigits: 1,
}))

const taskSelectOptions = computed(() => {
  const linkedIds = new Set(props.linkedTasks.map(task => task.task_id))
  return props.tasks.filter(task => !linkedIds.has(task.id)).map(task => ({
    label: task.current_phase ? `${task.name} (${task.current_phase})` : task.name,
    value: task.id,
  }))
})

function creatorLabel(task: RequirementLinkedTask) {
  return task.creator_name || t('task_rail.owner_unknown')
}

function openLinkDialog() {
  if (props.canManage && props.requirement.can_link_task && !props.loading) dialogVisible.value = true
}

function relationAction(task: RequirementLinkedTask) {
  return task.relation_type === 'COVERS'
    ? t('workspace_assets.requirements.progress.change_to_reference')
    : t('workspace_assets.requirements.progress.change_to_covers')
}

async function handleTaskCommand(task: RequirementLinkedTask, command: unknown) {
  if (!props.canManage || props.loading || (command !== 'unlink' && command !== 'change-relation')) return
  const requirementId = props.requirement.id
  const unlink = command === 'unlink'
  const affectsReview = props.requirement.status === 'PENDING_ACCEPTANCE' && (!unlink || task.relation_type === 'COVERS')

  if (unlink || affectsReview) {
    const message = unlink
      ? t('workspace_assets.requirements.link_task_modal.unlink_confirm_message', { name: task.task_name })
      : t('workspace_assets.requirements.task_links.change_relation_confirm', { name: task.task_name })
    try {
      await ElMessageBox.confirm(
        affectsReview ? `${message} ${t('workspace_assets.requirements.task_links.review_scope_changed')}` : message,
        unlink ? t('workspace_assets.requirements.link_task_modal.unlink_confirm_title') : relationAction(task),
        { confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel'), type: 'warning' },
      )
    } catch {
      return
    }
  }

  if (props.requirement.id !== requirementId || !props.canManage || props.loading) return
  if (unlink) emit('unlink', task.task_id)
  else emit('changeRelation', task.task_id, task.relation_type === 'COVERS' ? 'RELATES_TO' : 'COVERS')
}
</script>

<template>
  <section id="requirement-tasks" class="requirement-task-links-section" tabindex="-1">
    <header class="section-head">
      <h4>{{ t('workspace_assets.requirements.related_tasks_title') }}</h4>
      <button
        v-if="canManage && requirement.can_link_task && linkTask"
        type="button"
        class="associate-button"
        :aria-label="t('workspace_assets.requirements.actions.link_task')"
        :disabled="loading"
        @click="openLinkDialog"
      >
        <Plus :size="15" />
        {{ t('workspace_assets.requirements.task_links.associate') }}
      </button>
    </header>

    <RequirementTaskProgress :requirement="requirement" class="task-progress-summary" />

    <div v-if="linkedTasks.length" class="task-compact-list">
      <article v-for="task in linkedTasks" :key="task.link_id" class="task-compact-card">
        <div class="task-card-heading">
          <span v-if="task.task_status === 'PROVISIONING'" class="task-title">{{ task.task_name }}</span>
          <RouterLink
            v-else
            class="task-title task-title-link"
            :to="`/workspaces/${workspaceId}/chat/${task.task_id}`"
            :title="task.task_name"
          >
            {{ task.task_name }}
          </RouterLink>
          <el-dropdown
            v-if="canManage"
            trigger="click"
            placement="bottom-end"
            :disabled="loading"
            @command="handleTaskCommand(task, $event)"
          >
            <button
              type="button"
              class="task-menu-trigger"
              :aria-label="t('workspace_assets.requirements.task_links.more', { name: task.task_name })"
              :disabled="loading"
            >
              <MoreHorizontal :size="17" />
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="change-relation">
                  <ArrowsRightLeftIcon :size="15" />
                  {{ relationAction(task) }}
                </el-dropdown-item>
                <el-dropdown-item command="unlink" divided>
                  <Link2 :size="15" />
                  <span class="unlink-label">{{ t('workspace_assets.requirements.actions.unlink_task') }}</span>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>

        <div class="task-card-meta">
          <span class="task-relation" :data-relation="task.relation_type"
            :title="t(task.relation_type === 'COVERS'
              ? 'workspace_assets.requirements.relation_types.covers_desc'
              : 'workspace_assets.requirements.relation_types.relates_to_desc')"
          >
            {{ t(task.relation_type === 'COVERS'
              ? 'workspace_assets.requirements.relation_types.covers_short'
              : 'workspace_assets.requirements.relation_types.relates_to_short') }}
          </span>
          <span class="task-creator" :title="t('workspace_assets.requirements.task_links.creator', { name: creatorLabel(task) })">
            {{ creatorLabel(task) }}<template v-if="task.total_duration_ms && task.total_duration_ms >= 6000">
              · {{ minutes.format(task.total_duration_ms / 60000) }}
            </template>
          </span>
          <span class="task-status" :data-status="task.task_status" :title="task.current_phase || undefined">
            <span aria-hidden="true" />{{ t(taskStatusKey(taskDisplayStatus(task.task_status, task.task_interrupt_kind))) }}
          </span>
        </div>
      </article>
    </div>
    <p v-else-if="requirement.can_link_task" class="task-empty">{{ t('workspace_assets.requirements.related_tasks_empty') }}</p>

    <p v-if="!requirement.can_link_task" class="task-empty">
      {{ t('workspace_assets.requirements.task_links.parent_hint') }}
    </p>

    <RequirementTaskLinkDialog
      v-if="canManage && requirement.can_link_task && linkTask"
      :key="requirement.id"
      v-model="dialogVisible"
      :options="taskSelectOptions"
      :pending-acceptance="requirement.status === 'PENDING_ACCEPTANCE'"
      :send="linkTask"
    />
  </section>
</template>

<style scoped>
.requirement-task-links-section {
  display: grid;
  gap: 12px;
  scroll-margin-top: 24px;
}
.requirement-task-links-section:focus-visible {
  outline: 2px solid #3b82f6;
  outline-offset: 3px;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.section-head h4 {
  margin: 0;
  color: #1e3a8a;
  font-size: 0.95rem;
  font-weight: 700;
}
.associate-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-height: 29px;
  padding: 4px 9px;
  border: 1px solid #d5e5f4;
  border-radius: 7px;
  background: #f7fbff;
  color: #075985;
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.associate-button:hover:not(:disabled) { background: #eaf5ff; }
.associate-button:disabled, .task-menu-trigger:disabled { opacity: 0.55; cursor: default; }
.task-progress-summary { padding-block: 2px 11px; border-bottom: 1px solid #e2e8f0; }
.task-compact-list { display: grid; gap: 7px; }
.task-compact-card {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 7px 10px 9px;
  border: 1px solid #e3eaf2;
  border-radius: 9px;
  background: #fff;
}
.task-compact-card:hover, .task-compact-card:focus-within { border-color: #bcd5e9; }
.task-card-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  min-height: 25px;
}
.task-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #172b43;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.5;
}
.task-title-link:hover { color: #0369a1; text-decoration: underline; text-underline-offset: 3px; }
.task-menu-trigger {
  display: grid;
  width: 27px;
  height: 27px;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #52647c;
  cursor: pointer;
}
.task-menu-trigger:hover:not(:disabled), .task-menu-trigger[aria-expanded="true"] {
  color: #075985;
  background: #edf5fc;
}
.task-menu-trigger:focus-visible, .associate-button:focus-visible, .task-title-link:focus-visible {
  outline: 2px solid #0ea5e9;
  outline-offset: 2px;
}
.task-card-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #52647c;
  font-size: 11px;
}
.task-relation {
  flex: none;
  padding: 2px 5px;
  border-radius: 4px;
  background: #f1f5f9;
  color: #52647c;
  line-height: 1.4;
}
.task-relation[data-relation="COVERS"] { background: #ebf4fe; color: #1e497a; }
.task-creator {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.task-status { display: inline-flex; align-items: center; flex: none; gap: 4px; }
.task-status > span { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.task-status[data-status="COMPLETED"] { color: #15803d; }
.task-status[data-status="RUNNING"] { color: #1d4ed8; }
.task-status[data-status="AWAITING_INPUT"], .task-status[data-status="INTERRUPTED"] { color: #a0510b; }
.task-status[data-status="ROUND_COMPLETED"] { color: #5b50a5; }
.task-status[data-status="FAILED"] { color: #b91c1c; }
.unlink-label { color: #b91c1c; }
.task-empty { margin: 0; color: #52647c; font-size: 12px; line-height: 1.55; }
</style>
