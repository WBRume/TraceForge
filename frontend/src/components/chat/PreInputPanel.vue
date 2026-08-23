<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Check, Circle, Send, X } from 'lucide-vue-next'
import UserAvatar from '@/components/user/UserAvatar.vue'

const props = defineProps<{
  vm: any
}>()

const preInput = computed(() => props.vm?.activePreInput)
const isCreator = computed(() => Boolean(props.vm?.isPreInputCreator))
const canModifyExisting = computed(() => Boolean(props.vm?.canEditPreInputShared))
const hasParticipated = computed(() => Boolean(props.vm?.myPreInputParticipation))

// ── 倒计时 ──
const nowTs = ref(Date.now())
let ticker: number | null = null
onMounted(() => {
  ticker = window.setInterval(() => {
    nowTs.value = Date.now()
  }, 1000)
})
onBeforeUnmount(() => {
  if (ticker !== null) window.clearInterval(ticker)
  document.removeEventListener('mouseup', onDocumentMouseUp)
})

const deadlineTs = computed(() => {
  const raw = preInput.value?.deadline_at
  if (!raw) return 0
  const parsed = new Date(raw.includes('T') ? raw : `${raw}Z`).getTime()
  return Number.isNaN(parsed) ? 0 : parsed
})
const remainingSeconds = computed(() => Math.max(0, Math.floor((deadlineTs.value - nowTs.value) / 1000)))
const countdownText = computed(() => {
  const total = remainingSeconds.value
  const mm = String(Math.floor(total / 60)).padStart(2, '0')
  const ss = String(total % 60).padStart(2, '0')
  return `${mm}:${ss}`
})
const isDeadlineReached = computed(() => remainingSeconds.value <= 0)

const mentionees = computed(() => preInput.value?.mentionees || [])
const volunteers = computed(() => preInput.value?.volunteers || [])
const documentSegments = computed(() => preInput.value?.document_segments || [])
const doneCount = computed(() => mentionees.value.filter((m: any) => m.done).length)

const memberColor = (userId: string) => props.vm?.memberColorFor?.(userId) || '#0284C7'

const segmentTitle = (seg: any) => (
  seg.modified
    ? `${seg.created_by_name}（${seg.updated_by_name} 修改）`
    : String(seg.created_by_name || '')
)

// ── 框选提交输入 ──
const docContainerRef = ref<HTMLElement | null>(null)
const spanPopover = ref<{
  visible: boolean
  start: number
  end: number
  anchor: string
  top: number
  left: number
} | null>(null)
const spanDraft = ref('')
const spanSubmitting = ref(false)

// 无修改权限且框选了文字 → 只能作为纯插入（插到所选文字之前）
const spanInsertOnly = computed(() => !canModifyExisting.value && Boolean(spanPopover.value?.anchor))

const openSpanPopover = async (start: number, end: number, anchor: string, rect: DOMRect) => {
  spanPopover.value = {
    visible: true,
    start,
    end,
    anchor,
    top: rect.top,
    left: rect.left + Math.min(rect.width / 2, 180),
  }
  spanDraft.value = canModifyExisting.value ? anchor : ''
  await nextTick()
}

const closeSpanPopover = () => {
  spanPopover.value = null
  spanDraft.value = ''
}

const onDocumentMouseUp = async () => {
  if (!preInput.value || preInput.value.status !== 'COLLECTING') return
  const selection = window.getSelection()
  const container = docContainerRef.value
  if (!selection || selection.isCollapsed || !container) {
    return
  }
  const range = selection.getRangeAt(0)
  if (!container.contains(range.commonAncestorContainer)) return

  const selectedText = range.toString()
  if (!selectedText.trim()) return

  // 计算选区在全文中的字符偏移
  const preRange = document.createRange()
  preRange.selectNodeContents(container)
  preRange.setEnd(range.startContainer, range.startOffset)
  const start = preRange.toString().length
  const end = start + selectedText.length

  const anchor = String(preInput.value.main_text || '').slice(start, end)
  if (anchor !== selectedText) return // 渲染与文本不一致，忽略

  const rect = range.getBoundingClientRect()
  await openSpanPopover(start, end, anchor, rect)
}

const submitSpan = () => {
  const popover = spanPopover.value
  if (!popover) return
  const pi = preInput.value
  if (!pi) return
  const replacement = spanDraft.value
  if (spanInsertOnly.value) {
    // 无修改权限：纯插入到所选文字之前（不改动原有字符）
    if (!replacement.trim()) return
    props.vm.replacePreInputSpan(popover.start, popover.start, '', replacement)
  } else {
    if (!replacement.trim()) return
    props.vm.replacePreInputSpan(popover.start, popover.end, popover.anchor, replacement)
  }
  spanSubmitting.value = false
  closeSpanPopover()
  window.getSelection()?.removeAllRanges()
}

