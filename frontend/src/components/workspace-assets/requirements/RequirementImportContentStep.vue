<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { FileText, Sparkles, UploadCloud } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import type {
  RequirementDirectImportPayload,
  RequirementPreviewPayload,
} from './requirementCreateTypes'

const props = defineProps<{
  loading?: boolean
  resetKey?: number
}>()

const emit = defineEmits<{
  direct: [payload: RequirementDirectImportPayload]
  preview: [payload: RequirementPreviewPayload]
  back: []
  cancel: []
}>()

const { t } = useI18n()
const fileInput = shallowRef<HTMLInputElement | null>(null)
const selectedFile = shallowRef<File | null>(null)
const changeReason = shallowRef('')

const hasContent = computed(() => Boolean(selectedFile.value))

watch(
  () => props.resetKey,
  () => {
    changeReason.value = ''
    selectedFile.value = null
    if (fileInput.value) fileInput.value.value = ''
  },
)

function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement | null
  selectedFile.value = input?.files?.[0] || null
}

function directImport() {
  emit('direct', {
    file: selectedFile.value,
    text: null,
    source_kind: 'document',
    source_uri: null,
    source_ref: null,
    change_reason: changeReason.value || null,
  })
}

function createPreview() {
  emit('preview', {
    file: selectedFile.value,
    text: null,
    source_kind: 'document',
    source_uri: null,
    source_ref: null,
  })
}
</script>

<template>
  <section class="step-form">
    <div class="step-copy">
      <h4>{{ t('workspace_assets.requirements.create.file_step_title') }}</h4>
      <p>{{ t('workspace_assets.requirements.create.file_step_body') }}</p>
    </div>

    <label class="upload-box">
      <UploadCloud :size="20" />
      <span>{{ t('workspace_assets.requirements.create.file_input') }}</span>
      <input
        ref="fileInput"
        type="file"
        accept=".docx,.md,.markdown,.txt,text/plain,text/markdown"
        @change="handleFileChange"
      />
      <small v-if="selectedFile">{{ selectedFile.name }}</small>
    </label>

    <label>
      <span>{{ t('workspace_assets.requirements.fields.change_reason') }}</span>
      <textarea v-model="changeReason" rows="3" :placeholder="t('workspace_assets.requirements.placeholders.change_reason')" />
    </label>

    <p class="boundary-note">{{ t('workspace_assets.requirements.create.ai_preview_boundary') }}</p>

    <footer class="section-footer">
      <button type="button" class="ghost-action" @click="emit('back')">
        {{ t('workspace_assets.requirements.actions.back') }}
      </button>
      <div class="button-row">
        <button type="button" class="secondary-action" :disabled="props.loading || !hasContent" @click="directImport">
          <FileText :size="16" />
          {{ props.loading ? t('workspace_assets.requirements.actions.importing') : t('workspace_assets.requirements.actions.direct_import') }}
        </button>
        <button type="button" class="primary-action" :disabled="props.loading || !hasContent" @click="createPreview">
          <Sparkles :size="16" />
          {{ props.loading ? t('workspace_assets.requirements.actions.preview_running') : t('workspace_assets.requirements.actions.create_preview') }}
        </button>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.step-form {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.step-copy h4 {
  font-family: 'Poppins', sans-serif;
  font-size: 1.125rem;
  font-weight: 700;
  margin: 0 0 0.5rem;
  color: #0f172a;
}

.step-copy p {
  margin: 0;
  color: #64748b;
  font-size: 0.875rem;
  line-height: 1.6;
}

.upload-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 2.5rem;
  border: 2px dashed #e2e8f0;
  border-radius: 1.5rem;
  background: #f8fafc;
  color: #64748b;
  cursor: pointer;
  transition: all 0.3s;
}

.upload-box:hover {
  border-color: #0ea5e9;
  background: #f0f9ff;
  color: #0ea5e9;
}

.upload-box svg {
  margin-bottom: 0.75rem;
}

.upload-box span {
  font-weight: 600;
}

.upload-box input {
  display: none;
}

.upload-box small {
  margin-top: 0.5rem;
  color: #0ea5e9;
  font-weight: 700;
}

label:not(.upload-box) {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

label span {
  font-size: 0.8125rem;
  font-weight: 700;
  color: #475569;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

textarea {
  width: 100%;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  padding: 0.75rem 1rem;
  color: #0f172a;
  font-family: inherit;
  font-size: 0.9375rem;
  background: white;
  transition: border-color 0.3s;
  resize: vertical;
}

textarea:focus {
  border-color: #0ea5e9;
  outline: none;
}

.boundary-note {
  margin: 0;
  padding: 1rem;
  border-radius: 1rem;
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  color: #64748b;
  font-size: 0.8125rem;
  line-height: 1.5;
}

.section-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-top: 1rem;
  padding-top: 1.5rem;
  border-top: 1px solid #f1f5f9;
}

.button-row {
  display: flex;
  gap: 0.75rem;
}

.primary-action,
.secondary-action,
.ghost-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.75rem 1.25rem;
  border-radius: 0.75rem;
  font-weight: 700;
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.3s;
}

.primary-action {
  background: #0ea5e9;
  color: white;
  border: none;
}

.primary-action:hover:not(:disabled) {
  background: #0284c7;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.4);
}

.secondary-action {
  background: #f0f9ff;
  border: 1px solid rgba(14, 165, 233, 0.2);
  color: #0369a1;
}

.secondary-action:hover:not(:disabled) {
  background: #e0f2fe;
}

.ghost-action {
  background: white;
  border: 1px solid #e2e8f0;
  color: #64748b;
}

.ghost-action:hover {
  background: #f8fafc;
  color: #0f172a;
}

.primary-action:disabled,
.secondary-action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 640px) {
  .section-footer {
    flex-direction: column;
    align-items: stretch;
  }
  .button-row {
    flex-direction: column;
  }
}
</style>
