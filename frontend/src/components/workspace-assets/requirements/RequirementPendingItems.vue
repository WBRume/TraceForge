<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, useRouter, type RouteLocationRaw } from 'vue-router'
import type { RequirementSummary } from '@/types/workspaceAssets'
import { taskStatusKey } from '@/utils/taskStatus'
import { canSubmitRequirementAcceptance } from '@/utils/requirementStatus'

const props = defineProps<{ requirement: RequirementSummary }>()
const { t } = useI18n()
const router = useRouter()
const pendingStatuses = new Set(['FAILED', 'AWAITING_INPUT', 'INTERRUPTED', 'ROUND_COMPLETED', 'INITIALIZED'])

const items = computed(() => {
  const row = props.requirement
  if (row.status === 'ARCHIVED' || row.status === 'VERIFIED' || !row.task_progress) return []

  const result: { key: string; label: string; to: RouteLocationRaw }[] = []
  const detail = (id: string, focus: 'acceptance' | 'tasks'): RouteLocationRaw => ({
    name: 'workspaceAssetsRequirementDetail',
    params: { wsId: row.workspace_id, requirementId: id },
    query: { focus },
  })
  if (row.status === 'PENDING_ACCEPTANCE' || (canSubmitRequirementAcceptance(row.status) && !row.acceptance_blocker)) {
    const action = row.status === 'PENDING_ACCEPTANCE' ? 'title' : 'submit'
    result.push({ key: 'acceptance', label: t(`workspace_assets.requirements.acceptance.${action}`), to: detail(row.id, 'acceptance') })
  }
  if (row.acceptance_blocker === 'no_tasks' && canSubmitRequirementAcceptance(row.status)) {
    result.push({ key: 'assign', label: t('workspace_assets.requirements.pending.assign'), to: detail(row.id, 'tasks') })
  }
  const unassigned = new Set(row.task_progress.unassigned_child_ids)
  for (const child of row.children || []) {
    const review = child.status === 'PENDING_ACCEPTANCE' || (canSubmitRequirementAcceptance(child.status) && !child.acceptance_blocker)
    if (review || (canSubmitRequirementAcceptance(child.status) && unassigned.has(child.id))) {
      result.push({
        key: child.id,
        label: t(`workspace_assets.requirements.pending.${review ? 'child_review' : 'child'}`, { name: child.title }),
        to: detail(child.id, review ? 'acceptance' : 'tasks'),
      })
    }
  }
  const seenTasks = new Set<string>()
  for (const task of row.linked_tasks || []) {
    if (task.relation_type !== 'COVERS' || !pendingStatuses.has(task.task_status) || seenTasks.has(task.task_id)) continue
    seenTasks.add(task.task_id)
    result.push({
      key: task.task_id,
      label: t('workspace_assets.requirements.pending.task', { status: t(taskStatusKey(task.task_status)), name: task.task_name }),
      to: { name: 'taskChat', params: { wsId: row.workspace_id, taskId: task.task_id } },
    })
  }
  return result
})

function navigate(key: string) {
  const item = items.value.find(entry => entry.key === key)
  if (item) void router.push(item.to)
}
</script>

<template>
  <div v-if="items.length" class="pending-items" @click.stop>
    <RouterLink v-if="items.length === 1 && items[0]" :to="items[0].to" class="pending-link" :title="items[0].label">
      {{ items[0].label }}
    </RouterLink>
    <el-dropdown v-else trigger="click" @command="navigate">
      <button type="button" class="pending-link" :aria-label="t('workspace_assets.requirements.pending.title')">
        {{ t('workspace_assets.requirements.pending.count', { count: items.length }) }} ▾
      </button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item v-for="item in items" :key="item.key" :command="item.key">{{ item.label }}</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </div>
</template>

<style scoped>
.pending-items { display: flex; min-width: 0; }
.pending-link {
  overflow: hidden;
  max-width: 100%;
  padding: 0;
  border: 0;
  color: #0369a1;
  background: none;
  font: inherit;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}
.pending-link:hover { text-decoration: underline; }
</style>
