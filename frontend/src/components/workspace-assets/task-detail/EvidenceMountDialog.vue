<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { X, FileCheck, GitBranch, UserCheck, AlertTriangle, Terminal, TestTube, Wrench } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import type { EvidenceMutationPayload } from '@/types/workspaceAssets'

type EvidenceTypeOption = {
  value: string
  label: string
  icon: typeof FileCheck
  evidenceType: string
  sourceType: string
  needsRef: boolean
  needsUri: boolean
  needsPath: boolean
  needsSummary: boolean
}

const props = defineProps<{
  show: boolean
  taskStatus: string
  saving?: boolean
}>()

const emit = defineEmits<{
  close: []
  submit: [payload: EvidenceMutationPayload]
}>()

const { t } = useI18n()

const selectedType = ref('')
const form = ref({
  title: '',
  summary: '',
  source_ref: '',
  source_uri: '',
  source_path: '',
})

const errors = ref({
  title: false,
  source: false,
})

const isDone = computed(() => (props.taskStatus || '').toUpperCase() === 'DONE')
const isFailed = computed(() => (props.taskStatus || '').toUpperCase() === 'FAILED')

const evidenceTypeOptions = computed<EvidenceTypeOption[]>(() => {
  const baseOptions: EvidenceTypeOption[] = []

  if (isDone.value) {
    baseOptions.push(
      {
        value: 'commit',
        label: t('workspace_assets.task_detail.workbench.evidence_mount.type_commit'),
        icon: GitBranch,
        evidenceType: 'CODE',
        sourceType: 'COMMIT',
        needsRef: true,
        needsUri: false,
        needsPath: false,
        needsSummary: true,
      },
      {
        value: 'mr',
        label: t('workspace_assets.task_detail.workbench.evidence_mount.type_mr'),
        icon: GitBranch,
        evidenceType: 'CODE',
        sourceType: 'MR',
        needsRef: false,
        needsUri: true,
        needsPath: false,
        needsSummary: true,
      },
      {
        value: 'confirm',
        label: t('workspace_assets.task_detail.workbench.evidence_mount.type_confirm'),
        icon: UserCheck,
        evidenceType: 'HUMAN_CONFIRMATION',
        sourceType: 'HUMAN_CONFIRMATION',
        needsRef: false,
        needsUri: false,
        needsPath: false,
        needsSummary: true,
      },
      {
        value: 'test',
        label: t('workspace_assets.task_detail.workbench.evidence_mount.type_test'),
        icon: TestTube,
        evidenceType: 'TEST',
        sourceType: 'TEST_REPORT',
        needsRef: false,
        needsUri: false,
        needsPath: true,
        needsSummary: true,
      },
    )
  }

  if (isFailed.value) {
    baseOptions.push(
      {
        value: 'failure_log',
        label: t('workspace_assets.task_detail.workbench.evidence_mount.type_failure_log'),
        icon: AlertTriangle,
        evidenceType: 'FAILURE',
        sourceType: 'OTHER',
        needsRef: false,
        needsUri: false,
        needsPath: true,
        needsSummary: true,
      },
      {
        value: 'runtime_log',
        label: t('workspace_assets.task_detail.workbench.evidence_mount.type_runtime_log'),
        icon: Terminal,
        evidenceType: 'RUNTIME',
        sourceType: 'RUN_LOG',
        needsRef: false,
        needsUri: false,
        needsPath: true,
        needsSummary: true,
      },
      {
        value: 'compile_error',
        label: t('workspace_assets.task_detail.workbench.evidence_mount.type_compile_error'),
        icon: Wrench,
        evidenceType: 'FAILURE',
        sourceType: 'OTHER',
        needsRef: false,
        needsUri: false,
        needsPath: true,
        needsSummary: true,
      },
      {
        value: 'device_test',
        label: t('workspace_assets.task_detail.workbench.evidence_mount.type_device_test'),
        icon: FileCheck,
        evidenceType: 'TEST',
        sourceType: 'TEST_REPORT',
        needsRef: false,
        needsUri: false,
        needsPath: true,
        needsSummary: true,
      },
    )
  }

  return baseOptions
})

const selectedConfig = computed(() => {
  return evidenceTypeOptions.value.find(opt => opt.value === selectedType.value)
})

const typeSelectOptions = computed(() =>
  evidenceTypeOptions.value.map(opt => ({
    label: opt.label,
    value: opt.value,
  }))
)

