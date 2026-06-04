<script setup lang="ts">
import { reactive, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseSelect from '@/components/BaseSelect.vue'
import type {
  DecisionMutationPayload,
  HumanDeltaLight,
  EvidenceLight,
  TaskRequirementLink,
} from '@/types/workspaceAssets'

const props = defineProps<{
  requirementLinks: TaskRequirementLink[]
  humanDeltas: HumanDeltaLight[]
  evidence: EvidenceLight[]
  saving?: boolean
  hideActions?: boolean
}>()

const emit = defineEmits<{
  submit: [payload: DecisionMutationPayload]
  cancel: []
}>()

defineExpose({
  submit,
})

const { t } = useI18n()

const form = reactive({
  title: '',
  body: '',
  rationale: '',
  impact_scope: '',
  status: 'ACCEPTED',
  requirement_id: '',
  human_delta_id: '',
  source_evidence_id: '',
  promote_candidate: false,
  change_reason: '',
})
const touched = reactive({ title: false })
const titleInvalid = computed(() => touched.title && !form.title.trim())

const statusOptions = computed(() => [
  { label: t('workspace_assets.task_detail.workbench.status.accepted'), value: 'ACCEPTED' },
  { label: t('workspace_assets.task_detail.workbench.status.proposed'), value: 'PROPOSED' },
  { label: t('workspace_assets.task_detail.workbench.status.rejected'), value: 'REJECTED' },
  { label: t('workspace_assets.task_detail.workbench.status.superseded'), value: 'SUPERSEDED' },
])

const requirementOptions = computed(() =>
  props.requirementLinks.map(link => ({
    label: link.requirement?.title || link.requirement_id,
    value: link.requirement_id,
  }))
)

const humanDeltaOptions = computed(() =>
  props.humanDeltas.map(delta => ({
    label: delta.title || delta.id,
    value: delta.id,
  }))
)

const evidenceOptions = computed(() =>
  props.evidence.map(item => ({
    label: item.title || item.id,
    value: item.id,
  }))
)

function submit() {
  touched.title = true
  if (!form.title.trim()) return
  emit('submit', {
    title: form.title.trim(),
    body: form.body.trim() || null,
    rationale: form.rationale.trim() || null,
    impact_scope: form.impact_scope.trim() || null,
    status: form.status,
    requirement_id: form.requirement_id || null,
    human_delta_id: form.human_delta_id || null,
    source_evidence_id: form.source_evidence_id || null,
    promote_candidate: form.promote_candidate,
    change_reason: form.change_reason.trim() || null,
    source_type: 'TASK_DETAIL_BACKFILL',
  })
}
</script>

<template>
  <form class="backfill-form" @submit.prevent="submit">
    <div class="form-section">
      <div class="form-field" :class="{ invalid: titleInvalid }">
        <label class="required">{{ t('workspace_assets.task_detail.workbench.fields.title') }}</label>
        <input
          v-model="form.title"
          type="text"
          :disabled="saving"
          :placeholder="t('workspace_assets.task_detail.workbench.backfill_dialog.placeholder_title')"
          @blur="touched.title = true"
          @input="touched.title = false"
        />
      </div>

      <div class="form-field">
        <label>{{ t('workspace_assets.task_detail.workbench.fields.decision_body') }}</label>
        <textarea
          v-model="form.body"
          :disabled="saving"
          :placeholder="t('workspace_assets.task_detail.workbench.backfill_dialog.placeholder_body')"
          rows="3"
        />
      </div>

      <div class="field-grid">
        <div class="form-field">
          <label>{{ t('workspace_assets.task_detail.workbench.fields.status') }}</label>
          <BaseSelect v-model="form.status" :options="statusOptions" :disabled="saving" />
        </div>
        <div class="form-field">
          <label>{{ t('workspace_assets.task_detail.workbench.fields.impact_scope') }}</label>
          <input
            v-model="form.impact_scope"
            type="text"
            :disabled="saving"
            :placeholder="t('workspace_assets.task_detail.workbench.backfill_dialog.placeholder_impact_scope')"
          />
        </div>
        <div class="form-field">
          <label>{{ t('workspace_assets.task_detail.workbench.fields.rationale') }}</label>
          <input
            v-model="form.rationale"
            type="text"
            :disabled="saving"
            :placeholder="t('workspace_assets.task_detail.workbench.backfill_dialog.placeholder_rationale')"
          />
        </div>
      </div>
    </div>

    <div class="form-section">
      <div class="field-grid">
        <div class="form-field">
          <label>{{ t('workspace_assets.task_detail.workbench.fields.requirement') }}</label>
          <BaseSelect
            v-model="form.requirement_id"
            :options="requirementOptions"
            :disabled="saving"
            :placeholder="t('workspace_assets.task_detail.workbench.backfill_dialog.placeholder_requirement')"
          />
        </div>
        <div class="form-field">
          <label>{{ t('workspace_assets.task_detail.workbench.fields.human_delta') }}</label>
          <BaseSelect
            v-model="form.human_delta_id"
            :options="humanDeltaOptions"
            :disabled="saving"
            :placeholder="t('workspace_assets.task_detail.workbench.backfill_dialog.placeholder_human_delta')"
          />
        </div>
        <div class="form-field">
          <label>{{ t('workspace_assets.task_detail.workbench.fields.source_evidence') }}</label>
          <BaseSelect
            v-model="form.source_evidence_id"
            :options="evidenceOptions"
            :disabled="saving"
            :placeholder="t('workspace_assets.task_detail.workbench.backfill_dialog.placeholder_evidence')"
          />
        </div>
      </div>

      <div class="form-field">
        <label>{{ t('workspace_assets.task_detail.workbench.fields.reason') }}</label>
        <input
          v-model="form.change_reason"
          type="text"
          :disabled="saving"
          :placeholder="t('workspace_assets.task_detail.workbench.backfill_dialog.placeholder_reason')"
        />
      </div>

      <div class="form-field toggle-field">
        <label>{{ t('workspace_assets.task_detail.workbench.fields.promote_candidate') }}</label>
        <button
          type="button"
          class="toggle-btn"
          :class="{ active: form.promote_candidate }"
          :disabled="saving"
          @click="form.promote_candidate = !form.promote_candidate"
        >
          <span class="toggle-track">
            <span class="toggle-thumb" />
          </span>
          <span class="toggle-label">{{ form.promote_candidate ? t('common.yes') : t('common.no') }}</span>
        </button>
      </div>
    </div>

    <div v-if="!hideActions" class="form-actions">
      <button type="button" class="btn-cancel" :disabled="saving" @click="emit('cancel')">
        {{ t('common.cancel') }}
      </button>
      <button type="submit" class="btn-submit btn-primary" :disabled="saving">
        <span v-if="saving" class="spinner" />
        {{ saving ? t('common.saving') : t('workspace_assets.task_detail.workbench.backfill_dialog.submit') }}
      </button>
    </div>
  </form>
</template>

<style scoped>
.backfill-form {
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
  min-height: 80px;
  line-height: 1.5;
  resize: vertical;
}

.toggle-field {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
}

.toggle-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0;
  background: none;
  border: none;
  cursor: pointer;
}

.toggle-track {
  position: relative;
  width: 2.75rem;
  height: 1.5rem;
  background: #e2e8f0;
  border-radius: 0.75rem;
  transition: background 0.2s;
}

.toggle-btn.active .toggle-track {
  background: #3b82f6;
}

.toggle-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 1.25rem;
  height: 1.25rem;
  background: #ffffff;
  border-radius: 50%;
  box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1);
  transition: transform 0.2s;
}

.toggle-btn.active .toggle-thumb {
  transform: translateX(1.25rem);
}

.toggle-label {
  font-size: 0.8125rem;
  font-weight: 600;
  color: #64748b;
}

.form-actions {
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

.btn-primary {
  background: linear-gradient(to bottom, #3b82f6, #2563eb);
  box-shadow: 0 1px 2px 0 rgba(59, 130, 246, 0.2);
}

.btn-primary:hover:not(:disabled) {
  background: linear-gradient(to bottom, #2563eb, #1d4ed8);
  transform: translateY(-1px);
  box-shadow: 0 4px 6px -1px rgba(59, 130, 246, 0.2);
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

@media (max-width: 640px) {
  .field-grid {
    grid-template-columns: 1fr;
  }
}
</style>