onMounted(() => {
  document.addEventListener('mouseup', onDocumentMouseUp)
})

// 文档更新时关闭弹层（选区已失效）
watch(() => preInput.value?.main_text, () => {
  closeSpanPopover()
})

// ── 全文编辑（兜底，适合大改） ──
const docEditing = ref(false)
const docDraft = ref('')
const originalText = ref('')

const startEditDocument = () => {
  originalText.value = String(preInput.value?.main_text || '')
  docDraft.value = originalText.value
  docEditing.value = true
}

// 字符级插行校验：原文字符按顺序全部保留（只允许新增字符）
const isInsertOnly = (oldText: string, newText: string): boolean => {
  let i = 0
  for (const ch of newText) {
    if (i < oldText.length && ch === oldText[i]) i++
  }
  return i === oldText.length
}

const insertOnlyViolation = computed(() => {
  if (!docEditing.value || canModifyExisting.value) return false
  return !isInsertOnly(originalText.value, docDraft.value)
})

const saveDocument = () => {
  if (!docDraft.value.trim() || insertOnlyViolation.value) return
  props.vm.editPreInputDocument(docDraft.value)
  docEditing.value = false
}

// 编辑期间文档被他人更新时，若本地未改动则跟随最新内容
watch(
  () => preInput.value?.main_text,
  (text, prev) => {
    if (docEditing.value && (docDraft.value === '' || docDraft.value === prev)) {
      docDraft.value = text || ''
    }
  },
)

const markDone = () => {
  props.vm.markPreInputDone()
}

const submitNow = () => {
  if (!isCreator.value) return
  props.vm.submitPreInputManually()
}
const cancelCollect = () => {
  if (!isCreator.value) return
  props.vm.cancelPreInput()
}
</script>

