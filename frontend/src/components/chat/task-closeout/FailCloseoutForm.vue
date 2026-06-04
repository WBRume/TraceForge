<script setup lang="ts">
import { computed, reactive, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseSelect from '@/components/BaseSelect.vue'
import CloseoutEvidenceUploader from './CloseoutEvidenceUploader.vue'
import type {
  FailCloseoutPayload,
  FailureReason,
  FailureStage,
} from '@/types/taskCloseout'

defineProps<{
  saving?: boolean
}>()

const emit = defineEmits<{
  submit: [payload: Omit<FailCloseoutPayload, 'evidence_attachments'>, files: File[]]
  cancel: []
}>()

const { t } = useI18n()
const files = shallowRef<File[]>([])
const errors = reactive({
  summary: false,
  evidence: false,
})

const form = reactive({
  failure_stage: 'CODING' as FailureStage,
  failure_reason: 'OTHER' as FailureReason,
  failure_summary: '',
})

const failureStageOptions = computed(() => [
  { label: t('chat.closeout.failure_stage_options.ai_solution'), value: 'AI_SOLUTION' },
  { label: t('chat.closeout.failure_stage_options.coding'), value: 'CODING' },
  { label: t('chat.closeout.failure_stage_options.compile'), value: 'COMPILE' },
  { label: t('chat.closeout.failure_stage_options.package'), value: 'PACKAGE' },
  { label: t('chat.closeout.failure_stage_options.device_test'), value: 'DEVICE_TEST' },
  { label: t('chat.closeout.failure_stage_options.integration'), value: 'INTEGRATION' },
  { label: t('chat.closeout.failure_stage_options.requirement_clarification'), value: 'REQUIREMENT_CLARIFICATION' },
  { label: t('chat.closeout.failure_stage_options.other'), value: 'OTHER' },
])

const failureReasonOptions = computed(() => [
  { label: t('chat.closeout.failure_reason_options.ai_direction_wrong'), value: 'AI_DIRECTION_WRONG' },
  { label: t('chat.closeout.failure_reason_options.project_context_insufficient'), value: 'PROJECT_CONTEXT_INSUFFICIENT' },
  { label: t('chat.closeout.failure_reason_options.compile_error'), value: 'COMPILE_ERROR' },
  { label: t('chat.closeout.failure_reason_options.package_error'), value: 'PACKAGE_ERROR' },
  { label: t('chat.closeout.failure_reason_options.device_test_failed'), value: 'DEVICE_TEST_FAILED' },
  { label: t('chat.closeout.failure_reason_options.api_unclear'), value: 'API_UNCLEAR' },
  { label: t('chat.closeout.failure_reason_options.requirement_unclear'), value: 'REQUIREMENT_UNCLEAR' },
  { label: t('chat.closeout.failure_reason_options.environment_issue'), value: 'ENVIRONMENT_ISSUE' },
  { label: t('chat.closeout.failure_reason_options.other'), value: 'OTHER' },
])

function trimmed(value: string): string | null {
  const next = value.trim()
  return next || null
}

function updateFiles(nextFiles: File[]) {
  files.value = nextFiles
  if (nextFiles.length > 0) errors.evidence = false
}

function submitForm() {
  errors.summary = !trimmed(form.failure_summary)
  errors.evidence = files.value.length === 0
  if (errors.summary || errors.evidence) return
  emit('submit', {
    failure_stage: form.failure_stage,
    failure_reason: form.failure_reason,
    failure_summary: form.failure_summary.trim(),
  }, files.value)
}
</script>

<template>
  <form class="closeout-form" @submit.prevent="submitForm">
    <div class="form-section">
      <div class="field-grid">
        <div class="form-field">
          <label class="required">{{ t('chat.closeout.failure_stage') }}</label>
          <BaseSelect v-model="form.failure_stage" :options="failureStageOptions" :disabled="saving" />
        </div>
        <div class="form-field">
          <label class="required">{{ t('chat.closeout.failure_reason') }}</label>
          <BaseSelect v-model="form.failure_reason" :options="failureReasonOptions" :disabled="saving" />
        </div>
      </div>

      <div class="form-field full-width" :class="{ invalid: errors.summary }">
        <label class="required">{{ t('chat.closeout.failure_summary') }}</label>
        <textarea
          v-model="form.failure_summary"
          :class="{ invalid: errors.summary }"
          :disabled="saving"
          :placeholder="t('chat.closeout.failure_summary_placeholder')"
          @input="errors.summary = false"
        />
      </div>
    </div>

    <div class="form-section">
      <div class="form-field" :class="{ invalid: errors.evidence }">
        <label class="required">{{ t('chat.closeout.failure_evidence') }}</label>
        <CloseoutEvidenceUploader :files="files" :disabled="saving" :invalid="errors.evidence" @update:files="updateFiles" />
      </div>
    </div>

    <div class="closeout-actions">
      <button type="button" class="btn-cancel" :disabled="saving" @click="emit('cancel')">
        {{ t('common.cancel') }}
      </button>
      <button type="submit" class="btn-submit btn-fail" :disabled="saving">
        <span v-if="saving" class="spinner" />
        {{ saving ? t('common.loading') : t('chat.closeout.submit_failure') }}
      </button>
    </div>
  </form>
</template>

<style scoped>
.closeout-form {
  display: flex;
  flex-direction: column;
  gap: 2rem;
}

.form-section {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.form-field label {
  font-size: 0.8125rem;
  font-weight: 600;
  color: #334155;
}

.form-field.invalid label,
.required::after {
  color: #ef4444;
}

.required::after {
  content: '*';
  margin-left: 4px;
  font-weight: 800;
}

.field-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
}

input,
textarea {
  width: 100%;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  padding: 0.625rem 0.875rem;
  font-size: 0.875rem;
  color: #0f172a;
  background: #ffffff;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
}

input:focus,
textarea:focus {
  outline: none;
  border-color: #ef4444;
  box-shadow: 0 0 0 4px rgba(239, 68, 68, 0.1);
  background: #ffffff;
}

input:hover,
textarea:hover {
  border-color: #cbd5e1;
}

input.invalid,
textarea.invalid {
  border-color: #ef4444;
  background: #fff1f2;
}

textarea {
  min-height: 100px;
  line-height: 1.5;
}

.closeout-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  margin-top: 1rem;
  padding-top: 1.5rem;
  border-top: 1px solid #f1f5f9;
}

.btn-cancel {
  padding: 0.625rem 1.25rem;
  font-size: 0.875rem;
  font-weight: 600;
  color: #64748b;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-cancel:hover:not(:disabled) {
  background: #f8fafc;
  color: #0f172a;
  border-color: #cbd5e1;
}

.btn-submit {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.625rem 1.5rem;
  font-size: 0.875rem;
  font-weight: 600;
  color: #ffffff;
  border: none;
  border-radius: 0.75rem;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.btn-fail {
  background: linear-gradient(to bottom, #ef4444, #dc2626);
  box-shadow: 0 1px 2px 0 rgba(239, 68, 68, 0.2);
}

.btn-fail:hover:not(:disabled) {
  background: linear-gradient(to bottom, #dc2626, #b91c1c);
  transform: translateY(-1px);
  box-shadow: 0 4px 6px -1px rgba(239, 68, 68, 0.2);
}

.btn-submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none !important;
}

.spinner {
  width: 1rem;
  height: 1rem;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-radius: 50%;
  border-top-color: #ffffff;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 720px) {
  .field-grid {
    grid-template-columns: 1fr;
  }
}
</style>
