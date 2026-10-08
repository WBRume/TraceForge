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
  isUnselected: !row.values.length || row.values.every(v => v == null || v === ''),
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
          <p v-if="record.kind !== 'question'" class="question-answer" :class="{ 'is-unselected': row.isUnselected }">{{ row.answer }}</p>
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

/* 用户回答会话与确认记录气泡现代化优化 */
.history-answer,
.history-resolution.state-answered {
  --history-accent: #059669;
}

.history-answer .history-heading,
.history-resolution.state-answered .history-heading {
  padding-bottom: 6px;
  border-bottom: 1px solid #f1f5f9;
  color: #0f172a;
}

.history-answer .history-icon,
.history-resolution.state-answered .history-icon {
  width: 20px;
  height: 20px;
  padding: 3px;
  border-radius: 6px;
  background-color: #ecfdf5;
  color: #059669;
}

.history-answer .history-title,
.history-resolution.state-answered .history-title {
  font-size: 12.5px;
  font-weight: 600;
  color: #0f172a;
}

.history-answer .history-rows,
.history-resolution.state-answered .history-rows {
  margin-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.history-answer .history-row,
.history-resolution.state-answered .history-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 5px 8px;
  border-top: none;
  border-radius: 6px;
  background-color: #f8fafc;
  transition: background-color 0.15s ease;
}

.history-answer .history-row:hover,
.history-resolution.state-answered .history-row:hover {
  background-color: #f1f5f9;
}

.history-answer .question-number,
.history-resolution.state-answered .question-number {
  flex: 0 0 auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 10.5px;
  color: #94a3b8;
  padding-top: 0;
}

.history-answer .question-detail,
.history-resolution.state-answered .question-detail {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 4px 12px;
  flex: 1;
  min-width: 0;
}

.history-answer .question-title,
.history-resolution.state-answered .question-title {
  font-size: 12px;
  font-weight: 500;
  color: #64748b;
  white-space: nowrap;
}

.history-answer .question-description,
.history-resolution.state-answered .question-description {
  display: none;
}

.history-answer .question-answer,
.history-resolution.state-answered .question-answer {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  color: #0f172a;
  text-align: right;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.history-answer .question-answer.is-unselected,
.history-resolution.state-answered .question-answer.is-unselected {
  color: #94a3b8;
  font-weight: 400;
  font-style: italic;
}

.history-resolution { --history-accent: #047857; }
.history-resolution.state-cancelled, .history-resolution.state-closed { --history-accent: #64748b; }
.history-resolution.state-rejected { --history-accent: #b45309; }

/* 终端/暗色模式适配 */
.confirmation-history.is-terminal { --history-text: #d4deea; --history-muted: #9aafc9; --history-number: #8ba0bc; --history-line: #29384e; --history-option-text: #c6d8ed; --history-option-bg: #1d2b40; --history-accent: #8fc5ff; }
.confirmation-history.is-terminal.history-answer, .confirmation-history.is-terminal.state-answered, .confirmation-history.is-terminal.state-approved { --history-accent: #79e2b0; }
.confirmation-history.is-terminal.state-rejected { --history-accent: #f2c36c; }
.is-terminal .history-unconfirmed { color: #f2c36c; }

.confirmation-history.is-terminal.history-answer .history-heading,
.confirmation-history.is-terminal.state-answered .history-heading {
  border-bottom-color: #334155;
  color: #f1f5f9;
}
.confirmation-history.is-terminal.history-answer .history-icon,
.confirmation-history.is-terminal.state-answered .history-icon {
  background-color: rgba(16, 185, 129, 0.15);
  color: #34d399;
}
.confirmation-history.is-terminal.history-answer .history-title,
.confirmation-history.is-terminal.state-answered .history-title {
  color: #f1f5f9;
}
.confirmation-history.is-terminal.history-answer .history-row,
.confirmation-history.is-terminal.state-answered .history-row {
  background-color: rgba(30, 41, 59, 0.6);
}
.confirmation-history.is-terminal.history-answer .history-row:hover,
.confirmation-history.is-terminal.state-answered .history-row:hover {
  background-color: rgba(30, 41, 59, 0.9);
}
.confirmation-history.is-terminal.history-answer .question-title,
.confirmation-history.is-terminal.state-answered .question-title {
  color: #94a3b8;
}
.confirmation-history.is-terminal.history-answer .question-answer,
.confirmation-history.is-terminal.state-answered .question-answer {
  color: #f8fafc;
}
.confirmation-history.is-terminal.history-answer .question-answer.is-unselected,
.confirmation-history.is-terminal.state-answered .question-answer.is-unselected {
  color: #64748b;
}

@media (max-width: 480px) { .history-row { gap: 8px; } }
</style>