<template>
  <div v-if="preInput" class="preinput-panel">
    <!-- 头部：发起人 + 标题 + 倒计时 -->
    <div class="panel-header">
      <UserAvatar
        :display-name="preInput.creator?.display_name"
        :user-id="preInput.creator?.user_id"
        :avatar-svg="preInput.creator?.avatar_svg"
        :avatar-url="preInput.creator?.avatar_url"
        size="sm"
        :accent-color="memberColor(preInput.creator?.user_id)"
      />
      <span class="panel-title">{{ $t('preInput.panel_title') }}</span>
      <span class="panel-sub">· {{ preInput.creator?.display_name }}</span>
      <span class="countdown" :class="{ 'is-urgent': remainingSeconds <= 30 && !isDeadlineReached, 'is-expired': isDeadlineReached }">
        {{ countdownText }}
      </span>
    </div>

    <!-- 共享文档：字符级归属渲染，框选文字直接提交输入 -->
    <template v-if="!docEditing">
      <div class="document-block">
        <div ref="docContainerRef" class="document-text" @mouseup="onDocumentMouseUp">
          <span
            v-for="(seg, index) in documentSegments"
            :key="index"
            class="doc-seg"
            :class="{ 'is-modified': seg.modified, 'is-new': seg.created_by !== preInput.creator?.user_id && !seg.modified }"
            :style="{
              '--seg-color': memberColor(seg.created_by),
              '--seg-modifier-color': memberColor(seg.updated_by),
            }"
            :title="segmentTitle(seg)"
          >{{ seg.text }}</span>
        </div>
        <button type="button" class="text-btn" @click="startEditDocument">
          {{ $t('preInput.edit_full_text') }}
        </button>
      </div>
      <div class="doc-edit-hint">{{ $t('preInput.span_select_hint') }}</div>
    </template>
    <template v-else>
      <textarea v-model="docDraft" class="panel-textarea doc-textarea" rows="6"></textarea>
      <div v-if="!canModifyExisting" class="doc-edit-hint">{{ $t('preInput.edit_no_permission_hint') }}</div>
      <div v-if="insertOnlyViolation" class="doc-violation">{{ $t('preInput.edit_violation') }}</div>
      <div class="row-actions">
        <button
          type="button"
          class="btn-mini-primary"
          :disabled="!docDraft.trim() || insertOnlyViolation"
          @click="saveDocument"
        >{{ $t('common.save') }}</button>
        <button type="button" class="btn-mini-ghost" @click="docEditing = false">{{ $t('common.cancel') }}</button>
      </div>
    </template>

    <!-- 成员参与状态：单行紧凑 chips -->
    <div class="members-row" :title="$t('preInput.member_status_label')">
      <span class="members-progress">{{ doneCount }}/{{ mentionees.length }}</span>
      <template v-if="mentionees.length === 0 && volunteers.length === 0">
        <span class="no-members-hint">{{ $t('preInput.no_mentions_hint') }}</span>
      </template>
      <span
        v-for="member in mentionees"
        :key="member.user_id"
        class="member-chip"
        :class="{ 'is-done': member.done }"
      >
        <UserAvatar
          :display-name="member.display_name"
          :user-id="member.user_id"
          :avatar-svg="member.avatar_svg"
          :avatar-url="member.avatar_url"
          size="xs"
          :accent-color="memberColor(member.user_id)"
        />
        <span class="member-chip-name">{{ member.display_name }}</span>
        <Check v-if="member.done" class="w-2 h-2 chip-status-done" />
        <Circle v-else class="w-1.5 h-1.5 chip-status-pending" />
      </span>
      <span
        v-for="member in volunteers"
        :key="`vol-${member.user_id}`"
        class="member-chip is-volunteer"
        :title="$t('preInput.volunteer_hint')"
      >
        <UserAvatar
          :display-name="member.display_name"
          :user-id="member.user_id"
          :avatar-svg="member.avatar_svg"
          :avatar-url="member.avatar_url"
          size="xs"
          :accent-color="memberColor(member.user_id)"
        />
        <span class="member-chip-name">{{ member.display_name }}</span>
        <Check class="w-2 h-2 chip-status-done" />
      </span>
    </div>

    <!-- 底部：参与操作 + 发起人操作 -->
    <div class="panel-footer">
      <div class="self-actions">
        <span v-if="hasParticipated" class="participated-hint">
          <Check class="w-2 h-2" />
          {{ $t('preInput.participated') }}
        </span>
        <button v-else type="button" class="btn-mini-ghost" @click="markDone">
          {{ $t('preInput.mark_done') }}
        </button>
      </div>

      <div v-if="isCreator" class="creator-actions">
        <button type="button" class="btn-mini-ghost" @click="cancelCollect">
          <X class="w-2 h-2" />
          {{ $t('preInput.cancel_collect') }}
        </button>
        <button type="button" class="btn-mini-primary" @click="submitNow">
          <Send class="w-2 h-2" />
          {{ $t('preInput.submit_now') }}
        </button>
      </div>
    </div>

    <!-- 框选输入弹层：跟随选区浮层 -->
    <Teleport to="body">
      <div
        v-if="spanPopover?.visible"
        class="span-popover"
        :style="{ top: `${spanPopover.top}px`, left: `${spanPopover.left}px` }"
      >
        <div class="span-popover-anchor">{{ spanPopover.anchor }}</div>
        <textarea
          v-model="spanDraft"
          class="span-input"
          rows="2"
          :placeholder="spanInsertOnly
            ? $t('preInput.span_insert_placeholder')
            : $t('preInput.span_replace_placeholder')"
          @keydown.enter.exact.prevent="submitSpan"
        ></textarea>
        <div v-if="spanInsertOnly" class="span-hint">{{ $t('preInput.span_insert_only_hint') }}</div>
        <div class="span-actions">
          <button type="button" class="btn-mini-primary" :disabled="!spanDraft.trim()" @click="submitSpan">
            {{ $t('preInput.span_submit') }}
          </button>
          <button type="button" class="btn-mini-ghost" @click="closeSpanPopover">{{ $t('common.cancel') }}</button>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.preinput-panel {
  margin: var(--space-4) var(--space-6) 0;
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-lg);
  background: var(--color-surface-white);
  box-shadow: var(--shadow-sm);
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  position: relative;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.panel-title {
  font-weight: 600;
  font-size: 0.8125rem;
  color: var(--color-text-title);
  white-space: nowrap;
}

