<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Sparkles, Database, TestTube, Loader2 } from 'lucide-vue-next'
import type { ChatViewVm } from '@/composables/chat/useChatViewModel'

/**
 * 快捷操作行：研发态任务显示 UI/API/E2E 快捷验证按钮；
 * 问题定位任务显示一键总结问题案例（位置与样式与研发态一致）。
 */
const props = defineProps<{
  vm: ChatViewVm
}>()

const { t } = useI18n()
</script>

<template>
  <div
    v-if="props.vm.messages.length > 0 && !props.vm.isChatLocked && (props.vm.isDiagnosisTask || !props.vm.engineRunning)"
    class="verification-actions"
  >
    <template v-if="!props.vm.hidePatchWorkflows">
      <span class="verify-label">{{ t('portal.architecture') }}:</span>
      <button class="btn-micro" @click="props.vm.sendVerification('ui')" title="Playwright UI">
        <TestTube class="w-3" /> UI
      </button>
      <button class="btn-micro" @click="props.vm.sendVerification('api')" title="Postman API">
        <Database class="w-3" /> API
      </button>
      <button class="btn-micro" @click="props.vm.sendVerification('e2e')" :title="t('chat.verification_e2e_title')">
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
    </template>
  </div>
</template>

<style scoped>
.verification-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 24px;
  background-color: #F8FAFC;
  border-top: 1px solid #F1F5F9;
}
.verify-label {
  font-size: 0.75rem;
  color: #94A3B8;
  margin-right: 4px;
}
</style>
