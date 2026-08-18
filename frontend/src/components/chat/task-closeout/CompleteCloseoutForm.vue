<script setup lang="ts">
import { computed, reactive, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseSelect from '@/components/BaseSelect.vue'
import CloseoutEvidenceUploader from './CloseoutEvidenceUploader.vue'
import type { CompleteCloseoutPayload, LandingMethod } from '@/types/taskCloseout'

defineProps<{
  saving?: boolean
}>()

const emit = defineEmits<{
  submit: [payload: Omit<CompleteCloseoutPayload, 'evidence_attachments'>, files: File[]]
  cancel: []
}>()

const { t } = useI18n()
const files = shallowRef<File[]>([])
const errors = reactive({
  summary: false,
})

const form = reactive({
  completion_summary: '',
  landing_method: 'HUMAN_ADJUSTED' as LandingMethod,
  commit_id: '',
  pr_url: '',
  local_ref: '',
})

const landingOptions = computed(() => [
  { label: t('chat.closeout.landing.ai_implemented'), value: 'AI_IMPLEMENTED' },
  { label: t('chat.closeout.landing.human_adjusted'), value: 'HUMAN_ADJUSTED' },
  { label: t('chat.closeout.landing.ai_rewritten'), value: 'AI_REWRITTEN' },
  { label: t('chat.closeout.landing.ai_reference_only'), value: 'AI_REFERENCE_ONLY' },
])

function trimmed(value: string): string | null {
  const next = value.trim()
  return next || null
}

function updateFiles(nextFiles: File[]) {
  files.value = nextFiles
}

function submitForm() {
  errors.summary = !trimmed(form.completion_summary)
  if (errors.summary) return
  emit('submit', {
    completion_summary: form.completion_summary.trim(),
    landing_method: form.landing_method,
    commit_id: trimmed(form.commit_id),
    pr_url: trimmed(form.pr_url),
    local_ref: trimmed(form.local_ref),
  }, files.value)
}
</script>

<template>
  <form class="closeout-form" @submit.prevent="submitForm">
    <div class="form-section">
      <div class="form-field full-width" :class="{ invalid: errors.summary }">
        <label class="required">{{ t('chat.closeout.completion_summary') }}</label>
        <textarea
          v-model="form.completion_summary"
          :class="{ invalid: errors.summary }"
          :disabled="saving"
          :placeholder="t('chat.closeout.completion_summary_placeholder')"
          @input="errors.summary = false"
        />
      </div>

      <div class="form-field">
        <label class="required">{{ t('chat.closeout.landing_method') }}</label>
        <BaseSelect v-model="form.landing_method" :options="landingOptions" :disabled="saving" />
      </div>
    </div>

    <div class="form-section">
      <div class="field-grid">
        <div class="form-field">
          <label>{{ t('chat.closeout.commit_id') }}</label>
          <input v-model="form.commit_id" :disabled="saving" :placeholder="t('chat.closeout.commit_id_placeholder')" />
        </div>
        <div class="form-field">
          <label>{{ t('chat.closeout.pr_url') }}</label>
          <input v-model="form.pr_url" :disabled="saving" :placeholder="t('chat.closeout.pr_url_placeholder')" />
        </div>
        <div class="form-field">
          <label>{{ t('chat.closeout.local_ref') }}</label>
          <input v-model="form.local_ref" :disabled="saving" :placeholder="t('chat.closeout.local_ref_placeholder')" />
        </div>
      </div>

      <div class="form-field">
        <label>{{ t('chat.closeout.main_evidence') }}</label>
        <CloseoutEvidenceUploader :files="files" :disabled="saving" @update:files="updateFiles" />
      </div>
    </div>

    <div class="closeout-actions">
      <button type="button" class="btn-cancel" :disabled="saving" @click="emit('cancel')">
        {{ t('common.cancel') }}
      </button>
      <button type="submit" class="btn-submit btn-success" :disabled="saving">
        <span v-if="saving" class="spinner" />
        {{ saving ? t('common.loading') : t('chat.closeout.submit_complete') }}
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
  grid-template-columns: repeat(3, minmax(0, 1fr));
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
  border-color: #3b82f6;
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.1);
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

.btn-success {
  background: linear-gradient(to bottom, #10b981, #059669);
  box-shadow: 0 1px 2px 0 rgba(16, 185, 129, 0.2);
}

.btn-success:hover:not(:disabled) {
  background: linear-gradient(to bottom, #059669, #047857);
  transform: translateY(-1px);
  box-shadow: 0 4px 6px -1px rgba(16, 185, 129, 0.2);
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

@media (max-width: 860px) {
  .field-grid {
    grid-template-columns: 1fr;
  }
}
</style>
