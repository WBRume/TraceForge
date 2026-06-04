<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { Sparkles } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import type { RequirementEditableStatus } from '@/types/workspaceAssets'
import type { RequirementManualPayload, RequirementPreviewPayload } from './requirementCreateTypes'

const props = defineProps<{
  loading?: boolean
  resetKey?: number
}>()

const emit = defineEmits<{
  submit: [payload: RequirementManualPayload]
  preview: [payload: RequirementPreviewPayload]
  back: []
  cancel: []
}>()

const { t } = useI18n()
const statusOptions: RequirementEditableStatus[] = [
  'DRAFT',
  'READY',
  'IN_PROGRESS',
  'VERIFIED',
  'REJECTED',
  'ARCHIVED',
]

const form = reactive({
  title: '',
  body: '',
  acceptanceCriteriaText: '',
  priority: '',
  status: 'DRAFT' as RequirementEditableStatus,
  changeReason: '',
})

const previewText = computed(() => [
  form.title.trim() ? `# ${form.title.trim()}` : '',
  form.body.trim(),
  form.acceptanceCriteriaText.trim()
    ? `Acceptance Criteria:\n${form.acceptanceCriteriaText.trim()}`
    : '',
].filter(Boolean).join('\n\n'))

const canPreview = computed(() => Boolean(form.body.trim() || form.acceptanceCriteriaText.trim()))

watch(
  () => props.resetKey,
  () => {
    form.title = ''
    form.body = ''
    form.acceptanceCriteriaText = ''
    form.priority = ''
    form.status = 'DRAFT'
    form.changeReason = ''
  },
)

function submit() {
  emit('submit', {
    title: form.title,
    body: form.body || null,
    acceptance_criteria: form.acceptanceCriteriaText
      .split('\n')
      .map((item) => item.trim())
      .filter(Boolean),
    priority: form.priority || null,
    status: form.status,
    change_reason: form.changeReason || null,
  })
}

function createPreview() {
  emit('preview', {
    file: null,
    text: previewText.value,
    source_kind: 'pasted_text',
    source_uri: null,
    source_ref: null,
  })
}
</script>

<template>
  <form class="step-form" @submit.prevent="submit">
    <div class="step-copy">
      <h4>{{ t('workspace_assets.requirements.create.manual_step_title') }}</h4>
      <p>{{ t('workspace_assets.requirements.create.manual_step_body') }}</p>
    </div>

    <label>
      <span>{{ t('workspace_assets.requirements.fields.title') }}</span>
      <input v-model="form.title" required maxlength="300" />
    </label>
    <label>
      <span>{{ t('workspace_assets.requirements.fields.description') }}</span>
      <textarea v-model="form.body" rows="5" />
    </label>
    <label>
      <span>{{ t('workspace_assets.requirements.fields.acceptance_criteria') }}</span>
      <textarea
        v-model="form.acceptanceCriteriaText"
        rows="4"
        :placeholder="t('workspace_assets.requirements.placeholders.criteria')"
      />
    </label>
    <div class="field-grid">
      <label>
        <span>{{ t('workspace_assets.requirements.fields.status') }}</span>
        <select v-model="form.status">
          <option v-for="option in statusOptions" :key="option" :value="option">{{ option }}</option>
        </select>
      </label>
      <label>
        <span>{{ t('workspace_assets.requirements.fields.priority') }}</span>
        <input v-model="form.priority" maxlength="40" :placeholder="t('workspace_assets.requirements.placeholders.priority')" />
      </label>
    </div>
    <label>
      <span>{{ t('workspace_assets.requirements.fields.change_reason') }}</span>
      <textarea v-model="form.changeReason" rows="3" />
    </label>
    <p class="boundary-note">{{ t('workspace_assets.requirements.create.coverage_boundary') }}</p>
    <footer class="section-footer">
      <button type="button" class="ghost-action" @click="emit('back')">
        {{ t('workspace_assets.requirements.actions.back') }}
      </button>
      <div class="button-row">
        <button type="button" class="ghost-action" @click="emit('cancel')">
          {{ t('workspace_assets.requirements.actions.cancel') }}
        </button>
        <button
          type="button"
          class="secondary-action"
          :disabled="props.loading || !canPreview"
          @click="createPreview"
        >
          <Sparkles :size="16" />
          {{ props.loading ? t('workspace_assets.requirements.actions.preview_running') : t('workspace_assets.requirements.actions.create_preview') }}
        </button>
        <button type="submit" class="primary-action" :disabled="props.loading || !form.title.trim()">
          {{ props.loading ? t('workspace_assets.requirements.actions.saving') : t('workspace_assets.requirements.actions.save') }}
        </button>
      </div>
    </footer>
  </form>
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

.field-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
}

label {
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

input,
select,
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
}

input:focus,
select:focus,
textarea:focus {
  border-color: #0ea5e9;
  outline: none;
}

textarea {
  resize: vertical;
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
  .field-grid {
    grid-template-columns: 1fr;
  }
  .section-footer {
    flex-direction: column;
    align-items: stretch;
  }
  .button-row {
    flex-direction: column;
  }
}
</style>
