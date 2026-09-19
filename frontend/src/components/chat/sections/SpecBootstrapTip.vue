<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Loader2 } from 'lucide-vue-next'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import type { ChatViewVm } from '@/composables/chat/useChatViewModel'

/**
 * 任务启动前（PRE_START）且已有规格文档时的引导提示条：展示 spec 引导
 * 状态、触发构建（带确认弹窗）与打开规格工作区。
 */
const props = defineProps<{
  vm: ChatViewVm
}>()

const { t } = useI18n()
const showBootstrapConfirm = ref(false)

const confirmBootstrapBuild = async () => {
  if (props.vm.specBootstrapTriggering) return
  showBootstrapConfirm.value = false
  try {
    await props.vm.triggerSpecBootstrap()
  } catch {
    // triggerSpecBootstrap owns user-facing error handling
  }
}
</script>

<template>
  <div v-if="props.vm.isTaskPreStart && props.vm.currentTaskHasSpec && !props.vm.isPdfSpec" class="prestart-doc-tip glass-panel">
    <p>{{ t('chat.spec_prestart_hint') }}</p>
    <div v-if="props.vm.specBootstrapLoading" class="bootstrap-status">
      <span>{{ t('chat.spec_bootstrap_loading') }}</span>
    </div>
    <div v-else-if="props.vm.specBootstrap" class="bootstrap-status">
      <div class="bootstrap-status-main">
        <Loader2 v-if="props.vm.isSpecBootstrapActive" class="w-4 h-4 spin text-primary" />
        <span>{{ props.vm.bootstrapStatusText(props.vm.specBootstrap.status) }} · {{ props.vm.specBootstrap.progress }}%</span>
        <button
          v-if="props.vm.canTriggerSpecBootstrap"
          class="btn-secondary bootstrap-trigger-btn"
          :disabled="props.vm.specBootstrapTriggering"
          @click="showBootstrapConfirm = true"
        >
          {{ t('chat.spec_bootstrap_action_build') }}
        </button>
      </div>
      <p v-if="props.vm.specBootstrap.message" class="bootstrap-status-message">{{ props.vm.specBootstrap.message }}</p>
      <p v-if="props.vm.specBootstrap.error_message" class="bootstrap-status-error">{{ props.vm.specBootstrap.error_message }}</p>
    </div>
    <div v-else class="bootstrap-status">
      <span>{{ t('chat.spec_bootstrap_not_initialized') }}</span>
    </div>
    <button class="btn-secondary" @click="props.vm.openSpecWorkspace">
      {{ t('chat.spec_open_workspace') }}
    </button>

    <ConfirmActionModal
      :show="showBootstrapConfirm"
      :title="t('chat.spec_bootstrap_build_confirm_title')"
      :message="t('chat.spec_bootstrap_build_confirm_message')"
      :cancel-text="t('common.cancel')"
      :confirm-text="t('chat.spec_bootstrap_action_build')"
      tone="primary"
      :loading="props.vm.specBootstrapTriggering"
      @cancel="showBootstrapConfirm = false"
      @confirm="confirmBootstrapBuild"
    />
  </div>
</template>

<style scoped>
.prestart-doc-tip {
  margin: 10px var(--space-6) 0;
  padding: 10px 12px;
  border: 1px solid rgba(14, 165, 233, 0.22);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.prestart-doc-tip p {
  margin: 0;
  font-size: 0.85rem;
  color: #0369a1;
}
.bootstrap-status {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 4px;
  font-size: 0.8rem;
  color: #075985;
}
.bootstrap-status-main {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 500;
}
.bootstrap-trigger-btn {
  margin-left: 8px;
  padding: 2px 10px;
  font-size: 0.78rem;
  line-height: 1.4;
}
.bootstrap-status-message {
  margin: 0;
  font-size: 0.8rem;
  color: #0f766e;
}
.bootstrap-status-error {
  margin: 0;
  font-size: 0.8rem;
  color: #b91c1c !important;
}
</style>
