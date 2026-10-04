<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Bot } from '@/components/icons'
import UserAvatar from '@/components/user/UserAvatar.vue'
import { messageAuthorColor, memberColorFor, memberColorRgba } from '@/composables/chat/message/memberColor'
import type { ChatMessageFields } from '@/composables/chat/shared/messageIdentity'

// 只负责消息展示；交互和诊断结果由主会话通过插槽提供。
const props = defineProps<{
  msg: Partial<ChatMessageFields>
  authorLabel: string
  timeLabel: string
  content?: string
  isExpert?: boolean
  isCurrentUser?: boolean
  highlighted?: boolean
  diagnosisResult?: boolean
}>()

const { t } = useI18n()
const msgRole = computed(() => String(props.msg?.role || '').toLowerCase())
const memberColor = computed(() => messageAuthorColor(props.msg))

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

// 头像内联在“时间+姓名”元信息行内：用户消息一律行尾；assistant 用原小图标
const showTrailingAvatar = computed(() => (
  msgRole.value === 'user' || isCollabPreInput.value
))
</script>

<template>
  <div
    class="message-wrapper"
    :data-message-id="msg.id"
    :class="[
      `role-${msgRole}`,
      {
        'from-current-user': isCurrentUser,
        'from-workspace-expert': isExpert,
        'is-highlighted': highlighted,
        'is-collab-preinput': isCollabPreInput,
        'is-diagnosis-result': diagnosisResult,
      }
    ]"
    :style="{ '--member-color': memberColor }"
  >
    <div class="message-stack">
      <div class="message-meta">
        <Bot v-if="msgRole === 'assistant' || msgRole === 'system'" class="w-3 h-3 message-role-icon" />
        <time class="message-time">{{ timeLabel }}</time>
        <span
          v-if="isCollabPreInput"
          class="collab-preinput-badge"
          :title="t('chat.collab_preinput_title', { count: collabParticipants.length })"
        >
          <span>{{ $t('chat.collab_preinput_label') }}</span>
          <span class="collab-count">{{ collabParticipants.length }}</span>
        </span>
        <span class="message-author" :title="authorLabel" :style="msgRole === 'user' ? { color: memberColor } : undefined">{{ authorLabel }}</span>
        <span v-if="isExpert" class="message-expert-badge">
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
          :accent-color="memberColor"
        />
      </div>

      <slot name="body">
        <div class="message-bubble">
          <!-- 协作预输入：字符级归属渲染（作者色下划线，悬停可见原作者/修改者） -->
          <div v-if="isCollabPreInput && collabSegments.length > 0" class="collab-doc">
            <span
              v-for="(seg, index) in collabSegments"
              :key="index"
              class="collab-seg"
              :class="{ 'is-modified': seg.modified, 'is-new': seg.created_by !== msg.creator_id && !seg.modified }"
              :style="{
                '--seg-color': memberColorFor(seg.created_by),
                '--seg-modifier-color': memberColorFor(seg.updated_by),
                '--seg-tint': memberColorRgba(seg.created_by, 0.1),
              }"
              :title="segmentTitle(seg)"
            >{{ seg.text }}</span>
          </div>
          <div v-else class="msg-content">{{ content ?? msg.content }}</div>
        </div>
      </slot>
      <slot name="actions" />
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
/* 用户消息一律右对齐；assistant/system 左对齐 */
.role-user {
  align-self: flex-end;
}
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
  max-width: 100%;
  min-width: 0;
}

.role-user .message-meta {
  justify-content: flex-end;
}

.role-system .message-meta,
.role-assistant .message-meta {
  justify-content: flex-start;
}

/* 头像内联于元信息行，与时间/姓名水平对齐 */
.meta-avatar {
  flex: 0 0 auto;
}

.message-time {
  flex-shrink: 0;
  color: #475569;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.message-author {
  min-width: 0;
  font-weight: 650;
  color: #0f172a;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.collab-preinput-badge {
  flex-shrink: 0;
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
  flex-shrink: 0;
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
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
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
  border-color: var(--member-color, #0EA5E9);
  background: #ffffff;
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

.role-user.from-workspace-expert .message-bubble {
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

.message-wrapper.is-collab-preinput .message-bubble {
  background: var(--color-surface-white, #fff);
  border: 1px solid var(--color-primary-100, #E0F2FE);
  border-top-right-radius: 14px;
  min-width: min(220px, 100%);
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

@keyframes context-reference-pulse {
  0% { filter: drop-shadow(0 0 0 rgba(14, 165, 233, 0)); }
  45% { filter: drop-shadow(0 0 12px rgba(14, 165, 233, 0.45)); }
  100% { filter: drop-shadow(0 0 0 rgba(14, 165, 233, 0)); }
}
</style>