watch(() => props.show, (val) => {
  if (val) {
    selectedType.value = evidenceTypeOptions.value[0]?.value || ''
    form.value = { title: '', summary: '', source_ref: '', source_uri: '', source_path: '' }
    errors.value = { title: false, source: false }
  }
})

function close() {
  emit('close')
}

function submitForm() {
  const config = selectedConfig.value
  if (!config) return

  errors.value.title = !form.value.title.trim()

  let sourceValid = true
  if (config.needsRef) sourceValid = !!form.value.source_ref.trim()
  else if (config.needsUri) sourceValid = !!form.value.source_uri.trim()
  else if (config.needsPath) sourceValid = !!form.value.source_path.trim()
  errors.value.source = !sourceValid

  if (errors.value.title || errors.value.source) return

  emit('submit', {
    title: form.value.title.trim(),
    summary: form.value.summary.trim() || null,
    evidence_type: config.evidenceType,
    source_type: config.sourceType,
    source_ref: form.value.source_ref.trim() || null,
    source_uri: form.value.source_uri.trim() || null,
    source_path: form.value.source_path.trim() || null,
    confirmed: selectedType.value === 'confirm',
  })
}
</script>

<template>
  <Teleport to="body">
    <div v-if="show" class="modal-overlay" @pointerdown.self="close">
      <section class="modal glass-panel evidence-modal" role="dialog" aria-modal="true">
        <header class="modal-header">
          <div class="header-pattern" />
          <div class="header-icon" :class="isFailed ? 'fail' : 'success'">
            <div class="icon-ring" />
            <FileCheck :size="24" />
          </div>

          <div class="header-text">
            <span class="eyebrow" :class="isFailed ? 'text-fail' : 'text-success'">
              {{ t('workspace_assets.task_detail.workbench.evidence.eyebrow') }}
            </span>
            <h2>{{ t('workspace_assets.task_detail.workbench.evidence_mount.title') }}</h2>
            <p class="description">{{ t('workspace_assets.task_detail.workbench.evidence_mount.description') }}</p>
          </div>

          <button type="button" class="close-btn" :disabled="saving" @click="close">
            <X :size="20" />
          </button>
        </header>

        <div class="modal-content">
          <form class="evidence-form" @submit.prevent="submitForm">
            <div class="form-section">
              <div class="form-field">
                <label class="required">{{ t('workspace_assets.task_detail.workbench.evidence_mount.evidence_type') }}</label>
                <BaseSelect
                  v-model="selectedType"
                  :options="typeSelectOptions"
                  :disabled="saving"
                />
              </div>

              <div v-if="selectedConfig" class="selected-type-hint">
                <component :is="selectedConfig.icon" :size="16" />
                <span>{{ selectedConfig.label }}</span>
              </div>
            </div>

            <div class="form-section">
              <div class="form-field" :class="{ invalid: errors.title }">
                <label class="required">{{ t('workspace_assets.task_detail.workbench.fields.title') }}</label>
                <input
                  v-model="form.title"
                  type="text"
                  :disabled="saving"
                  :placeholder="t('workspace_assets.task_detail.workbench.evidence_mount.placeholder_title')"
                  @input="errors.title = false"
                />
              </div>

              <div v-if="selectedConfig?.needsRef" class="form-field" :class="{ invalid: errors.source }">
                <label class="required">{{ t('workspace_assets.task_detail.workbench.evidence_dialog.field_commit_sha') }}</label>
                <input
                  v-model="form.source_ref"
                  type="text"
                  :disabled="saving"
                  placeholder="abc1234"
                  @input="errors.source = false"
                />
              </div>

              <div v-if="selectedConfig?.needsUri" class="form-field" :class="{ invalid: errors.source }">
                <label class="required">{{ t('workspace_assets.task_detail.workbench.evidence_dialog.field_mr_url') }}</label>
                <input
                  v-model="form.source_uri"
                  type="text"
                  :disabled="saving"
                  placeholder="https://..."
                  @input="errors.source = false"
                />
              </div>

              <div v-if="selectedConfig?.needsPath" class="form-field" :class="{ invalid: errors.source }">
                <label class="required">{{ t('workspace_assets.task_detail.workbench.fields.path') }}</label>
                <input
                  v-model="form.source_path"
                  type="text"
                  :disabled="saving"
                  :placeholder="t('workspace_assets.task_detail.workbench.evidence_dialog.placeholder_path')"
                  @input="errors.source = false"
                />
              </div>

              <div v-if="selectedConfig?.needsSummary" class="form-field">
                <label>{{ t('workspace_assets.task_detail.workbench.fields.summary') }}</label>
                <textarea
                  v-model="form.summary"
                  :disabled="saving"
                  :placeholder="t('workspace_assets.task_detail.workbench.evidence_mount.placeholder_summary')"
                  rows="3"
                />
              </div>
            </div>

            <div class="form-actions">
              <button type="button" class="btn-cancel" :disabled="saving" @click="close">
                {{ t('common.cancel') }}
              </button>
              <button type="submit" class="btn-submit" :class="isFailed ? 'btn-fail' : 'btn-success'" :disabled="saving">
                <span v-if="saving" class="spinner" />
                {{ saving ? t('common.saving') : t('workspace_assets.task_detail.workbench.evidence_mount.submit') }}
              </button>
            </div>
          </form>

          <Transition name="fade">
            <div v-if="errors.title || errors.source" class="validation-error">
              <div class="error-indicator" />
              <span>{{ t('workspace_assets.task_detail.workbench.evidence_dialog.title_required') }}</span>
            </div>
          </Transition>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(8px);
  animation: fade-in 0.3s ease-out;
}

