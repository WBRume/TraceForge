<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Copy,
  Check,
  Undo2,
  Loader2,
} from '@/components/icons'
import DecisionMarkPopover from './DecisionMarkPopover.vue'
import DiagnosisResultCard from './DiagnosisResultCard.vue'
import ChatMessageContent from './ChatMessageContent.vue'
import { diagnosisPayloadFromMessage } from '@/types/diagnosis'
import type { ChatDecisionPayload } from '@/composables/useChatDecision'

const props = defineProps<{
  msg: Record<string, any>
  vm: any
}>()

const emit = defineEmits<{
  (event: 'undo-request', message: Record<string, any>): void
}>()

const { t } = useI18n()

const isPopoverOpen = ref(false)

const isDiagnosisResult = computed(() => String(props.msg?.message_type || props.msg?.type || '') === 'diagnosis_result')

const diagnosisPayload = computed(() => {
  if (!isDiagnosisResult.value) return null
  return diagnosisPayloadFromMessage(props.msg)
})

const diagnosisStatus = computed(() => {
  const status = props.vm?.diagnosisResult?.status
  return status ? String(status) : 'DRAFT'
})

const diagnosisExtractedFromAi = computed(() => {
  const flag = props.vm?.diagnosisResult?.extracted_from_ai
  return flag === undefined ? true : Boolean(flag)
})

const msgRole = computed(() => String(props.msg?.role || '').toLowerCase())
const displayContent = computed(() => {
  const content = String(props.msg?.content || '')
  return msgRole.value === 'assistant' && props.vm.currentTask?.task_meta_json?.diagnosis_playbook_guide
    ? content.replace(/```traceforge-sop[\s\S]*?(?:```|$)/g, '').trim() : content
})

function handleOpenPopover() {
  isPopoverOpen.value = true
}

// 气泡复制：AI / 人工消息均可一键复制会话内容
const canCopyMessage = computed(() => {
  if (isDiagnosisResult.value) return false
  if (msgRole.value !== 'user' && msgRole.value !== 'assistant') return false
  return Boolean(String(props.msg?.content || '').trim())
})

const canUndoMessage = computed(() => Boolean(props.vm?.canUndoMessage?.(props.msg)))
const isUndoingMessage = computed(() => String(props.vm?.undoingMessageId || '') === String(props.msg?.id || ''))
const showUndoAction = computed(() => canUndoMessage.value || isUndoingMessage.value)

function handleUndoMessage() {
  if (!canUndoMessage.value || isUndoingMessage.value || Boolean(props.vm?.isUndoing)) return
  emit('undo-request', props.msg)
}

const copyState = ref<'idle' | 'done' | 'failed'>('idle')
let copyResetTimer: number | undefined

const copyTitle = computed(() => {
  if (copyState.value === 'done') return t('chat.copied')
  if (copyState.value === 'failed') return t('chat.copy_failed')
  return t('chat.copy')
})

async function writeClipboardText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 剪贴板 API 不可用时退回旧式复制
  }
  try {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.setAttribute('readonly', '')
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(textarea)
    return ok
  } catch {
    return false
  }
}

async function handleCopyMessage() {
  if (!canCopyMessage.value || copyState.value === 'done') return
  const ok = await writeClipboardText(String(props.msg?.content || ''))
  copyState.value = ok ? 'done' : 'failed'
  window.clearTimeout(copyResetTimer)
  copyResetTimer = window.setTimeout(() => {
    copyState.value = 'idle'
  }, 1600)
}

onBeforeUnmount(() => {
  window.clearTimeout(copyResetTimer)
})

function handleClosePopover() {
  isPopoverOpen.value = false
}

async function handleSubmitDecision(payload: ChatDecisionPayload) {
  await props.vm.submitMessageDecision(props.msg.id, payload)
  isPopoverOpen.value = false
}

function handleSaveDiagnosis(payload: Record<string, any>) {
  props.vm.saveDiagnosisResult(payload, props.msg.id)
}

function handleExportDiagnosis(payload: Record<string, any>) {
  if (typeof props.vm.exportDiagnosisResult === 'function') {
    props.vm.exportDiagnosisResult(payload)
  }
}

function handleRegenerateDiagnosis() {
  if (typeof props.vm.generateDiagnosisSummary === 'function') {
    props.vm.generateDiagnosisSummary()
  }
}

function openDiagnosisCase(caseId: string) {
  props.vm.router.push(`/workspaces/${props.vm.route.params.wsId}/cases/${caseId}`)
}
</script>

