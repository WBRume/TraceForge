<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  ShieldCheck,
  Bot,
  UserRound,
} from 'lucide-vue-next'
import DecisionMarkPopover from './DecisionMarkPopover.vue'
import DiagnosisResultCard from './DiagnosisResultCard.vue'
import { diagnosisPayloadFromMessage } from '@/types/diagnosis'
import type { ChatDecisionPayload } from '@/composables/useChatDecision'

const props = defineProps<{
  msg: Record<string, any>
  vm: any
}>()

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

function handleOpenPopover() {
  isPopoverOpen.value = true
}

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

function openDiagnosisCase(caseId: string) {
  props.vm.router.push(`/ws/${props.vm.route.params.wsId}/cases/${caseId}`)
}
</script>

<template>
  <div
    class="message-wrapper"
    :data-message-id="msg.id"
    :class="[
      `role-${msg.role}`,
      {
        'from-current-user': vm.isMessageFromCurrentUser(msg),
        'from-workspace-expert': vm.isMessageWorkspaceExpert(msg),
        'is-highlighted': vm.highlightedMessageId === msg.id,
      }
    ]"
  >
    <div class="message-stack">
      <div class="message-meta">
        <time class="message-time">{{ vm.formatMessageTime(msg.created_at) }}</time>
        <span class="message-author">{{ vm.messageAuthorLabel(msg) }}</span>
        <span v-if="vm.isMessageWorkspaceExpert(msg)" class="message-pm-badge">PM</span>
        <ShieldCheck v-if="vm.isMessageWorkspaceExpert(msg)" class="w-3 h-3 message-expert-icon" />
        <Bot v-else-if="msg.role === 'assistant'" class="w-3 h-3 message-role-icon" />
        <UserRound v-else class="w-3 h-3 message-role-icon" />
      </div>
      
      <!-- 问题定位结果：AI 会话反填的结构化卡片（对话内展示，替代独立面板） -->
      <DiagnosisResultCard
        v-if="isDiagnosisResult && diagnosisPayload"
        :payload="diagnosisPayload"
        :status="diagnosisStatus"
        :extracted-from-ai="diagnosisExtractedFromAi"
        :case-link="String(vm.diagnosisCaseLink || '')"
        :saving="Boolean(vm.diagnosisResultSaving)"
        :case-creating="Boolean(vm.diagnosisCaseCreating)"
        @save="handleSaveDiagnosis"
        @confirm="vm.createDiagnosisCase(false)"
        @open-case="openDiagnosisCase"
      />

      <div v-else class="message-bubble">
        <div class="msg-content">{{ msg.content }}</div>
      </div>
      
      <!-- Mark Decision Action (Under the bubble) -->
      <div v-if="vm.canMarkMessageAsDecision(msg) || msg.decision_id" class="message-actions-row">
        <div class="decision-action-wrapper" v-if="vm.canMarkMessageAsDecision(msg)">
          <button
            type="button"
            class="message-decision-btn"
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
      </div>
    </div>
  </div>
</template>

<style scoped>
.message-wrapper {
  display: flex;
  max-width: min(78%, 720px);
}
.role-user { align-self: flex-end; }
.role-system,
.role-assistant { align-self: flex-start; }

.message-wrapper.is-highlighted {
  animation: context-reference-pulse 1.3s ease-in-out 2;
}

.message-stack {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.role-user .message-stack {
  align-items: flex-end;
}

.role-system .message-stack,
.role-assistant .message-stack {
  align-items: flex-start;
}

.message-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 18px;
  color: #334155;
  font-size: 0.72rem;
  line-height: 1;
}

.role-user .message-meta {
  justify-content: flex-end;
}

.message-time {
  color: #475569;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.message-author {
  font-weight: 650;
  color: #0f172a;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.message-role-icon,
.message-expert-icon {
  flex: 0 0 auto;
  color: #475569;
}

.message-expert-icon {
  color: #166534;
}

.message-pm-badge {
  display: inline-flex;
  align-items: center;
  height: 18px;
  padding: 0 7px;
  border-radius: 999px;
  border: 1px solid #bbf7d0;
  background: #ecfdf5;
  color: #166534;
  font-size: 0.68rem;
  font-weight: 750;
  letter-spacing: 0;
}

.message-bubble {
  padding: 13px 18px;
  border-radius: 16px;
  font-size: 0.95rem;
  line-height: 1.65;
  color: #1f2937;
  border: 1px solid #d6d3d1;
  background: #f8f7f5;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
}

.role-user .message-bubble {
  border-top-right-radius: 14px;
}

.role-system .message-bubble,
.role-assistant .message-bubble {
  background: #ffffff;
  border-color: #dbe3ea;
  border-top-left-radius: 14px;
}

.role-system .message-bubble {
  background: #f9fafb;
  color: #475569;
}

.from-workspace-expert .message-bubble {
  border-color: #a7f3d0;
  box-shadow: 0 10px 24px rgba(22, 101, 52, 0.08);
}

.msg-content {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
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

.message-decision-btn,
.message-decision-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  border-radius: 999px;
  font-size: 0.65rem;
  font-weight: 700;
  transition: all 0.15s ease;
}

.message-decision-btn {
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

.message-wrapper:hover .message-decision-btn,
.message-decision-btn.is-active {
  opacity: 1;
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

@keyframes context-reference-pulse {
  0% { filter: drop-shadow(0 0 0 rgba(14, 165, 233, 0)); }
  45% { filter: drop-shadow(0 0 12px rgba(14, 165, 233, 0.45)); }
  100% { filter: drop-shadow(0 0 0 rgba(14, 165, 233, 0)); }
}
</style>
