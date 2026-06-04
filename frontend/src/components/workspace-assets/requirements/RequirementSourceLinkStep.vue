<script setup lang="ts">
import { reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RequirementManualPayload } from './requirementCreateTypes'

const props = defineProps<{
  loading?: boolean
  resetKey?: number
}>()

const emit = defineEmits<{
  submit: [payload: RequirementManualPayload]
  back: []
  cancel: []
}>()

const { t } = useI18n()
const form = reactive({
  title: '',
  body: '',
  sourceKind: 'source_link',
  sourceUri: '',
  sourceRef: '',
  priority: '',
  changeReason: '',
})

watch(
  () => props.resetKey,
  () => {
    form.title = ''
    form.body = ''
    form.sourceKind = 'source_link'
    form.sourceUri = ''
    form.sourceRef = ''
    form.priority = ''
    form.changeReason = ''
  },
)

function submit() {
  emit('submit', {
    title: form.title,
    body: form.body || null,
    status: 'DRAFT',
    priority: form.priority || null,
    source_kind: form.sourceKind || 'source_link',
    source_uri: form.sourceUri || null,
    source_ref: form.sourceRef || null,
    source_metadata: {
      created_from: 'source_link',
    },
    change_reason: form.changeReason || null,
  })
}
</script>

<template>
  <form class="step-form" @submit.prevent="submit">
    <div class="step-copy">
      <h4>{{ t('workspace_assets.requirements.create.source_link_title') }}</h4>
      <p>{{ t('workspace_assets.requirements.create.source_link_body') }}</p>
    </div>
    <label>
      <span>{{ t('workspace_assets.requirements.fields.title') }}</span>
      <input v-model="form.title" required maxlength="300" />
    </label>
    <label>
      <span>{{ t('workspace_assets.requirements.fields.source_uri') }}</span>
      <input v-model="form.sourceUri" required maxlength="1000" :placeholder="t('workspace_assets.requirements.placeholders.source_uri')" />
    </label>
    <div class="field-grid">
      <label>
        <span>{{ t('workspace_assets.requirements.fields.source_kind') }}</span>
        <input v-model="form.sourceKind" maxlength="80" :placeholder="t('workspace_assets.requirements.placeholders.source_kind')" />
      </label>
      <label>
        <span>{{ t('workspace_assets.requirements.fields.source_ref') }}</span>
        <input v-model="form.sourceRef" maxlength="300" />
      </label>
    </div>
    <label>
      <span>{{ t('workspace_assets.requirements.fields.description') }}</span>
      <textarea v-model="form.body" rows="4" />
    </label>
    <label>
      <span>{{ t('workspace_assets.requirements.fields.change_reason') }}</span>
      <textarea v-model="form.changeReason" rows="3" :placeholder="t('workspace_assets.requirements.placeholders.change_reason')" />
    </label>
    <p class="boundary-note">{{ t('workspace_assets.requirements.create.source_link_boundary') }}</p>
    <footer class="section-footer">
      <button type="button" class="ghost-action" @click="emit('back')">
        {{ t('workspace_assets.requirements.actions.back') }}
      </button>
      <div class="button-row">
        <button type="button" class="ghost-action" @click="emit('cancel')">
          {{ t('workspace_assets.requirements.actions.cancel') }}
        </button>
        <button type="submit" class="primary-action" :disabled="props.loading || !form.title.trim() || !form.sourceUri.trim()">
          {{ props.loading ? t('workspace_assets.requirements.actions.saving') : t('workspace_assets.requirements.actions.save_source_link') }}
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

input:focus,
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

.ghost-action {
  background: white;
  border: 1px solid #e2e8f0;
  color: #64748b;
}

.ghost-action:hover {
  background: #f8fafc;
  color: #0f172a;
}

.primary-action:disabled {
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
