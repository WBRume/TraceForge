<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Loader2,
  ArrowPathIcon,
  ArrowTopRightOnSquareIcon
} from '@/components/icons'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import type { ChatViewVm } from '@/composables/chat/useChatViewModel'

/**
 * 任务启动前（PRE_START）且已有规格文档时的引导提示条（极简悬浮胶囊形态）：
 * 与历史记录阅读恢复胶囊 (ReadingResumeBanner) 视觉与交互规范全面对齐。
 * 展示 spec 引导状态、触发构建（带确认弹窗）与打开规格工作区。
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

const hasError = computed(() => Boolean(props.vm.specBootstrap?.error_message))
const isRunning = computed(() => props.vm.isSpecBootstrapActive)

const bootstrapText = computed(() => {
  if (props.vm.specBootstrapLoading) {
    return t('chat.spec_bootstrap_loading')
  }
  if (props.vm.specBootstrap) {
    return `${props.vm.bootstrapStatusText(props.vm.specBootstrap.status)} · ${props.vm.specBootstrap.progress}%`
  }
  return t('chat.spec_bootstrap_not_initialized')
})
</script>

<template>
  <div
    v-if="props.vm.isTaskPreStart && props.vm.currentTaskHasSpec && !props.vm.isPdfSpec"
    class="spec-bootstrap-wrapper"
  >
    <div
      class="spec-bootstrap-pill"
      :class="{
        'is-active': isRunning,
        'is-error': hasError
      }"
      role="status"
    >
      <!-- 左侧呼吸状态指示灯 -->
      <div class="dot-wrapper" aria-hidden="true">
        <span class="dot-pulse"></span>
        <span class="dot"></span>
      </div>

      <!-- 核心文案区 -->
      <div class="pill-main">
        <span class="pill-text">{{ t('chat.spec_prestart_hint') }}</span>
        <span class="pill-separator">·</span>
        <span class="pill-status">
          <Loader2 v-if="isRunning" class="w-3.5 h-3.5 spin inline-loader" />
          <span>{{ bootstrapText }}</span>
        </span>
        <span
          v-if="props.vm.specBootstrap?.error_message"
          class="pill-error-tag"
          :title="props.vm.specBootstrap.error_message"
        >
          ({{ props.vm.specBootstrap.error_message }})
        </span>
      </div>

      <!-- 右侧操作区 -->
      <div class="pill-side-actions">
        <div class="pill-divider" aria-hidden="true"></div>

        <button
          v-if="props.vm.canTriggerSpecBootstrap"
          type="button"
          class="btn-pill-action secondary"
          :disabled="props.vm.specBootstrapTriggering"
          @click="showBootstrapConfirm = true"
        >
          <ArrowPathIcon class="w-3 h-3" />
          <span>{{ t('chat.spec_bootstrap_action_build') }}</span>
        </button>

        <button
          type="button"
          class="btn-pill-action primary"
          @click="props.vm.openSpecWorkspace"
        >
          <span>{{ t('chat.spec_open_workspace') }}</span>
          <ArrowTopRightOnSquareIcon class="w-3 h-3" />
        </button>
      </div>
    </div>

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
.spec-bootstrap-wrapper {
  display: flex;
  justify-content: center;
  width: 100%;
  padding: 8px var(--space-6) 0;
  box-sizing: border-box;
}

.spec-bootstrap-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  width: fit-content;
  max-width: calc(100% - 32px);
  margin: 0;
  padding: 5px 6px 5px 12px;
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(226, 232, 240, 0.95);
  box-shadow: 0 4px 14px -2px rgba(15, 23, 42, 0.08), 0 1px 3px -1px rgba(15, 23, 42, 0.03);
  user-select: none;
  transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1),
              box-shadow 0.2s cubic-bezier(0.4, 0, 0.2, 1),
              border-color 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  box-sizing: border-box;
}

.spec-bootstrap-pill:hover {
  transform: translateY(-1px);
  border-color: rgba(203, 213, 225, 1);
  box-shadow: 0 6px 18px -2px rgba(15, 23, 42, 0.1), 0 2px 6px -1px rgba(15, 23, 42, 0.04);
}

.spec-bootstrap-pill:active {
  transform: translateY(0);
  box-shadow: 0 1px 4px -1px rgba(15, 23, 42, 0.06);
}

/* 异常状态风格 */
.spec-bootstrap-pill.is-error {
  background: rgba(254, 242, 242, 0.95);
  border-color: rgba(248, 113, 113, 0.45);
}

/* 呼吸点动画 */
.dot-wrapper {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 8px;
  height: 8px;
  flex-shrink: 0;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #0ea5e9;
  position: relative;
  z-index: 1;
}

.dot-pulse {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: #0ea5e9;
  opacity: 0.6;
  animation: spec-dot-pulse 2s cubic-bezier(0.45, 0, 0.55, 1) infinite;
}

@keyframes spec-dot-pulse {
  0% {
    transform: scale(1);
    opacity: 0.6;
  }
  70% {
    transform: scale(2.4);
    opacity: 0;
  }
  100% {
    transform: scale(2.4);
    opacity: 0;
  }
}

.spec-bootstrap-pill.is-error .dot {
  background: #ef4444;
}
.spec-bootstrap-pill.is-error .dot-pulse {
  background: #ef4444;
}

.pill-main {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  overflow: hidden;
}

.pill-text {
  font-size: 0.78rem;
  font-weight: 600;
  color: #0f172a;
  white-space: nowrap;
  letter-spacing: -0.01em;
}

.pill-separator {
  font-size: 0.75rem;
  color: #cbd5e1;
  margin: 0 1px;
}

.pill-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.78rem;
  font-weight: 500;
  color: #475569;
  white-space: nowrap;
}

.inline-loader {
  color: #0284c7;
}

.pill-error-tag {
  font-size: 0.75rem;
  color: #b91c1c;
  max-width: 200px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pill-side-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.pill-divider {
  width: 1px;
  height: 12px;
  background-color: rgba(203, 213, 225, 0.8);
  margin: 0 2px;
}

.btn-pill-action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 24px;
  padding: 0 10px;
  font-size: 0.74rem;
  line-height: 1;
  border-radius: 9999px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
}

.btn-pill-action.secondary {
  border: 1px solid rgba(203, 213, 225, 0.8);
  color: #475569;
  background: #ffffff;
}

.btn-pill-action.secondary:hover {
  background: #f8fafc;
  border-color: #94a3b8;
  color: #0f172a;
}

.btn-pill-action.secondary:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.btn-pill-action.primary {
  background-color: var(--color-primary-500, #0ea5e9);
  color: var(--color-surface-white, #ffffff);
  border: none;
  font-weight: 600;
  box-shadow: 0 2px 6px -1px rgba(14, 165, 233, 0.3);
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.btn-pill-action.primary:hover {
  background-color: var(--color-primary-600, #0284c7);
  transform: translateY(-1px);
  box-shadow: 0 4px 10px -2px rgba(14, 165, 233, 0.4);
}

.btn-pill-action.primary:active {
  transform: translateY(0);
}

.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