@keyframes fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

.modal {
  width: min(640px, 100%);
  max-height: min(800px, 92vh);
  background: #ffffff;
  border-radius: 1.5rem;
  box-shadow:
    0 10px 15px -3px rgba(0, 0, 0, 0.1),
    0 25px 50px -12px rgba(0, 0, 0, 0.25);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.2);
  animation: modal-enter 0.4s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes modal-enter {
  from {
    opacity: 0;
    transform: scale(0.95) translateY(15px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

.modal-header {
  position: relative;
  display: flex;
  align-items: center;
  gap: 1.25rem;
  padding: 1.5rem 2rem;
  border-bottom: 1px solid #f1f5f9;
  background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
  overflow: hidden;
}

.header-pattern {
  position: absolute;
  inset: 0;
  opacity: 0.03;
  pointer-events: none;
  background-image: radial-gradient(#0f172a 1px, transparent 0);
  background-size: 20px 20px;
}

.header-icon {
  position: relative;
  width: 2.75rem;
  height: 2.75rem;
  border-radius: 0.875rem;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  z-index: 1;
}

.icon-ring {
  position: absolute;
  inset: -3px;
  border: 2px solid currentColor;
  border-radius: 1rem;
  opacity: 0.1;
}

.header-icon.success {
  background: #f0fdf4;
  color: #10b981;
}

.header-icon.fail {
  background: #fef2f2;
  color: #ef4444;
}

.header-text {
  flex: 1;
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.eyebrow {
  font-size: 0.65rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  display: block;
}

.text-success { color: #10b981; }
.text-fail { color: #ef4444; }

h2 {
  font-family: 'Poppins', sans-serif;
  font-size: 1.25rem;
  font-weight: 700;
  margin: 0;
  color: #0f172a;
  letter-spacing: -0.01em;
}

.description {
  margin: 2px 0 0;
  color: #64748b;
  font-size: 0.875rem;
  line-height: 1.4;
}

.close-btn {
  position: relative;
  width: 2.5rem;
  height: 2.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 0.875rem;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  z-index: 1;
}

.close-btn:hover {
  background: #f8fafc;
  color: #0f172a;
  border-color: #cbd5e1;
  transform: translateY(-1px);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}

.modal-content {
  flex: 1;
  overflow-y: auto;
  padding: 2rem;
}

.evidence-form {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.form-section {
  display: flex;
  flex-direction: column;
  gap: 1rem;
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
  box-sizing: border-box;
}

input:focus,
textarea:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.1);
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
  min-height: 80px;
  line-height: 1.5;
  resize: vertical;
}

.selected-type-hint {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  border-radius: 0.5rem;
  color: #0369a1;
  font-size: 0.8125rem;
  font-weight: 500;
  width: fit-content;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
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

.validation-error {
  margin-top: 1rem;
  padding: 1rem 1.25rem;
  background: #fff1f2;
  border: 1px solid #fecdd3;
  border-radius: 0.75rem;
  color: #be123c;
  font-size: 0.875rem;
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.error-indicator {
  width: 4px;
  height: 1rem;
  background: #e11d48;
  border-radius: 2px;
  flex-shrink: 0;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@media (max-width: 640px) {
  .modal-header {
    padding: 1.5rem;
    gap: 1rem;
  }

  h2 {
    font-size: 1.125rem;
  }

  .modal-content {
    padding: 1.5rem;
  }
}
</style>
