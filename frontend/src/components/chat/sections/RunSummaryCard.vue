<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { CheckCircle2, XCircle, Clock, DollarSign, ChevronDown, Loader2 } from 'lucide-vue-next'
import { statusMessageText, statusModelText } from '@/composables/chat/cards/presenters'
import type { ChatStatusCard, ResultsSummaryState } from '@/composables/chat/types'

/**
 * 运行摘要卡：实时引擎状态列表 + 阶段耗时/成本汇总（可展开历史明细）。
 */
const props = defineProps<{
  statusCards: ChatStatusCard[]
  resultsSummary: ResultsSummaryState
}>()

const emit = defineEmits<{
  (event: 'toggle-expanded'): void
}>()

const { t } = useI18n()
</script>

<template>
  <div
    v-if="props.statusCards.length > 0 || props.resultsSummary.visible"
    class="run-summary-card"
    :class="{ 'is-error': props.statusCards.some(card => card.status === 'FAILED') }"
  >
    <div class="run-summary-header">
      <div class="run-status-stack">
        <div v-if="props.statusCards.length > 0" class="run-status-list">
          <div v-for="card in props.statusCards" :key="card.id" class="run-status-item">
            <CheckCircle2 v-if="card.status === 'COMPLETED'" class="w-4 h-4 text-success" />
            <XCircle v-else-if="card.status === 'FAILED'" class="w-4 h-4 text-error" />
            <Loader2 v-else class="w-4 h-4 spin text-primary" />
            <span class="run-status-text">{{ statusMessageText(card.message) }}</span>
            <span v-if="statusModelText(card)" class="run-model-pill">{{ statusModelText(card) }}</span>
          </div>
        </div>
        <div v-else class="run-status-item">
          <CheckCircle2 class="w-4 h-4 text-success" />
          <span class="run-status-text">{{ t('dashboard.status_dist') }}</span>
        </div>
      </div>
      <div class="run-summary-meta">
        <span v-if="props.resultsSummary.visible" class="run-metric">
          <Clock class="w-3 h-3" /> {{ (props.resultsSummary.totalDurationMs / 1000).toFixed(1) }}s
        </span>
        <span v-if="props.resultsSummary.visible" class="run-metric">
          <DollarSign class="w-3 h-3" /> ${{ props.resultsSummary.totalCostUsd.toFixed(4) }}
        </span>
        <Transition name="run-summary-toggle-motion">
          <button
            v-if="props.resultsSummary.visible"
            class="run-summary-toggle"
            type="button"
            :title="t('dashboard.status_dist')"
            @click="emit('toggle-expanded')"
          >
            <ChevronDown class="w-4 h-4 transition-transform inline" :class="{'rotate-180': props.resultsSummary.expanded}" />
          </button>
        </Transition>
      </div>
    </div>
    <div v-show="props.resultsSummary.expanded" class="card-body flex flex-col gap-2 mt-2 border-t pt-2 border-gray-100">
      <div v-for="(step, idx) in props.resultsSummary.history" :key="step.id" class="text-xs text-slate-500 flex justify-between items-center bg-gray-50 p-1.5 rounded">
        <span class="flex items-center gap-1">
          <CheckCircle2 v-if="step.success" class="w-3 h-3 text-green-500" />
          <XCircle v-else class="w-3 h-3 text-red-500" />
          {{ t('chat.stage_step', { index: idx + 1, timestamp: step.timestamp }) }}
        </span>
        <span class="flex gap-2">
          <span v-if="step.duration_ms"><Clock class="w-3 h-3 inline"/> {{ (step.duration_ms / 1000).toFixed(1) }}s</span>
          <span v-if="step.cost_usd"><DollarSign class="w-3 h-3 inline"/> ${{ step.cost_usd.toFixed(4) }}</span>
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.run-summary-card {
  background: white;
  border: 1px solid var(--color-primary-100);
  border-left: 3px solid var(--color-primary-500);
  padding: 10px 12px;
}

.run-summary-card.is-error {
  border-color: #FEE2E2;
  border-left-color: var(--color-accent-rose);
}

.run-summary-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}

.run-status-stack {
  min-width: 0;
  flex: 1;
}

.run-status-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.run-status-item {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  color: var(--color-text-body);
  font-size: 0.84rem;
  font-weight: 600;
}

.run-status-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-model-pill {
  flex: 0 0 auto;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border: 1px solid #dbeafe;
  background: #eff6ff;
  color: #1d4ed8;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 0.7rem;
  font-weight: 700;
}

.run-summary-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
  color: var(--color-text-muted);
  font-size: 0.75rem;
}

.run-metric,
.run-summary-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.run-summary-toggle {
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #475569;
  border-radius: 50%;
  width: 28px;
  height: 28px;
  justify-content: center;
  padding: 0;
  cursor: pointer;
  font-size: 0.75rem;
  font-weight: 700;
  transform-origin: center;
  transition: background-color 0.18s ease, border-color 0.18s ease, transform 0.18s ease, opacity 0.18s ease;
}

.run-summary-toggle:hover {
  border-color: #cbd5e1;
  background: #f1f5f9;
  transform: translateY(-1px);
}

.run-summary-toggle-motion-enter-active,
.run-summary-toggle-motion-leave-active {
  transition: opacity 0.18s ease, transform 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}

.run-summary-toggle-motion-enter-from,
.run-summary-toggle-motion-leave-to {
  opacity: 0;
  transform: translateX(6px) scale(0.88);
}

.run-summary-toggle-motion-enter-to,
.run-summary-toggle-motion-leave-from {
  opacity: 1;
  transform: translateX(0) scale(1);
}

.card-body { margin-top: 4px; }

@media (max-width: 760px) {
  .run-summary-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .run-summary-meta {
    width: 100%;
    flex-wrap: wrap;
  }
}
</style>
