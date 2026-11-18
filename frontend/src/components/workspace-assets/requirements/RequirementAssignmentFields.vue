<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import RequirementOwnerSelect from './RequirementOwnerSelect.vue'
import MemberWorkloadDetails from '../workload/MemberWorkloadDetails.vue'
import { countsFor } from '../workload/workloadCounts'
import { useWorkspaceWorkload } from '@/composables/useWorkspaceWorkload'
import type { RequirementSummary } from '@/types/workspaceAssets'

const props = defineProps<{ workspaceId: string; requirement: RequirementSummary }>()
const ownerId = defineModel<string | null>('ownerId', { required: true })
const reviewerId = defineModel<string | null>('reviewerId', { required: true })
const acceptorId = defineModel<string | null>('acceptorId', { required: true })
const reviewRequired = defineModel<boolean>('reviewRequired', { required: true })
const { t } = useI18n()
const delivery = 'workspace_assets.delivery.'
const workload = 'workspace_assets.workload.'
const { data, failed } = useWorkspaceWorkload(() => props.workspaceId)
const selected = computed(() => data.value?.members.find(member => member.user_id === ownerId.value))
const counts = computed(() => selected.value ? countsFor(selected.value) : null)
const impact = computed(() => {
  if (!ownerId.value || ownerId.value === props.requirement.owner_id
    || props.requirement.child_count || ['VERIFIED', 'ARCHIVED'].includes(props.requirement.status)) return null
  return props.requirement.work_started ? 'ongoing_impact' : 'plan_impact'
})
const owner = computed(() => props.requirement.owner_id ? {
  user_id: props.requirement.owner_id, display_name: props.requirement.owner_name || props.requirement.owner_id,
} : undefined)
const reviewer = computed(() => props.requirement.reviewer_id ? {
  user_id: props.requirement.reviewer_id, display_name: props.requirement.reviewer_name || props.requirement.reviewer_id,
} : undefined)
const acceptor = computed(() => props.requirement.acceptor_id ? {
  user_id: props.requirement.acceptor_id, display_name: props.requirement.acceptor_name || props.requirement.acceptor_id,
} : undefined)
</script>

<template>
  <el-form-item :label="t('workspace_assets.requirements.owner')">
    <RequirementOwnerSelect v-model="ownerId" :workspace-id="workspaceId" :initial-owner="owner" :workloads="failed ? undefined : data?.members" />
  </el-form-item>
  <el-alert v-if="failed && ownerId" :title="t(workload + (data ? 'stale' : 'unavailable'))" type="warning" :closable="false" />
  <div v-if="selected && counts && data" class="member-summary">
    <div class="metrics">
      <el-tag type="info">{{ t(workload + 'pending') }} {{ counts.pending }}</el-tag>
      <el-tag v-for="slot in (['background', 'interactive'] as const)" :key="slot"
        :type="selected.limits[slot] !== null && counts[slot] > selected.limits[slot]! ? 'warning' : 'info'">
        {{ t(workload + slot) }} {{ counts[slot] }}<template v-if="selected.limits[slot] !== null"> / {{ selected.limits[slot] }}</template>
      </el-tag>
      <el-tag type="info">{{ t(workload + 'planned') }} {{ counts.planned }}</el-tag>
      <el-tag v-if="counts.expected" type="info">{{ t(workload + 'return_count', { count: counts.expected }) }}</el-tag>
      <el-tag v-if="counts.overdue" type="warning">{{ t(workload + 'overdue', { count: counts.overdue }) }}</el-tag>
      <el-tag v-if="counts.uncertain" type="warning">{{ t(workload + 'uncertain') }} {{ counts.uncertain }}</el-tag>
      <el-tag v-if="counts.incomplete" type="warning">{{ t(workload + 'incomplete') }} {{ counts.incomplete }}</el-tag>
    </div>
    <details v-if="selected.items.length || selected.executions.length" :key="selected.user_id">
      <summary>{{ t(workload + 'details') }}</summary>
      <MemberWorkloadDetails :items="selected.items" :executions="selected.executions" :workspace-id="workspaceId"
        :as-of="data.as_of" inline />
    </details>
  </div>
  <p v-if="impact" class="assignment-impact">{{ t(delivery + impact) }}</p>
  <p v-if="impact && requirement.status === 'PENDING_ACCEPTANCE' && acceptorId === (requirement.acceptor_id || null)"
    class="assignment-impact">{{ t(delivery + 'acceptance_impact') }}</p>

  <el-form-item :label="t(delivery + 'acceptor')">
    <RequirementOwnerSelect v-model="acceptorId" :workspace-id="workspaceId" :initial-owner="acceptor" :label="t(delivery + 'acceptor')" />
  </el-form-item>
  <template v-if="!requirement.child_count">
    <el-checkbox v-model="reviewRequired">{{ t(delivery + 'review_required') }}</el-checkbox>
    <el-form-item v-if="reviewRequired" :label="t(delivery + 'reviewer')">
      <RequirementOwnerSelect v-model="reviewerId" :workspace-id="workspaceId" :initial-owner="reviewer" :label="t(delivery + 'reviewer')" />
    </el-form-item>
  </template>
</template>

<style scoped>
.member-summary { display: grid; gap: 8px; margin: -8px 0 14px; }
.metrics { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.member-summary summary { cursor: pointer; width: fit-content; color: var(--el-color-primary-dark-2); font-size: 13px; }
.member-summary details[open] summary { margin-bottom: 8px; }
.assignment-impact { color: var(--el-text-color-secondary); font-size: 13px; margin: 0 0 12px; }
</style>
