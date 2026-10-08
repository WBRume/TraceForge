<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, CircleHelp, MessageSquare, X } from '@/components/icons'
import { confirmationValueText, type ConfirmationHistoryRecord } from '@/composables/chat/message/confirmationHistory'

const props = defineProps<{ record: ConfirmationHistoryRecord; appearance?: 'chat' | 'terminal' }>()
const { t } = useI18n()
const state = computed(() => ['answered', 'cancelled', 'approved', 'rejected', 'closed'].includes(props.record.status) ? props.record.status : 'closed')
const heading = computed(() => t(`chat.confirmation_history.${props.record.kind === 'resolution' ? state.value : props.record.kind}`))
const icon = computed(() => props.record.kind === 'question' ? CircleHelp : props.record.kind === 'answer' ? MessageSquare
  : ['answered', 'approved'].includes(state.value) ? Check : X)
const rows = computed(() => props.record.rows.map((row, index) => ({
  ...row,
  title: row.title || row.description || t('chat.confirmation_history.item', { index: index + 1 }),
  description: row.title ? row.description : '',
  answer: confirmationValueText(row.values, t),
})))
</script>

<template>
  <section class="confirmation-history" :class="[`history-${record.kind}`, `state-${state}`, { 'is-terminal': appearance === 'terminal' }]" :aria-label="heading">
    <header class="history-heading">
      <component :is="icon" class="history-icon" aria-hidden="true" />
      <span class="history-title">{{ heading }}</span>
      <span v-if="record.kind === 'question' && rows.length > 1" class="history-count">{{ t('chat.confirmation_history.question_count', { count: rows.length }) }}</span>
      <span v-if="record.status === 'unconfirmed'" class="history-unconfirmed">{{ t('chat.confirmation_history.unconfirmed') }}</span>
    </header>
    <p v-if="record.prompt" class="history-prompt">{{ record.prompt }}</p>
    <p v-if="record.kind === 'resolution' && state === 'closed'" class="history-note">{{ t('chat.confirmation_history.unavailable') }}</p>
    <ol v-if="rows.length" class="history-rows">
      <li v-for="(row, index) in rows" :key="row.key" class="history-row">
        <span class="question-number" aria-hidden="true">{{ String(index + 1).padStart(2, '0') }}</span>
        <div class="question-detail">
          <p v-if="row.title && (rows.length > 1 || row.title !== t('chat.confirmation_history.item', { index: 1 }))" class="question-title">{{ row.title }}</p>
          <p v-if="row.description" class="question-description">{{ row.description }}</p>
          <div v-if="record.kind === 'question' && row.options.length" class="question-options" :aria-label="t('chat.confirmation_history.options')">
            <span v-for="(option, optionIndex) in row.options" :key="optionIndex" class="question-option">{{ option }}</span>
          </div>
          <p v-if="record.kind !== 'question'" class="question-answer">{{ row.answer }}</p>
        </div>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.confirmation-history { --history-accent: #0369a1; --history-muted: #64748b; --history-line: #e2e8f0; color: var(--history-text, #1e293b); font-size: 13px; line-height: 1.6; min-width: 0; }
.history-heading { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; color: var(--history-accent); }
.history-icon { width: 17px; height: 17px; flex-shrink: 0; }
.history-title { font-weight: 650; font-size: 13px; }
.history-count { margin-left: auto; color: var(--history-muted); font-size: 12px; }
.history-unconfirmed { color: #b45309; font-size: 12px; }
.history-prompt { margin: 10px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.history-note { margin: 3px 0 0 25px; color: var(--history-muted); font-size: 12px; }
.history-rows { list-style: none; padding: 0; margin: 10px 0 0; }
.history-row { display: flex; align-items: flex-start; gap: 12px; padding: 11px 0; border-top: 1px solid var(--history-line); }
.history-row:last-child { padding-bottom: 0; }
.question-number { flex: 0 0 20px; font-variant-numeric: tabular-nums; color: var(--history-number, #94a3b8); font-size: 11px; padding-top: 3px; }
.question-detail { flex: 1; min-width: 0; }
.question-title { margin: 0; font-weight: 600; white-space: pre-wrap; overflow-wrap: anywhere; }
.question-description { margin: 3px 0 0; color: var(--history-muted); white-space: pre-wrap; overflow-wrap: anywhere; }
.question-options { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 7px; }
.question-option { color: var(--history-option-text, #475569); background: var(--history-option-bg, #f1f5f9); padding: 2px 7px; border-radius: 4px; font-size: 11px; overflow-wrap: anywhere; max-width: 100%; }
.history-answer { --history-accent: #047857; }
.history-answer .question-title { color: var(--history-muted); font-size: 12px; font-weight: 500; }
.history-answer .question-description { display: none; }
.question-answer { margin: 3px 0 0; font-weight: 550; white-space: pre-wrap; overflow-wrap: anywhere; }
.history-resolution { --history-accent: #047857; }
.history-resolution.state-cancelled, .history-resolution.state-closed { --history-accent: #64748b; }
.history-resolution.state-rejected { --history-accent: #b45309; }
.confirmation-history.is-terminal { --history-text: #d4deea; --history-muted: #9aafc9; --history-number: #8ba0bc; --history-line: #29384e; --history-option-text: #c6d8ed; --history-option-bg: #1d2b40; --history-accent: #8fc5ff; }
.confirmation-history.is-terminal.history-answer, .confirmation-history.is-terminal.state-answered, .confirmation-history.is-terminal.state-approved { --history-accent: #79e2b0; }
.confirmation-history.is-terminal.state-rejected { --history-accent: #f2c36c; }
.is-terminal .history-unconfirmed { color: #f2c36c; }
@media (max-width: 480px) { .history-row { gap: 8px; } }
</style>
