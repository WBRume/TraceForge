<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import type { ChatViewVm } from '@/composables/chat/useChatViewModel'

/**
 * 启动引擎确认弹窗：确认前允许编辑随首条消息发出的初始 Prompt。
 */
const props = defineProps<{
  vm: ChatViewVm
}>()

const { t } = useI18n()
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
</style>
