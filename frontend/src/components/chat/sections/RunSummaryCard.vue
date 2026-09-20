<script setup lang="ts">
import { CheckCircle2, XCircle, Clock, DollarSign, Loader2 } from 'lucide-vue-next'
import { statusMessageText, statusModelText } from '@/composables/chat/cards/presenters'
import type { ChatStatusCard, ResultsSummaryState } from '@/composables/chat/types'

/**
 * 运行状态与任务状态分布摘要（精简内联模式）：
 * 用于输入框上方操作栏右侧显示，包含状态/模型、总耗时与总成本，不展开分阶段历史。
 */
const props = defineProps<{
  statusCards: ChatStatusCard[]
  resultsSummary: ResultsSummaryState
}>()
</script>

<template>
  <div
    v-if="props.statusCards.length > 0 || props.resultsSummary.visible"
    class="run-summary-inline"
    :class="{ 'is-error': props.statusCards.some(card => card.status === 'FAILED') }"
  >
    <div v-if="props.statusCards.length > 0" class="run-status-stack">
      <div class="run-status-list">
        <div v-for="card in props.statusCards" :key="card.id" class="run-status-item">
          <CheckCircle2 v-if="card.status === 'COMPLETED'" class="w-3.5 h-3.5 text-success" />
          <XCircle v-else-if="card.status === 'FAILED'" class="w-3.5 h-3.5 text-error" />
          <Loader2 v-else class="w-3 h-3 spin text-slate-400" />
          <span class="run-status-text">{{ statusMessageText(card.message) }}</span>
          <span v-if="statusModelText(card)" class="run-model-pill">{{ statusModelText(card) }}</span>
        </div>
      </div>
    </div>
    <div v-if="props.resultsSummary.visible" class="run-summary-meta">
      <span class="run-metric">
        <Clock class="w-3 h-3 text-slate-400" /> {{ (props.resultsSummary.totalDurationMs / 1000).toFixed(1) }}s
      </span>
      <span class="run-metric">
        <DollarSign class="w-3 h-3 text-slate-400" /> ${{ props.resultsSummary.totalCostUsd.toFixed(4) }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.run-summary-inline {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  max-width: 100%;
}

.run-status-stack {
  min-width: 0;
  display: flex;
  align-items: center;
}

.run-status-list {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.run-status-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  color: var(--color-text-body, #334155);
  font-size: 0.75rem;
  font-weight: 500;
}

.run-status-text {
  min-width: 0;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-model-pill {
  flex: 0 0 auto;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border: 1px solid #dbeafe;
  background: #eff6ff;
  color: #1d4ed8;
  border-radius: 999px;
  padding: 1px 6px;
  font-size: 0.6875rem;
  font-weight: 600;
}

.run-summary-meta {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
  color: var(--color-text-muted, #64748b);
  font-size: 0.75rem;
}

.run-metric {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-variant-numeric: tabular-nums;
}

@media (max-width: 760px) {
  .run-summary-inline {
    flex-wrap: wrap;
    gap: 6px;
  }
}
</style>