<template>
  <ChatMessageContent
    :msg="msg"
    :author-label="vm.messageAuthorLabel(msg)"
    :time-label="vm.formatMessageTime(msg.created_at)"
    :content="displayContent"
    :is-expert="vm.isMessageWorkspaceExpert(msg)"
    :is-current-user="vm.isMessageFromCurrentUser(msg)"
    :highlighted="vm.highlightedMessageId === msg.id"
    :diagnosis-result="isDiagnosisResult"
  >
    <template v-if="isDiagnosisResult && diagnosisPayload" #body>
      <!-- 问题定位结果：AI 会话反填的结构化卡片（对话内展示，替代独立面板） -->
      <DiagnosisResultCard
        :payload="diagnosisPayload"
        :playbook-provenance="msg.metadata?.playbook_provenance"
        :status="diagnosisStatus"
        :extracted-from-ai="diagnosisExtractedFromAi"
        :case-link="String(vm.diagnosisCaseLink || '')"
        :saving="Boolean(vm.diagnosisResultSaving)"
        :case-creating="Boolean(vm.diagnosisCaseCreating)"
        :summarizing="Boolean(vm.diagnosisSummarizing)"
        :adopted="Boolean(vm.isDiagnosisAdopted)"
        @save="handleSaveDiagnosis"
        @confirm="vm.createDiagnosisCase(false)"
        @open-case="openDiagnosisCase"
        @export="handleExportDiagnosis"
        @regenerate="handleRegenerateDiagnosis"
      />
    </template>
    <template #actions>
      <!-- Bubble Actions (Under the bubble): Mark Decision / Undo / Copy -->
      <div v-if="vm.canMarkMessageAsDecision(msg) || msg.decision_id || canCopyMessage || showUndoAction" class="message-actions-row">
        <div class="decision-action-wrapper" v-if="vm.canMarkMessageAsDecision(msg)">
          <button
            type="button"
            class="message-action-btn message-decision-btn"
            :class="{ 'is-active': isPopoverOpen }"
            :title="$t('chat.decision.mark')"
            @click.stop="handleOpenPopover"
          >
            <svg class="custom-decision-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <defs>
                <linearGradient id="markGrad" x1="5" y1="2" x2="19" y2="22" gradientUnits="userSpaceOnUse">
                  <stop offset="0%" stop-color="currentColor" stop-opacity="0.7"/>
                  <stop offset="100%" stop-color="currentColor" stop-opacity="1"/>
                </linearGradient>
                <linearGradient id="markShine" x1="5" y1="2" x2="12" y2="10" gradientUnits="userSpaceOnUse">
                  <stop offset="0%" stop-color="#ffffff" stop-opacity="0.6"/>
                  <stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>
                </linearGradient>
              </defs>
              <!-- Glassy Bookmark Shape -->
              <path d="M6 4C6 2.89543 6.89543 2 8 2H16C17.1046 2 18 2.89543 18 4V22.5L12 18.5L6 22.5V4Z" fill="url(#markGrad)"/>
              <path d="M6 4C6 2.89543 6.89543 2 8 2H16C17.1046 2 18 2.89543 18 4V22.5L12 18.5L6 22.5V4Z" fill="url(#markShine)"/>
              <circle cx="12" cy="8.5" r="2.5" fill="#ffffff" fill-opacity="0.95"/>
            </svg>
          </button>

          <DecisionMarkPopover
            :show="isPopoverOpen"
            :message="msg"
            :saving="vm.chatDecisionSaving"
            @close="handleClosePopover"
            @submit="handleSubmitDecision"
          />
        </div>
        <span v-else-if="msg.decision_id" class="message-decision-badge">
            <svg class="custom-decision-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <defs>
                <linearGradient id="markGrad2" x1="5" y1="2" x2="19" y2="22" gradientUnits="userSpaceOnUse">
                  <stop offset="0%" stop-color="currentColor" stop-opacity="0.7"/>
                  <stop offset="100%" stop-color="currentColor" stop-opacity="1"/>
                </linearGradient>
                <linearGradient id="markShine2" x1="5" y1="2" x2="12" y2="10" gradientUnits="userSpaceOnUse">
                  <stop offset="0%" stop-color="#ffffff" stop-opacity="0.6"/>
                  <stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>
                </linearGradient>
              </defs>
              <path d="M6 4C6 2.89543 6.89543 2 8 2H16C17.1046 2 18 2.89543 18 4V22.5L12 18.5L6 22.5V4Z" fill="url(#markGrad2)"/>
              <path d="M6 4C6 2.89543 6.89543 2 8 2H16C17.1046 2 18 2.89543 18 4V22.5L12 18.5L6 22.5V4Z" fill="url(#markShine2)"/>
              <circle cx="12" cy="8.5" r="2.5" fill="#ffffff" fill-opacity="0.95"/>
            </svg>
          <span>{{ $t('chat.decision.marked') }}</span>
        </span>

        <button
          v-if="showUndoAction"
          type="button"
          class="message-action-btn message-undo-btn"
          :disabled="Boolean(vm.isUndoing)"
          :class="{ 'is-loading': isUndoingMessage }"
          :aria-busy="isUndoingMessage"
          :aria-label="isUndoingMessage ? $t('chat.undo.in_progress') : $t('chat.undo.message')"
          :title="$t('chat.undo.message')"
          @click.stop="handleUndoMessage"
        >
          <Loader2 v-if="isUndoingMessage" class="undo-icon undo-spin" />
          <Undo2 v-else class="undo-icon" />
        </button>

        <button
          v-if="canCopyMessage"
          type="button"
          class="message-action-btn message-copy-btn"
          :class="{ 'is-done': copyState === 'done', 'is-failed': copyState === 'failed' }"
          :title="copyTitle"
          @click.stop="handleCopyMessage"
        >
          <Check v-if="copyState === 'done'" class="copy-icon" />
          <Copy v-else class="copy-icon" />
        </button>
      </div>
    </template>
  </ChatMessageContent>
