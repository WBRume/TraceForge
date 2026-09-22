<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import ToggleSwitch from '@/components/ToggleSwitch.vue'
import type { ChatViewVm } from '@/composables/chat/useChatViewModel'

/**
 * 启动引擎确认弹窗：确认前允许编辑随首条消息发出的初始 Prompt；
 * 问题定位且绑定规程的任务提供“自动执行全流程”主开关。
 */
const props = defineProps<{
  vm: ChatViewVm
}>()

const { t } = useI18n()

const sopApplies = computed(() =>
  Boolean(props.vm.currentTask?.task_meta_json?.diagnosis_playbook_guide),
)
</script>

<template>
  <ConfirmActionModal
    :show="props.vm.showStartConfirm"
    :title="t('chat.start_confirm_title')"
    :message="t('chat.start_confirm_message')"
    :description="t('chat.start_confirm_description')"
    :cancel-text="t('common.cancel')"
    :confirm-text="t('chat.engine_start')"
    tone="primary"
    :loading="props.vm.startingTask"
    @cancel="props.vm.showStartConfirm = false"
    @confirm="props.vm.startTask"
  >
    <template #content>
      <div class="modal-form">
        <div class="form-group">
          <label for="start-initial-prompt">{{ t('chat.initial_prompt_label') }}</label>
          <textarea
            id="start-initial-prompt"
            v-model="props.vm.startPrompt"
            class="input-field textarea-field"
            rows="5"
            :placeholder="t('chat.initial_prompt_placeholder')"
          ></textarea>
        </div>
        <div v-if="sopApplies" class="form-group sop-auto-run-group">
          <label class="sop-auto-run-switch" title="开启后，SOP 阶段确认通过即由服务端自动衔接下一阶段，无需逐步确认；证据不足或执行失败时暂停。">
            <ToggleSwitch v-model="props.vm.startSopAutoRun" aria-label="自动执行全流程" />
            <span class="sop-auto-run-title">自动执行全流程</span>
            <span class="sop-auto-run-hint">阶段确认通过后自动推进下一阶段</span>
          </label>
        </div>
      </div>
    </template>
  </ConfirmActionModal>
</template>

<style scoped>
.modal-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.form-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.form-group label {
  font-size: 0.875rem;
  font-weight: 500;
  color: #475569;
}
.input-field {
  padding: 10px 14px;
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-md);
  font-family: inherit;
  font-size: 1rem;
  width: 100%;
  box-sizing: border-box;
}
.input-field:focus { border-color: var(--color-primary-500); outline: none; }
.sop-auto-run-group { padding: 10px 12px; border: 1px solid #E2E8F0; border-radius: var(--radius-md); background: #F8FAFC; }
.sop-auto-run-switch { display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 0.875rem; color: #334155; }
.sop-auto-run-title { font-weight: 600; flex-shrink: 0; }
.sop-auto-run-hint { color: #94A3B8; font-size: 0.78rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
