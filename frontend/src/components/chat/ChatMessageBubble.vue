<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Bot,
  Copy,
  Check,
  Undo2,
  Loader2,
} from 'lucide-vue-next'
import DecisionMarkPopover from './DecisionMarkPopover.vue'
import DiagnosisResultCard from './DiagnosisResultCard.vue'
import UserAvatar from '@/components/user/UserAvatar.vue'
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
const isFromCurrentUser = computed(() => Boolean(props.vm?.isMessageFromCurrentUser?.(props.msg)))
const memberColor = computed(() => props.vm?.messageAuthorColor?.(props.msg) || '#0EA5E9')

const metadata = computed(() => {
  const meta = props.msg?.metadata
  return meta && typeof meta === 'object' ? meta : null
})
const collabParticipants = computed(() => {
  if (msgRole.value !== 'user' || !metadata.value?.pre_input_id) return []
  const participants = metadata.value.participants
  return Array.isArray(participants) ? participants : []
})
const isCollabPreInput = computed(() => collabParticipants.value.length > 0)
// 共享文档字符级 segment（原作者 + 修改者）；兼容旧消息的 lines 与旧版 segments
const collabSegments = computed(() => {
  if (!isCollabPreInput.value) return []
  const segments = metadata.value?.segments
  if (Array.isArray(segments) && segments.length > 0) {
    return segments.map((s: any) => ({
      created_by: String(s?.created_by ?? s?.user_id ?? ''),
      created_by_name: String(s?.created_by_name ?? s?.display_name ?? ''),
      updated_by: String(s?.updated_by ?? s?.created_by ?? s?.user_id ?? ''),
      updated_by_name: String(s?.updated_by_name ?? s?.created_by_name ?? s?.display_name ?? ''),
      modified: Boolean(s?.modified),
      text: String(s?.text ?? s?.content ?? ''),
    }))
  }
  const lines = metadata.value?.lines
  if (Array.isArray(lines) && lines.length > 0) {
    return lines.map((l: any) => ({
      created_by: String(l?.created_by ?? l?.user_id ?? ''),
      created_by_name: String(l?.created_by_name ?? l?.display_name ?? ''),
      updated_by: String(l?.updated_by ?? l?.user_id ?? ''),
      updated_by_name: String(l?.updated_by_name ?? l?.display_name ?? ''),
      modified: Boolean(l?.modified),
      text: `${String(l?.text ?? '')}\n`,
    }))
  }
  return []
})

const segmentTitle = (seg: any) => (
  seg.modified
    ? `${seg.created_by_name}（${seg.updated_by_name} 修改）`
    : String(seg.created_by_name || '')
)

// 头像内联在“时间+姓名”元信息行内：他人消息行首、本人/协作消息行尾；assistant 用原小图标
const showLeadingAvatar = computed(() => (
  msgRole.value === 'user' && !isFromCurrentUser.value && !isCollabPreInput.value
))
const showTrailingAvatar = computed(() => (
  msgRole.value === 'user' && !isCollabPreInput.value && isFromCurrentUser.value
) || isCollabPreInput.value)

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
        'is-collab-preinput': isCollabPreInput,
        'is-diagnosis-result': isDiagnosisResult,
      }
    ]"
    :style="{ '--member-color': memberColor }"
  >
    <div class="message-stack">
      <div class="message-meta">
        <UserAvatar
          v-if="showLeadingAvatar"
          class="meta-avatar"
          :display-name="msg.creator_display_name"
          :user-id="msg.creator_id"
          :avatar-svg="msg.creator_avatar_svg"
          :avatar-url="msg.creator_avatar_url"
          size="xs"
          :accent-color="memberColor"
        />
        <Bot v-else-if="msgRole === 'assistant' || msgRole === 'system'" class="w-3 h-3 message-role-icon" />
        <time class="message-time">{{ vm.formatMessageTime(msg.created_at) }}</time>
        <span
          v-if="isCollabPreInput"
          class="collab-preinput-badge"
          :title="t('chat.collab_preinput_title', { count: collabParticipants.length })"
        >
          <span>{{ $t('chat.collab_preinput_label') }}</span>
          <span class="collab-count">{{ collabParticipants.length }}</span>
        </span>
        <span class="message-author" :style="msgRole === 'user' ? { color: memberColor } : undefined">{{ vm.messageAuthorLabel(msg) }}</span>
        <span v-if="vm.isMessageWorkspaceExpert(msg)" class="message-expert-badge">
          {{ $t('settings.members.expert_badge') }}
        </span>
        <UserAvatar
          v-if="showTrailingAvatar"
          class="meta-avatar"
          :display-name="msg.creator_display_name"
          :user-id="msg.creator_id"
          :avatar-svg="msg.creator_avatar_svg"
          :avatar-url="msg.creator_avatar_url"
          size="xs"
          :accent-color="isCollabPreInput ? vm.memberColorFor(msg.creator_id) : memberColor"
        />
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
        :summarizing="Boolean(vm.diagnosisSummarizing)"
        :adopted="Boolean(vm.isDiagnosisAdopted)"
        @save="handleSaveDiagnosis"
        @confirm="vm.createDiagnosisCase(false)"
        @open-case="openDiagnosisCase"
        @export="handleExportDiagnosis"
        @regenerate="handleRegenerateDiagnosis"
      />

      <div v-else class="message-bubble">
        <!-- 协作预输入：字符级归属渲染（作者色下划线，悬停可见原作者/修改者） -->
        <div v-if="isCollabPreInput && collabSegments.length > 0" class="collab-doc">
          <span
            v-for="(seg, index) in collabSegments"
            :key="index"
            class="collab-seg"
            :class="{ 'is-modified': seg.modified, 'is-new': seg.created_by !== msg.creator_id && !seg.modified }"
            :style="{
              '--seg-color': vm.memberColorFor(seg.created_by),
              '--seg-modifier-color': vm.memberColorFor(seg.updated_by),
              '--seg-tint': vm.memberColorRgba ? vm.memberColorRgba(seg.created_by, 0.1) : 'transparent',
            }"
            :title="segmentTitle(seg)"
          >{{ seg.text }}</span>
        </div>
        <div v-else class="msg-content">{{ msg.content }}</div>
      </div>

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
    </div>
  </div>

