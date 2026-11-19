<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Sparkles, Database, TestTube, Loader2 } from '@/components/icons'
import RunSummaryCard from './RunSummaryCard.vue'
import DomainMilestones from '@/components/ai/DomainMilestones.vue'
import type { ChatViewVm } from '@/composables/chat/useChatViewModel'

/**
 * 快捷操作与状态摘要行：
 * 左侧：研发态任务显示 UI/API/E2E 快捷验证按钮；问题定位任务显示一键总结问题案例；
 * 右侧：展示任务状态分布、模型标签、耗时与成本摘要（无展开明细）。
 */
const props = defineProps<{
  vm: ChatViewVm
}>()

const { t } = useI18n()

const canShowActions = computed(() => (
  props.vm.messages.length > 0
  && !props.vm.isChatLocked
  && (props.vm.isDiagnosisTask || !props.vm.engineRunning)
))

const canShowStatusSummary = computed(() => (
  props.vm.statusCards.length > 0 || props.vm.resultsSummary.visible
))
</script>

<template>
  <div
    v-if="canShowActions || canShowStatusSummary || $slots.notice"
    class="verification-actions"
  >
    <div v-if="canShowActions" class="actions-left">
      <template v-if="!props.vm.hidePatchWorkflows">
        <span class="verify-label">{{ t('portal.architecture') }}:</span>
        <!-- 架构图能力尚未接入：三个快捷验证按钮统一置灰 -->
        <button
          class="btn-micro is-unavailable"
          type="button"
          disabled
          aria-disabled="true"
          :title="t('chat.verification_unavailable_title')"
        >
          <TestTube class="w-3" /> UI
        </button>
        <button
          class="btn-micro is-unavailable"
          type="button"
          disabled
          aria-disabled="true"
          :title="t('chat.verification_unavailable_title')"
        >
          <Database class="w-3" /> API
        </button>
        <button
          class="btn-micro is-unavailable"
          type="button"
          disabled
          aria-disabled="true"
          :title="t('chat.verification_unavailable_title')"
        >
          <Sparkles class="w-3" /> E2E
        </button>
      </template>
      <template v-else>
        <button
          class="btn-micro"
          :disabled="props.vm.engineRunning || props.vm.diagnosisChatBusy || props.vm.diagnosisSummarizing || props.vm.isDiagnosisAdopted"
          :title="props.vm.isDiagnosisAdopted ? t('diagnosis.case_already_adopted_no_summary') : t('diagnosis.summarize_case_button')"
          @click="props.vm.generateDiagnosisSummary"
        >
          <Loader2 v-if="props.vm.diagnosisSummarizing" class="w-3 h-3 spin" />
          <Sparkles v-else class="w-3 h-3" />
          {{ props.vm.isDiagnosisAdopted ? t('diagnosis.case_adopted_label') : props.vm.diagnosisSummarizingLabel }}
        </button>
        <DomainMilestones :active="props.vm.diagnosisSummarizing" :events="props.vm.diagnosisMilestones" />
      </template>
    </div>

    <div v-if="canShowStatusSummary || $slots.notice" class="actions-right">
      <RunSummaryCard
        v-if="canShowStatusSummary"
        :status-cards="props.vm.statusCards"
        :results-summary="props.vm.resultsSummary"
      />
      <slot name="notice" />
    </div>
  </div>
</template>

<style scoped>
.verification-actions {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  /* 左右内边距与输入卡外沿对齐 */
  padding: 8px 16px;
  /* 会话区已是白色圆角卡片：这里不再铺一条灰色横带，改用白色实底托住操作行，
     让快捷操作与右侧状态摘要像悬浮在对话之上，而不是被灰条切成两段 */
  background: var(--color-surface-white, #FFFFFF);
  border-top: 0;
  min-height: 44px;
  box-sizing: border-box;
}

/* 操作行上方的白色渐隐：滚动内容淡出到卡片底色，避免生硬切断 */
.verification-actions::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 100%;
  height: 32px;
  background: linear-gradient(to top, var(--color-surface-white, #FFFFFF) 0%, rgba(255, 255, 255, 0) 100%);
  pointer-events: none;
}

.actions-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}

.actions-right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
  margin-left: auto;
  min-width: 0;
  color: var(--color-text-muted);
}

.verify-label {
  font-size: 0.75rem;
  color: #94A3B8;
  margin-right: 4px;
}

/* 未接入能力的按钮：保持占位可见，但明确置灰且不可点击 */
.actions-left .btn-micro.is-unavailable,
.actions-left .btn-micro.is-unavailable:hover {
  background: #F8FAFC;
  color: #CBD5E1;
  border-color: #E2E8F0;
  box-shadow: none;
  cursor: not-allowed;
}

@media (max-width: 760px) {
  .verification-actions {
    flex-wrap: wrap;
    gap: 8px;
    padding: 8px 16px;
  }
}
</style>
