<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Loader2, Save, CheckCircle2, SendHorizonal, ExternalLink, ClipboardList } from 'lucide-vue-next'

const props = defineProps<{
  task: any
  result: any
  loading: boolean
  saving: boolean
  caseCreating: boolean
  caseLink: string
}>()

const emit = defineEmits<{
  save: []
  confirm: []
  confirmAndSubmit: []
  openCase: [caseId: string]
}>()

const { t } = useI18n()

const taskMeta = computed(() => (props.task?.task_meta_json && typeof props.task.task_meta_json === 'object' ? props.task.task_meta_json : {}))
const phenomenon = computed(() => String(taskMeta.value.phenomenon || ''))
const priority = computed(() => String(taskMeta.value.priority || ''))
const resultConfirmed = computed(() => props.result?.status === 'CONFIRMED')
const priorityClass = computed(() => `prio-${String(priority.value || 'p2').toLowerCase()}`)
</script>

<template>
  <div class="diagnosis-panel glass-panel">
    <div class="diagnosis-header">
      <div class="header-title-row">
        <ClipboardList class="w-5 h-5 diagnosis-icon" />
        <div class="header-title-text">
          <div class="title-line">
            <span class="panel-title">{{ t('diagnosis.panel_title') }}</span>
            <span v-if="priority" class="priority-pill" :class="priorityClass">{{ priority }}</span>
            <span v-if="resultConfirmed" class="confirmed-pill">{{ t('diagnosis.result_confirmed') }}</span>
            <span v-else class="draft-pill">{{ t('diagnosis.result_draft') }}</span>
          </div>
          <div v-if="phenomenon" class="phenomenon-preview">
            <span class="phenomenon-label">{{ t('diagnosis.phenomenon') }}:</span>
            <span class="phenomenon-text">{{ phenomenon }}</span>
          </div>
        </div>
      </div>
    </div>

    <div v-if="loading" class="diagnosis-state">
      <Loader2 class="w-4 h-4 spin" />
      <span>{{ t('common.loading') }}</span>
    </div>

    <div v-else-if="!result" class="diagnosis-state">
      <span>{{ t('diagnosis.result_load_failed') }}</span>
    </div>

    <div v-else class="diagnosis-body">
      <div class="field-group">
        <label>{{ t('diagnosis.root_cause') }}</label>
        <textarea v-model="result.root_cause" class="input-field diagnosis-textarea" rows="3" :placeholder="t('diagnosis.root_cause_placeholder')" />
      </div>
      <div class="field-group">
        <label>{{ t('diagnosis.evidence_chain') }}</label>
        <textarea v-model="result.evidence_chain" class="input-field diagnosis-textarea" rows="3" :placeholder="t('diagnosis.evidence_chain_placeholder')" />
      </div>
      <div class="field-group">
        <label>{{ t('diagnosis.fix_suggestion') }}</label>
        <textarea v-model="result.fix_suggestion" class="input-field diagnosis-textarea" rows="2" :placeholder="t('diagnosis.fix_suggestion_placeholder')" />
      </div>
      <div class="field-group">
        <label class="confidence-label">
          {{ t('diagnosis.confidence') }}
          <span class="confidence-value">{{ result.confidence }}%</span>
        </label>
        <el-slider v-model="result.confidence" :min="0" :max="100" :step="5" />
      </div>

      <div class="diagnosis-actions">
        <button class="btn-secondary" :disabled="saving || caseCreating" @click="emit('save')">
          <Save v-if="!saving" class="w-4 h-4" />
          <Loader2 v-else class="w-4 h-4 spin" />
          {{ t('diagnosis.save_draft') }}
        </button>
        <button class="btn-primary" :disabled="saving || caseCreating" @click="emit('confirm')">
          <CheckCircle2 v-if="!caseCreating" class="w-4 h-4" />
          <Loader2 v-else class="w-4 h-4 spin" />
          {{ t('diagnosis.confirm_create_case') }}
        </button>
        <button class="btn-primary submit-btn" :disabled="saving || caseCreating" @click="emit('confirmAndSubmit')">
          <SendHorizonal class="w-4 h-4" />
          {{ t('diagnosis.create_and_submit') }}
        </button>
        <button v-if="caseLink" class="btn-micro" @click="emit('openCase', caseLink)">
          <ExternalLink class="w-4 h-4" />
          {{ t('diagnosis.view_case') }}
        </button>
      </div>
      <p class="diagnosis-hint">{{ t('diagnosis.panel_hint') }}</p>
    </div>
  </div>
</template>

<style scoped>
.diagnosis-panel {
  margin: 0 24px 12px;
  padding: 14px 16px;
  border: 1px solid rgba(14, 165, 233, 0.2);
  border-radius: var(--radius-lg);
  background: #ffffff;
}

.diagnosis-header {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.diagnosis-icon {
  flex-shrink: 0;
  color: var(--color-primary-600);
  margin-top: 2px;
}

.header-title-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.header-title-text {
  min-width: 0;
  flex: 1;
}

.title-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.panel-title {
  font-weight: 700;
  font-size: 0.95rem;
  color: var(--color-primary-900);
}

.priority-pill {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 700;
  line-height: 1.4;
}

.priority-pill.prio-p0 { color: #b91c1c; background: #fef2f2; border: 1px solid #fecaca; }
.priority-pill.prio-p1 { color: #c2410c; background: #fff7ed; border: 1px solid #fed7aa; }
.priority-pill.prio-p2 { color: #1d4ed8; background: #eff6ff; border: 1px solid #bfdbfe; }
.priority-pill.prio-p3 { color: #475569; background: #f8fafc; border: 1px solid #e2e8f0; }

.confirmed-pill {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 600;
  color: #14532d;
  background: #dcfce7;
  border: 1px solid #86efac;
}

.draft-pill {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 600;
  color: #7c2d12;
  background: #ffedd5;
  border: 1px solid #fdba74;
}

.phenomenon-preview {
  margin-top: 4px;
  font-size: 0.8rem;
  color: #475569;
  display: flex;
  gap: 6px;
  min-width: 0;
}

.phenomenon-label {
  flex-shrink: 0;
  font-weight: 600;
  color: #334155;
}

.phenomenon-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.diagnosis-state {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 0 6px;
  color: #64748b;
  font-size: 0.85rem;
}

.diagnosis-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-top: 10px;
}

.field-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field-group label {
  font-size: 0.8rem;
  font-weight: 600;
  color: #334155;
}

.diagnosis-textarea {
  resize: vertical;
  font-size: 0.85rem;
  line-height: 1.5;
}

.confidence-label {
  display: flex;
  align-items: center;
  gap: 8px;
}

.confidence-value {
  color: var(--color-primary-600);
  font-weight: 700;
}

.diagnosis-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 2px;
}

.submit-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.diagnosis-hint {
  margin: 0;
  font-size: 0.75rem;
  color: #94a3b8;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
