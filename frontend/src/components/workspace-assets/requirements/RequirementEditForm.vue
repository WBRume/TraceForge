<script setup lang="ts">
import { computed, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseSelect from '@/components/BaseSelect.vue'
import RequirementAssignmentFields from './RequirementAssignmentFields.vue'
import RequirementPrerequisiteSelect from './RequirementPrerequisiteSelect.vue'
import { useAuthStore } from '@/stores/auth'
import { editableRequirementStatuses, requirementStatusKey } from '@/utils/requirementStatus'
import type { RequirementEditableStatus, RequirementMutationPayload, RequirementSummary } from '@/types/workspaceAssets'

const props = defineProps<{ workspaceId: string; requirement: RequirementSummary; createChild?: boolean }>()
const emit = defineEmits<{ submit: [payload: RequirementMutationPayload] }>()
const { t } = useI18n()
const auth = useAuthStore()
const fields = 'workspace_assets.requirements.fields.'
const delivery = 'workspace_assets.delivery.'
const current = props.createChild ? null : props.requirement
const form = reactive({
  title: current?.title || '',
  body: current?.body || '',
  taskPrompt: current?.task_prompt ?? String(current?.source_metadata?.task_prompt ?? ''),
  criteria: (current?.acceptance_criteria || []).join('\n'),
  priority: current?.priority || '',
  status: (current?.status || 'DRAFT') as RequirementEditableStatus,
  ownerId: current ? current.owner_id ?? null : auth.user?.id ?? null,
  reviewerId: current?.reviewer_id ?? null,
  acceptorId: current?.acceptor_id ?? null,
  predecessorId: current?.predecessor_id ?? null,
  reviewRequired: current?.result_check_required === true,
  sourceKind: current?.source_kind || '',
  sourceRef: current?.source_ref || '',
  sourceUri: current?.source_uri || '',
  reason: '',
})
const assignmentRequirement = current || {
  ...props.requirement, status: 'DRAFT', work_started: false, child_count: 0,
  owner_id: auth.user?.id, owner_name: auth.user?.display_name,
  reviewer_id: null, reviewer_name: null, acceptor_id: null, acceptor_name: null,
}
const statusOptions = computed(() => {
  const status = current?.status
  const choices = status === 'VERIFIED' || status === 'REJECTED' ? [status, 'ARCHIVED'] : editableRequirementStatuses
  return choices.map(value => ({ value, label: t(requirementStatusKey(value)) }))
})
const statusEditable = computed(() => !current || statusOptions.value.some(option => option.value === current.status))

function submit() {
  const title = form.title.trim()
  if (!title) return
  const reviewer = form.reviewRequired ? form.reviewerId : null
  emit('submit', {
    title,
    body: form.body || null,
    task_prompt: form.taskPrompt || null,
    acceptance_criteria: form.criteria.split('\n').map(item => item.trim()).filter(Boolean),
    priority: form.priority || null,
    source_kind: form.sourceKind || null,
    source_ref: form.sourceRef || null,
    source_uri: form.sourceUri || null,
    change_reason: form.reason || null,
    ...(statusEditable.value && form.status !== current?.status ? { status: form.status } : {}),
    ...(!current || form.ownerId !== (current.owner_id ?? null) ? { owner_id: form.ownerId } : {}),
    ...(!current || form.acceptorId !== (current.acceptor_id ?? null) ? { acceptor_id: form.acceptorId } : {}),
    ...(!current || reviewer !== (current.reviewer_id ?? null) ? { reviewer_id: reviewer } : {}),
    ...(!current || form.reviewRequired !== Boolean(current.result_check_required) ? { result_check_required: form.reviewRequired } : {}),
    ...(!current || form.predecessorId !== (current.predecessor_id ?? null) ? { predecessor_id: form.predecessorId } : {}),
  })
}
</script>

<template>
  <el-form id="requirement-edit-form" label-position="top" class="form-grid" @submit.prevent="submit">
    <section class="form-panel">
      <el-form-item :label="t(fields + 'title')" required><el-input v-model="form.title" required maxlength="300" /></el-form-item>
      <el-form-item :label="t(fields + 'description')"><el-input v-model="form.body" type="textarea" :rows="5" /></el-form-item>
      <el-form-item :label="t(fields + 'acceptance_criteria')">
        <el-input v-model="form.criteria" type="textarea" :rows="4" :placeholder="t('workspace_assets.requirements.placeholders.criteria')" />
      </el-form-item>
      <el-form-item :label="t('task_rail.initial_prompt')"><el-input v-model="form.taskPrompt" type="textarea" :rows="3" /></el-form-item>
      <div class="paired-fields">
        <el-form-item :label="t(fields + 'source_kind')"><el-input v-model="form.sourceKind" maxlength="80" /></el-form-item>
        <el-form-item :label="t(fields + 'source_ref')"><el-input v-model="form.sourceRef" maxlength="300" /></el-form-item>
      </div>
      <el-form-item :label="t('task_rail.document_location')"><el-input v-model="form.sourceUri" maxlength="1000" /></el-form-item>
      <el-form-item v-if="current?.source_metadata?.source_filename" :label="t('task_rail.source_document')">
        <el-input :model-value="String(current.source_metadata.source_filename)" readonly />
      </el-form-item>
    </section>
    <section class="form-panel">
      <h2>{{ t(delivery + 'assignment') }}</h2>
      <RequirementAssignmentFields v-model:owner-id="form.ownerId" v-model:reviewer-id="form.reviewerId"
        v-model:acceptor-id="form.acceptorId" v-model:review-required="form.reviewRequired"
        :workspace-id="workspaceId" :requirement="assignmentRequirement" />
      <div class="paired-fields">
        <el-form-item :label="t(fields + 'status')">
          <BaseSelect v-if="statusEditable" v-model="form.status" :options="statusOptions" :aria-label="t(fields + 'status')" />
          <el-input v-else :model-value="t(requirementStatusKey(form.status))" readonly />
        </el-form-item>
        <el-form-item :label="t(fields + 'priority')"><el-input v-model="form.priority" maxlength="40" /></el-form-item>
      </div>
      <el-form-item :label="t(delivery + 'predecessor')">
        <RequirementPrerequisiteSelect v-model="form.predecessorId" :workspace-id="workspaceId"
          :requirement-id="current?.id || ''" :initial-title="current?.predecessor_title" />
      </el-form-item>
      <el-form-item :label="t(fields + 'change_reason')"><el-input v-model="form.reason" type="textarea" :rows="2" /></el-form-item>
    </section>
  </el-form>
</template>

<style scoped>
.form-grid { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(300px, 1fr); gap: 18px; align-items: start; }
.form-panel { padding: 20px; border: 1px solid var(--el-border-color-light); border-radius: 12px; background: var(--el-bg-color); min-width: 0; }
.form-panel h2 { margin: 0 0 16px; font-size: 16px; font-weight: 600; }
.form-panel > .el-form-item:last-child { margin-bottom: 0; }
.paired-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
@media (max-width: 820px) {
  .form-grid { grid-template-columns: minmax(0, 1fr); gap: 12px; }
  .form-panel { padding: 14px; }
}
</style>