.panel-sub {
  font-size: 0.75rem;
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.countdown {
  margin-left: auto;
  padding: 2px 8px;
  border-radius: var(--radius-full);
  background: var(--color-primary-50);
  color: var(--color-primary-700);
  font-weight: 600;
  font-size: 0.72rem;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.countdown.is-urgent {
  background: #FFFBEB;
  color: #B45309;
}

.countdown.is-expired {
  background: #F1F5F9;
  color: var(--color-text-muted);
}

/* ── 共享文档：字符级归属渲染 ── */
.document-block {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
}

.document-text {
  flex: 1;
  min-width: 0;
  background: #F8FAFC;
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-3);
  font-size: 0.82rem;
  line-height: 1.9;
  color: var(--color-text-body);
  white-space: pre-wrap;
  word-break: break-word;
  cursor: text;
  user-select: text;
}

.doc-seg {
  border-bottom: 2px solid color-mix(in srgb, var(--seg-color, #0284C7) 45%, transparent);
  border-radius: 1px;
}

/* 被他人修改过的段：虚线下划线（悬停可见修改者） */
.doc-seg.is-modified {
  border-bottom-style: dashed;
  border-bottom-color: var(--seg-modifier-color, #0284C7);
}

/* 新增文字段：淡色底强调 */
.doc-seg.is-new {
  background: color-mix(in srgb, var(--seg-color, #0284C7) 8%, transparent);
}

.doc-edit-hint {
  font-size: 0.68rem;
  color: #94A3B8;
  margin-top: -2px;
}

.text-btn {
  border: none;
  background: transparent;
  color: var(--color-primary-600);
  cursor: pointer;
  padding: 2px 4px;
  border-radius: var(--radius-sm);
  font-size: 0.72rem;
  font-weight: 500;
  flex: 0 0 auto;
  white-space: nowrap;
  transition: color var(--transition-fast);
}

.text-btn:hover {
  color: var(--color-primary-700);
  text-decoration: underline;
}

.panel-textarea {
  width: 100%;
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-md);
  background: var(--color-surface-white);
  padding: 8px 10px;
  font-size: 0.8rem;
  font-family: var(--font-body);
  line-height: 1.55;
  color: var(--color-text-body);
  resize: vertical;
  outline: none;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
  box-sizing: border-box;
}

.panel-textarea:focus {
  border-color: var(--color-primary-500);
  box-shadow: 0 0 0 3px var(--color-primary-100);
}

.doc-textarea {
  font-family: var(--font-mono, monospace);
  font-size: 0.78rem;
}

.doc-violation {
  font-size: 0.7rem;
  color: #BE123C;
  background: #FFF1F2;
  border: 1px solid #FECDD3;
  border-radius: var(--radius-sm);
  padding: 5px 8px;
  margin-top: 6px;
}

.row-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: 6px;
}

.members-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.members-progress {
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

.no-members-hint {
  font-size: 0.7rem;
  color: #94A3B8;
}

.member-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px 2px 3px;
  border-radius: var(--radius-full);
  background: #F8FAFC;
  border: 1px solid #E2E8F0;
}

.member-chip.is-done {
  background: #F0FDF4;
  border-color: #BBF7D0;
}

.member-chip.is-volunteer {
  border-style: dashed;
}

.member-chip-name {
  font-size: 0.7rem;
  font-weight: 500;
  color: var(--color-text-body);
  max-width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chip-status-done {
  color: var(--color-accent-emerald, #10B981);
}

.chip-status-pending {
  color: #CBD5E1;
}

.btn-mini-primary {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: var(--color-primary-500);
  color: #fff;
  border-radius: var(--radius-md);
  padding: 4px 12px;
  font-size: 0.72rem;
  font-weight: 600;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.btn-mini-primary:hover:not(:disabled) {
  background: var(--color-primary-600);
}

.btn-mini-primary:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.btn-mini-ghost {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid #E2E8F0;
  background: var(--color-surface-white);
  color: #475569;
  border-radius: var(--radius-md);
  padding: 4px 12px;
  font-size: 0.72rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-mini-ghost:hover {
  background: #F8FAFC;
}

.participated-hint {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.72rem;
  color: var(--color-accent-emerald, #10B981);
  font-weight: 600;
}

.panel-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
  border-top: 1px solid rgba(0, 0, 0, 0.05);
  padding-top: var(--space-3);
}

.self-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.creator-actions {
  display: flex;
  gap: var(--space-2);
}
</style>

<!-- 框选弹层挂在 body 下（Teleport），样式需非 scoped -->
<style>
.span-popover {
  position: fixed;
  transform: translate(-50%, calc(-100% - 10px));
  width: 300px;
  background: var(--color-surface-white, #fff);
  border: 1px solid #E2E8F0;
  border-radius: 10px;
  box-shadow: 0 14px 34px rgba(15, 23, 42, 0.16);
  z-index: 3000;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.span-popover-anchor {
  font-size: 0.7rem;
  color: var(--color-text-muted, #64748B);
  background: #F1F5F9;
  border-radius: 6px;
  padding: 4px 8px;
  max-height: 52px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.span-input {
  width: 100%;
  border: 1px solid #E2E8F0;
  border-radius: 8px;
  padding: 7px 9px;
  font-size: 0.78rem;
  font-family: var(--font-body);
  line-height: 1.5;
  color: var(--color-text-body);
  resize: vertical;
  outline: none;
  box-sizing: border-box;
  transition: border-color 150ms, box-shadow 150ms;
}

.span-input:focus {
  border-color: var(--color-primary-500, #0EA5E9);
  box-shadow: 0 0 0 3px var(--color-primary-100, #E0F2FE);
}

.span-hint {
  font-size: 0.68rem;
  color: #B45309;
}

.span-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
</style>