</template>

<style scoped>
.message-wrapper {
  display: flex;
  min-width: 0;
  max-width: min(78%, 720px);
}

.message-wrapper.is-diagnosis-result {
  width: min(78%, 720px);
  max-width: 100%;
}

.message-wrapper.is-diagnosis-result .message-stack {
  width: 100%;
}
/* 多人会话：仅本人消息右对齐，其他成员与 assistant 一律左对齐 */
.role-user.from-current-user {
  align-self: flex-end;
}
.role-user:not(.from-current-user),
.role-system,
.role-assistant {
  align-self: flex-start;
}

.message-wrapper.is-highlighted {
  animation: context-reference-pulse 1.3s ease-in-out 2;
}

.message-stack {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.role-user.from-current-user .message-stack {
  align-items: flex-end;
}

.role-user:not(.from-current-user) .message-stack,
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
  flex-wrap: wrap;
}

.role-user.from-current-user .message-meta {
  justify-content: flex-end;
}

.role-user:not(.from-current-user) .message-meta,
.role-system .message-meta,
.role-assistant .message-meta {
  justify-content: flex-start;
}

/* 头像内联于元信息行，与时间/姓名水平对齐 */
.meta-avatar {
  flex: 0 0 auto;
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

.collab-preinput-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 18px;
  padding: 0 7px;
  border-radius: 999px;
  border: 1px solid var(--color-primary-100, #E0F2FE);
  background: var(--color-primary-50, #F0F9FF);
  color: var(--color-primary-700, #0369A1);
  font-size: 0.68rem;
  font-weight: 700;
  white-space: nowrap;
}

.collab-count {
  min-width: 12px;
  text-align: center;
}

.message-role-icon {
  flex: 0 0 auto;
  color: #475569;
}

.message-expert-badge {
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

.role-user.from-current-user .message-bubble {
  border-top-right-radius: 14px;
  border-color: var(--member-color, #0EA5E9);
  background: #ffffff;
}

.role-user:not(.from-current-user) .message-bubble {
  border-top-left-radius: 14px;
  background: #F8FAFC;
  border-color: #E2E8F0;
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
  box-shadow: 0 10px 24px rgba(22, 101, 52, 0.08);
}

.role-user.from-current-user.from-workspace-expert .message-bubble {
  border-color: #166534;
}

/* 协作预输入气泡：一律右对齐、无左侧色条，分段结构化展示，行尾显示发起人头像 */
.message-wrapper.is-collab-preinput {
  align-self: flex-end;
}

.message-wrapper.is-collab-preinput .message-stack {
  align-items: flex-end;
}

.message-wrapper.is-collab-preinput .message-meta {
  justify-content: flex-end;
}

.message-wrapper.is-collab-preinput .message-actions-row {
  justify-content: flex-end;
}

.message-wrapper.is-collab-preinput .message-bubble {
  background: var(--color-surface-white, #fff);
  border: 1px solid var(--color-primary-100, #E0F2FE);
  border-top-right-radius: 14px;
  min-width: 220px;
}

/* 协作文档：字符级归属，作者色实线下划线 + 被改段虚线（实色，不依赖 color-mix） */
.collab-doc {
  font-size: 0.9rem;
  line-height: 1.8;
  color: #1f2937;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.collab-seg {
  border-bottom: 2px solid var(--seg-color, #0284C7);
  border-radius: 1px;
}

.collab-seg.is-modified {
  border-bottom-style: dashed;
  border-bottom-color: var(--seg-modifier-color, #0284C7);
}

/* 他人新增的文字：成员色淡底强调 */
.collab-seg.is-new {
  background: var(--seg-tint, transparent);
  border-radius: 3px;
  padding: 0 1px;
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
.role-system .message-actions-row,
.role-user:not(.from-current-user) .message-actions-row {
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

@keyframes context-reference-pulse {
  0% { filter: drop-shadow(0 0 0 rgba(14, 165, 233, 0)); }
  45% { filter: drop-shadow(0 0 12px rgba(14, 165, 233, 0.45)); }
  100% { filter: drop-shadow(0 0 0 rgba(14, 165, 233, 0)); }
}
</style>
