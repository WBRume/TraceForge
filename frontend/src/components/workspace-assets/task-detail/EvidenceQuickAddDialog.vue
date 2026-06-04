<script setup lang="ts">
import { reactive, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { EvidenceMutationPayload } from '@/types/workspaceAssets'

type QuickAddMode = 'commit' | 'mr' | 'confirm' | 'failure' | 'log'

const props = defineProps<{
  mode: QuickAddMode
  visible: boolean
  saving?: boolean
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  submit: [payload: EvidenceMutationPayload]
}>()

const { t } = useI18n()

const form = reactive({
  title: '',
  summary: '',
  source_ref: '',
  source_uri: '',
  source_path: '',
})

const errors = reactive({
  title: false,
  source: false,
})

const modeConfig = computed(() => {
  const configs: Record<QuickAddMode, { evidenceType: string; sourceType: string; needsRef: boolean; needsUri: boolean; needsPath: boolean }> = {
    commit: { evidenceType: 'CODE', sourceType: 'COMMIT', needsRef: true, needsUri: false, needsPath: false },
    mr: { evidenceType: 'CODE', sourceType: 'MR', needsRef: false, needsUri: true, needsPath: false },
    confirm: { evidenceType: 'HUMAN_CONFIRMATION', sourceType: 'HUMAN_CONFIRMATION', needsRef: false, needsUri: false, needsPath: false },
    failure: { evidenceType: 'FAILURE', sourceType: 'OTHER', needsRef: false, needsUri: false, needsPath: true },
    log: { evidenceType: 'RUNTIME', sourceType: 'RUN_LOG', needsRef: false, needsUri: false, needsPath: true },
  }
  return configs[props.mode]
})

function close() {
  emit('update:visible', false)
}

function submitForm() {
  const config = modeConfig.value
  errors.title = !form.title.trim()

  let sourceValid = true
  if (config.needsRef) sourceValid = !!form.source_ref.trim()
  else if (config.needsUri) sourceValid = !!form.source_uri.trim()
  else if (config.needsPath) sourceValid = !!form.source_path.trim()
  errors.source = !sourceValid

  if (errors.title || errors.source) return

  const payload: EvidenceMutationPayload = {
    title: form.title.trim(),
    summary: form.summary.trim() || null,
    evidence_type: config.evidenceType,
    source_type: config.sourceType,
    source_ref: form.source_ref.trim() || null,
    source_uri: form.source_uri.trim() || null,
    source_path: form.source_path.trim() || null,
    confirmed: props.mode === 'confirm',
  }
  emit('submit', payload)
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="t(`workspace_assets.task_detail.workbench.evidence_dialog.title_${mode}`)"
    width="460px"
    append-to-body
    :close-on-click-modal="false"
    @update:model-value="close"
  >
    <el-form label-position="top" @submit.prevent="submitForm">
      <el-form-item
        :label="t('workspace_assets.task_detail.workbench.fields.title')"
        :error="errors.title ? t('workspace_assets.task_detail.workbench.evidence_dialog.title_required') : ''"
      >
        <el-input v-model="form.title" :placeholder="t(`workspace_assets.task_detail.workbench.evidence_dialog.placeholder_${mode}`)" />
      </el-form-item>

      <el-form-item v-if="modeConfig.needsRef" :label="t('workspace_assets.task_detail.workbench.evidence_dialog.field_commit_sha')" :error="errors.source ? t('workspace_assets.task_detail.workbench.evidence_dialog.source_required') : ''">
        <el-input v-model="form.source_ref" placeholder="abc1234" />
      </el-form-item>

      <el-form-item v-if="modeConfig.needsUri" :label="t('workspace_assets.task_detail.workbench.evidence_dialog.field_mr_url')" :error="errors.source ? t('workspace_assets.task_detail.workbench.evidence_dialog.source_required') : ''">
        <el-input v-model="form.source_uri" placeholder="https://..." />
      </el-form-item>

      <el-form-item v-if="modeConfig.needsPath" :label="t('workspace_assets.task_detail.workbench.fields.path')" :error="errors.source ? t('workspace_assets.task_detail.workbench.evidence_dialog.source_required') : ''">
        <el-input v-model="form.source_path" :placeholder="t('workspace_assets.task_detail.workbench.evidence_dialog.placeholder_path')" />
      </el-form-item>

      <el-form-item :label="t('workspace_assets.task_detail.workbench.fields.summary')">
        <el-input v-model="form.summary" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="close">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="saving" @click="submitForm">
        {{ t('common.confirm') }}
      </el-button>
    </template>
  </el-dialog>
</template>
