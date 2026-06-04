<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

type ResolutionDecisionDraft = {
  enabled: boolean
  title: string
  body: string
  impact_scope: string
  promote_candidate: boolean
}

const props = defineProps<{
  modelValue: ResolutionDecisionDraft
  titleInvalid?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: ResolutionDecisionDraft]
}>()

const { t } = useI18n()

const draft = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

function update<K extends keyof ResolutionDecisionDraft>(key: K, value: ResolutionDecisionDraft[K]) {
  draft.value = { ...draft.value, [key]: value }
}
</script>

<template>
  <section class="decision-inline">
    <label class="toggle-line">
      <input
        :checked="draft.enabled"
        type="checkbox"
        @change="update('enabled', ($event.target as HTMLInputElement).checked)"
      />
      <span>{{ t('doc_review.decision_record_toggle') }}</span>
    </label>

    <div v-if="draft.enabled" class="decision-grid">
      <label class="field">
        <span>{{ t('doc_review.decision_title') }} <b>*</b></span>
        <input
          :value="draft.title"
          :class="{ 'is-invalid': titleInvalid }"
          @input="update('title', ($event.target as HTMLInputElement).value)"
        />
      </label>
      <label class="field">
        <span>{{ t('doc_review.decision_impact_scope') }}</span>
        <input
          :value="draft.impact_scope"
          @input="update('impact_scope', ($event.target as HTMLInputElement).value)"
        />
      </label>
      <label class="field wide">
        <span>{{ t('doc_review.decision_body') }}</span>
        <textarea
          :value="draft.body"
          rows="2"
          @input="update('body', ($event.target as HTMLTextAreaElement).value)"
        />
      </label>
      <label class="toggle-line subtle">
        <input
          :checked="draft.promote_candidate"
          type="checkbox"
          @change="update('promote_candidate', ($event.target as HTMLInputElement).checked)"
        />
        <span>{{ t('doc_review.decision_promote_candidate') }}</span>
      </label>
    </div>
  </section>
</template>

<style scoped>
.decision-inline {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 8px;
  background: rgba(248, 250, 252, 0.82);
}

.toggle-line {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #334155;
  font-size: 0.86rem;
  font-weight: 700;
}

.toggle-line.subtle {
  font-weight: 500;
}

.decision-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(180px, 0.65fr);
  gap: 10px;
}

.field {
  display: grid;
  gap: 5px;
  color: #334155;
  font-size: 0.78rem;
  font-weight: 700;
}

.field.wide {
  grid-column: 1 / -1;
}

.field b {
  color: #dc2626;
}

.field input,
.field textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 8px 9px;
  color: #0f172a;
  font: inherit;
  font-weight: 500;
}

.field textarea {
  resize: vertical;
}

.field input:focus,
.field textarea:focus {
  outline: none;
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.13);
}

.field .is-invalid {
  border-color: #dc2626;
  box-shadow: 0 0 0 2px rgba(220, 38, 38, 0.13);
}

@media (max-width: 760px) {
  .decision-grid {
    grid-template-columns: 1fr;
  }
}
</style>