</template>

<style scoped>
.message-wrapper.is-collab-preinput .message-actions-row {
  justify-content: flex-end;
}

.message-actions-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  margin-top: 2px;
  min-height: 20px;
}

.role-assistant .message-actions-row,
.role-system .message-actions-row {
  justify-content: flex-start;
}

.decision-action-wrapper {
  position: relative;
  display: inline-flex;
}

.message-action-btn,
.message-decision-badge,
.message-decision-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  border-radius: 999px;
  font-size: 0.65rem;
  font-weight: 700;
  transition: all 0.15s ease;
}

.message-action-btn {
  width: 22px;
  height: 22px;
  border: 1px solid rgba(255, 255, 255, 0.4);
  background: rgba(248, 250, 252, 0.6);
  backdrop-filter: blur(4px);
  color: #94a3b8;
  padding: 0;
  cursor: pointer;
  opacity: 0;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}

.message-wrapper:hover .message-action-btn,
.message-action-btn.is-active,
.message-action-btn.is-done,
.message-action-btn.is-failed,
.message-action-btn.is-loading {
  opacity: 1;
}

.message-action-btn:hover:not(:disabled),
.message-wrapper:hover .message-action-btn {
  color: #64748b;
  border-color: rgba(203, 213, 225, 0.6);
  background: rgba(241, 245, 249, 0.85);
}

.message-action-btn:disabled {
  cursor: wait;
  opacity: 0.8;
}

.message-undo-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%) !important;
  border-color: rgba(251, 191, 36, 0.68) !important;
  color: #d97706 !important;
  transform: scale(1.08) translateY(-1px);
  box-shadow: 0 4px 10px -2px rgba(245, 158, 11, 0.18), 0 2px 4px -2px rgba(245, 158, 11, 0.12) !important;
}

.message-copy-btn:hover,
.message-copy-btn.is-done {
  background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%) !important;
  border-color: rgba(134, 239, 172, 0.6) !important;
  color: #16a34a !important;
  transform: scale(1.08) translateY(-1px);
  box-shadow: 0 4px 10px -2px rgba(22, 163, 74, 0.15), 0 2px 4px -2px rgba(22, 163, 74, 0.1) !important;
}

.message-copy-btn.is-failed {
  background: rgba(254, 242, 242, 0.92) !important;
  border-color: rgba(252, 165, 165, 0.6) !important;
  color: #dc2626 !important;
}

.copy-icon {
  width: 12px;
  height: 12px;
}

.undo-icon {
  width: 12px;
  height: 12px;
}

.undo-spin {
  animation: undo-spin 0.9s linear infinite;
}

@keyframes undo-spin {
  to { transform: rotate(360deg); }
}

.message-wrapper:hover .message-decision-btn {
  color: #64748b;
  border-color: rgba(203, 213, 225, 0.6);
  background: rgba(241, 245, 249, 0.85);
}

.message-decision-btn:hover,
.message-decision-btn.is-active {
  background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%) !important;
  border-color: rgba(147, 197, 253, 0.6) !important;
  color: #2563eb !important;
  transform: scale(1.08) translateY(-1px);
  box-shadow: 0 4px 10px -2px rgba(37, 99, 235, 0.15), 0 2px 4px -2px rgba(37, 99, 235, 0.1) !important;
}

.message-decision-badge {
  padding: 2px 8px;
  min-height: 20px;
  border: 1px solid rgba(22, 163, 74, 0.24);
  background: rgba(240, 253, 244, 0.92);
  color: #15803d;
}

.custom-decision-icon {
  width: 12px;
  height: 12px;
  filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.1));
  transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.message-decision-btn:hover .custom-decision-icon,
.message-decision-btn.is-active .custom-decision-icon {
  transform: scale(1.12);
  filter: drop-shadow(0 2px 4px rgba(37, 99, 235, 0.25));
}

</style>
