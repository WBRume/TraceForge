<script setup lang="ts">
import { reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { DeltaLineRef, DecisionMutationPayload } from '@/types/workspaceAssets'

const props = defineProps<{
  open: boolean
  deltaId: string
  lineRefs: DeltaLineRef[]
}>()

const emit = defineEmits<{
  submit: [payload: DecisionMutationPayload]
  close: []
}>()

const { t } = useI18n()

const form = reactive({
  title: '',
  body: '',
  status: 'PROPOSED',
})

const touched = reactive({ title: false })

watch(() => props.open, (isOpen) => {
  if (isOpen) {
    touched.title = false
    // Auto-generate title from line refs
    if (props.lineRefs.length) {
      const ref = props.lineRefs[0]
      const file = ref.file_path.split('/').pop() || ref.file_path
      if (ref.line_start === ref.line_end) {
        form.title = `Decision on ${file}#L${ref.line_start}`
      } else {
        form.title = `Decision on ${file}#L${ref.line_start}-L${ref.line_end}`
      }
    }
  }
})

function handleSubmit() {
  touched.title = true
  if (!form.title.trim()) return
  emit('submit', {
    title: form.title.trim(),
    body: form.body.trim() || null,
    status: form.status,
    human_delta_id: props.deltaId,
    delta_line_refs: props.lineRefs,
    source_type: 'TASK_DETAIL_BACKFILL',
  })
}

function lineRefSummary(ref: DeltaLineRef): string {
  const file = ref.file_path.split('/').pop() || ref.file_path
  if (ref.line_start === ref.line_end) {
    return `${file}#L${ref.line_start}`
  }
  return `${file}#L${ref.line_start}-L${ref.line_end}`
}
</script>

<template>
  <el-dialog
    :model-value="open"
    :title="t('workspace_assets.task_detail.workbench.decision_create.title')"
    width="520px"
    append-to-body
    destroy-on-close
    @close="emit('close')"
  >
    <div v-if="lineRefs.length" class="line-ref-summary">
      <span v-for="(ref, idx) in lineRefs" :key="idx" class="line-ref-tag">
        {{ lineRefSummary(ref) }}
      </span>
    </div>

    <el-form label-position="top" class="decision-form">
      <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.title') + ' *'">
        <el-input
          v-model="form.title"
          :class="{ 'is-invalid': touched.title && !form.title.trim() }"
          @blur="touched.title = true"
        />
      </el-form-item>

      <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.status')">
        <el-select v-model="form.status">
          <el-option :label="t('workspace_assets.task_detail.workbench.status.accepted')" value="ACCEPTED" />
          <el-option :label="t('workspace_assets.task_detail.workbench.status.proposed')" value="PROPOSED" />
          <el-option :label="t('workspace_assets.task_detail.workbench.status.rejected')" value="REJECTED" />
        </el-select>
      </el-form-item>

      <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.decision_body')">
        <el-input v-model="form.body" type="textarea" :rows="3" />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="emit('close')">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" @click="handleSubmit">
        {{ t('workspace_assets.task_detail.workbench.decisions.submit') }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.line-ref-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 14px;
}

.line-ref-tag {
  display: inline-block;
  padding: 2px 8px;
  font-size: 0.75rem;
  font-family: var(--font-mono, monospace);
  color: #3b82f6;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 4px;
}

.decision-form {
  display: grid;
  gap: 8px;
}

:deep(.is-invalid .el-input__wrapper),
:deep(.is-invalid.el-input .el-input__wrapper) {
  box-shadow: 0 0 0 1px #dc2626 inset, 0 0 0 2px rgba(220, 38, 38, 0.12);
}
</style>
