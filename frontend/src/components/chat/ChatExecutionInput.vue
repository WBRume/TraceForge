<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, Search, ShieldCheck, Send, X, Loader2, Square } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import UserAvatar from '@/components/user/UserAvatar.vue'

const { t } = useI18n()

type MentionOption = {
  user_id: string
  display_name: string | null
  avatar_url: string | null
  avatar_svg: string | null
  is_expert: boolean
}

const props = defineProps<{
  modelValue: string
  disabled: boolean
  running: boolean
  canInterrupt: boolean
  interrupting: boolean
  placeholder: string
  sendTitle: string
  interruptTitle: string
  preInputMode?: boolean
  canStartPreInput?: boolean
  searchMembers?: (keyword: string) => Promise<MentionOption[]>
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'update:preInputMode', value: boolean): void
  (e: 'submit'): void
  (e: 'interrupt'): void
  (e: 'start-pre-input', payload: {
    main_text: string
    mentioned_user_ids: string[]
    edit_permission: 'ALL' | 'MENTIONED' | 'EXPERTS' | 'NONE'
    wait_seconds: number
  }): void
}>()

// ── 文本域：多行自动增高 ──
const textareaRef = ref<HTMLTextAreaElement | null>(null)

const autoGrow = () => {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`
}

watch(() => props.modelValue, () => {
  void nextTick(autoGrow)
})

const onTextareaInput = (event: Event) => {
  emit('update:modelValue', (event.target as HTMLTextAreaElement).value)
}

const canSend = computed(() => Boolean(props.modelValue.trim()) && !props.disabled)

const handleKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    if (canSend.value) {
      if (props.preInputMode) emit('start-pre-input', buildPreInputPayload())
      else emit('submit')
    }
  }
}

const handleSendClick = () => {
  if (!canSend.value) return
  if (props.preInputMode) emit('start-pre-input', buildPreInputPayload())
  else emit('submit')
}

// ── 协作预输入模式 ──
const isPreInput = computed(() => Boolean(props.preInputMode) && props.canStartPreInput !== false)

const togglePreInputMode = () => {
  if (props.canStartPreInput === false) return
  emit('update:preInputMode', !props.preInputMode)
}

const editPermission = ref<'ALL' | 'MENTIONED' | 'EXPERTS' | 'NONE'>('NONE')
const waitSeconds = ref(180)

const permissionOptions = computed(() => ([
  { value: 'ALL', label: t('preInput.permission_all') },
  { value: 'MENTIONED', label: t('preInput.permission_mentioned') },
  { value: 'EXPERTS', label: t('preInput.permission_experts') },
  { value: 'NONE', label: t('preInput.permission_none') },
]))
const durationOptions = computed(() => ([
  { value: 60, label: t('preInput.duration_minutes', { n: 1 }) },
  { value: 180, label: t('preInput.duration_minutes', { n: 3 }) },
  { value: 300, label: t('preInput.duration_minutes', { n: 5 }) },
  { value: 600, label: t('preInput.duration_minutes', { n: 10 }) },
]))

// ── 提及成员：工具栏内多选 + 搜索，向上展开 ──
const mentionSelectRef = ref<HTMLElement | null>(null)
const mentionSearchRef = ref<HTMLInputElement | null>(null)
const mentionPickerOpen = ref(false)
const mentionKeyword = ref('')
const mentions = ref<MentionOption[]>([])
const memberPool = ref<MentionOption[]>([])
const memberPoolLoading = ref(false)

const selectedIds = computed(() => new Set(mentions.value.map((m) => m.user_id)))

let memberSearchSeq = 0
let memberSearchTimer: number | null = null

const runMemberSearch = async (keyword: string) => {
  if (!props.searchMembers) return
  const seq = ++memberSearchSeq
  memberPoolLoading.value = true
  const results = await props.searchMembers(keyword)
  if (seq !== memberSearchSeq) return
  memberPool.value = results
  memberPoolLoading.value = false
}

const scheduleMemberSearch = (keyword: string, delay = 0) => {
  if (memberSearchTimer !== null) window.clearTimeout(memberSearchTimer)
  memberSearchTimer = window.setTimeout(() => {
    memberSearchTimer = null
    void runMemberSearch(keyword.trim())
  }, delay)
}

const toggleMentionPicker = async () => {
  if (!isPreInput.value) return
  if (mentionPickerOpen.value) {
    mentionPickerOpen.value = false
    return
  }
  mentionPickerOpen.value = true
  mentionKeyword.value = ''
  scheduleMemberSearch('')
  await nextTick()
  mentionSearchRef.value?.focus()
}

const toggleMention = (option: MentionOption) => {
  if (selectedIds.value.has(option.user_id)) {
    mentions.value = mentions.value.filter((m) => m.user_id !== option.user_id)
  } else {
    mentions.value = [...mentions.value, option]
  }
}

const removeMention = (userId: string) => {
  mentions.value = mentions.value.filter((m) => m.user_id !== userId)
}

const handleClickOutside = (event: MouseEvent) => {
  if (mentionSelectRef.value && !mentionSelectRef.value.contains(event.target as Node)) {
    mentionPickerOpen.value = false
  }
}

onMounted(() => {
  window.addEventListener('click', handleClickOutside)
})
onBeforeUnmount(() => {
  window.removeEventListener('click', handleClickOutside)
  if (memberSearchTimer !== null) window.clearTimeout(memberSearchTimer)
})

watch(mentionKeyword, (keyword) => {
  if (!mentionPickerOpen.value) return
  scheduleMemberSearch(keyword, 250)
})

// 离开协作模式时收起弹层
watch(() => props.preInputMode, (active) => {
  if (!active) mentionPickerOpen.value = false
})

// 展开动画结束后放开 overflow，避免提及/下拉面板被动画容器裁切
const controlsSettled = ref(false)
let settleTimer: number | null = null
watch(isPreInput, (active) => {
  if (settleTimer !== null) {
    window.clearTimeout(settleTimer)
    settleTimer = null
  }
  if (active) {
    settleTimer = window.setTimeout(() => {
      controlsSettled.value = true
    }, 360)
  } else {
    controlsSettled.value = false
  }
})
onBeforeUnmount(() => {
  if (settleTimer !== null) window.clearTimeout(settleTimer)
})

const buildPreInputPayload = () => ({
  main_text: props.modelValue.trim(),
  mentioned_user_ids: mentions.value.map((m) => m.user_id),
  edit_permission: editPermission.value,
  wait_seconds: waitSeconds.value,
})

const resetPreInputForm = () => {
  mentions.value = []
  mentionKeyword.value = ''
  mentionPickerOpen.value = false
  editPermission.value = 'NONE'
  waitSeconds.value = 180
}

defineExpose({ resetPreInputForm })
</script>

<template>
  <div class="chat-execution-row" :class="{ 'is-running': props.running }">
    <div class="input-card" :class="{ 'is-disabled': props.disabled, 'is-running': props.running, 'is-preinput': isPreInput }">
      <!-- 文本域 -->
      <textarea
        ref="textareaRef"
        :value="props.modelValue"
        class="card-textarea"
        rows="1"
        :placeholder="props.placeholder"
        :disabled="props.disabled"
        @input="onTextareaInput"
        @keydown="handleKeydown"
      ></textarea>

      <!-- 协作模式：已选成员 chips -->
      <div v-if="isPreInput && mentions.length > 0" class="mention-chips-row">
        <span v-for="m in mentions" :key="m.user_id" class="mention-chip">
          <UserAvatar
            :display-name="m.display_name"
            :user-id="m.user_id"
            :avatar-svg="m.avatar_svg"
            :avatar-url="m.avatar_url"
            size="xs"
          />
          <span class="chip-name">{{ m.display_name }}</span>
          <button type="button" class="chip-remove" @click="removeMention(m.user_id)">
            <X class="w-2 h-2" />
          </button>
        </span>
      </div>

      <!-- 工具栏 -->
      <div class="card-toolbar">
        <button
          type="button"
          class="tool-toggle"
          :class="{ 'is-active': isPreInput }"
          :disabled="props.canStartPreInput === false || props.disabled"
          :title="t('preInput.toggle_title')"
          @click="togglePreInputMode"
        >
          <span class="tool-toggle-label">{{ $t('preInput.toggle_label') }}</span>
        </button>

        <!-- 协作控件：宽度/透明度丝滑展开；动画结束后放开 overflow 让弹层可点 -->
        <div class="preinput-controls" :class="{ 'is-open': isPreInput, 'is-settled': controlsSettled }">
          <div class="preinput-controls-inner">
            <div ref="mentionSelectRef" class="mention-select">
              <button type="button" class="tool-btn" @click="toggleMentionPicker">
                <span class="tool-btn-label">{{ $t('preInput.mention_field_label') }}</span>
                <span v-if="mentions.length > 0" class="tool-btn-count">{{ mentions.length }}</span>
              </button>

              <div v-if="mentionPickerOpen" class="mention-dropdown">
                <div class="mention-search">
                  <Search class="w-2.5 h-2.5" />
                  <input
                    ref="mentionSearchRef"
                    v-model="mentionKeyword"
                    type="text"
                    :placeholder="$t('preInput.mention_search_placeholder')"
                  >
                </div>
                <div class="mention-list">
                  <div v-if="memberPoolLoading" class="mention-hint">{{ $t('common.loading') }}</div>
                  <div v-else-if="memberPool.length === 0" class="mention-hint">{{ $t('preInput.mention_no_results') }}</div>
                  <button
                    v-for="member in memberPool"
                    v-else
                    :key="member.user_id"
                    type="button"
                    class="mention-option"
                    :class="{ 'is-selected': selectedIds.has(member.user_id) }"
                    @click="toggleMention(member)"
                  >
                    <UserAvatar
                      :display-name="member.display_name"
                      :user-id="member.user_id"
                      :avatar-svg="member.avatar_svg"
                      :avatar-url="member.avatar_url"
                      size="xs"
                    />
                    <span class="mention-name">{{ member.display_name }}</span>
                    <ShieldCheck v-if="member.is_expert" class="w-2 h-2 mention-expert" />
                    <Check v-if="selectedIds.has(member.user_id)" class="w-2 h-2 mention-check" />
                  </button>
                </div>
              </div>
            </div>

            <BaseSelect
              v-model="editPermission"
              :options="permissionOptions"
              size="sm"
              drop-up
              class="tool-select"
            />
            <BaseSelect
              v-model="waitSeconds"
              :options="durationOptions"
              size="sm"
              drop-up
              class="tool-select tool-select--narrow"
            />
          </div>
        </div>

        <div class="toolbar-spacer"></div>

        <!-- 主按钮：运行中切换为停止（替换发送位置，带过渡动效） -->
        <Transition name="action-swap" mode="out-in">
          <button
            v-if="props.running"
            key="stop"
            type="button"
            class="stop-btn"
            :class="{ 'is-interrupting': props.interrupting }"
            :disabled="!props.canInterrupt || props.interrupting"
            :title="props.interruptTitle"
            @click="emit('interrupt')"
          >
            <Loader2 v-if="props.interrupting" class="w-3.5 h-3.5 spin" />
            <Square v-else class="w-3 h-3 stop-icon" />
          </button>
          <button
            v-else
            key="send"
            type="button"
            class="send-btn"
            :class="{ 'is-preinput': isPreInput }"
            :disabled="!canSend"
            :title="isPreInput ? $t('preInput.start_button') : props.sendTitle"
            @click="handleSendClick"
          >
            <Send class="w-4 h-4" />
          </button>
        </Transition>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-execution-row {
  margin: var(--space-4) var(--space-6);
  display: flex;
  align-items: flex-end;
  gap: 10px;
  flex-shrink: 0;
}

/* ── 统一输入卡：上文本域 + 下工具栏 ── */
.input-card {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--color-surface-white);
  border: 1px solid #E2E8F0;
  border-radius: 16px;
  padding: 6px 8px 6px 14px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
  /* 建立层叠上下文：保证内部向上弹出的面板盖住上方消息区 */
  position: relative;
  z-index: 30;
}

.input-card:focus-within {
  border-color: var(--color-primary-500, #0EA5E9);
  box-shadow: 0 0 0 3px var(--color-primary-100, #E0F2FE);
}

.input-card.is-preinput {
  border-color: var(--color-primary-100, #E0F2FE);
}

.input-card.is-disabled {
  opacity: 0.65;
}

.input-card.is-running {
  box-shadow: 0 8px 22px rgba(14, 165, 233, 0.12);
}

.card-textarea {
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  font-size: 0.95rem;
  font-family: var(--font-body);
  line-height: 1.6;
  color: var(--color-text-body);
  padding: 8px 0 6px;
  resize: none;
  overflow-y: auto;
  min-height: 36px;
  max-height: 160px;
  box-sizing: border-box;
}

.card-textarea::placeholder {
  color: #94A3B8;
}

/* ── 已选成员 chips ── */
.mention-chips-row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  padding: 0 0 6px;
}

.mention-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 4px 2px 3px;
  border-radius: var(--radius-full, 999px);
  background: var(--color-primary-50, #F0F9FF);
  border: 1px solid var(--color-primary-100, #E0F2FE);
  color: var(--color-primary-700, #0369A1);
  font-size: 0.7rem;
  font-weight: 500;
}

.chip-name {
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chip-remove {
  border: none;
  background: transparent;
  color: var(--color-primary-600, #0284C7);
  cursor: pointer;
  padding: 2px;
  border-radius: var(--radius-full, 999px);
  display: inline-flex;
  transition: background var(--transition-fast);
}

.chip-remove:hover {
  background: var(--color-primary-100, #E0F2FE);
}

/* ── 工具栏 ── */
.card-toolbar {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  flex-wrap: nowrap;
}

.toolbar-spacer {
  flex: 1;
  min-width: 4px;
}

.tool-toggle,
.tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 10px;
  border-radius: var(--radius-md, 8px);
  border: 1px solid transparent;
  background: transparent;
  color: var(--color-text-muted, #64748B);
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  flex: 0 0 auto;
  transition: all var(--transition-fast);
}

/* 协作模式切换：实体按钮 + 状态圆点，选中态蓝底白字 */
.tool-toggle {
  border-color: rgba(226, 232, 240, 0.8);
  background: var(--color-surface-layer, rgba(255, 255, 255, 0.7));
  color: var(--color-text-body, #334155);
  font-weight: 600;
}

.tool-toggle:hover:not(:disabled) {
  border-color: #BAE6FD;
  color: var(--color-primary-600, #0284C7);
  background: var(--color-primary-50, #F0F9FF);
}

.tool-toggle.is-active {
  background: var(--color-primary-500, #0EA5E9);
  border-color: var(--color-primary-500, #0EA5E9);
  color: #fff;
}

.tool-toggle.is-active:hover:not(:disabled) {
  background: var(--color-primary-600, #0284C7);
  border-color: var(--color-primary-600, #0284C7);
  color: #fff;
}

/* 提及成员：带边框的实体按钮，与 BaseSelect 触发器同语言 */
.tool-btn {
  border-color: rgba(226, 232, 240, 0.8);
  background: var(--color-surface-layer, rgba(255, 255, 255, 0.7));
  color: var(--color-text-body, #334155);
}

.tool-btn:hover:not(:disabled) {
  border-color: #BAE6FD;
  color: var(--color-primary-600, #0284C7);
  background: var(--color-primary-50, #F0F9FF);
}

.tool-toggle:disabled,
.tool-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.tool-btn-count {
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: var(--radius-full, 999px);
  background: var(--color-primary-100, #E0F2FE);
  color: var(--color-primary-700, #0369A1);
  font-size: 0.62rem;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

/* ── 协作控件：丝滑展开 ── */
.preinput-controls {
  flex: 0 1 auto;
  min-width: 0;
  max-width: 0;
  opacity: 0;
  transform: translateX(-10px);
  overflow: hidden;
  transition: max-width 0.32s cubic-bezier(0.4, 0, 0.2, 1),
    opacity 0.24s ease,
    transform 0.32s cubic-bezier(0.4, 0, 0.2, 1);
  pointer-events: none;
}

.preinput-controls.is-open {
  max-width: 560px;
  opacity: 1;
  transform: none;
  pointer-events: auto;
}

/* 展开动画结束后放开裁切，提及面板 / BaseSelect 弹层才能向上露出可交互 */
.preinput-controls.is-settled {
  overflow: visible;
}

.preinput-controls-inner {
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.tool-select {
  width: 132px;
  flex: 0 0 auto;
}

.tool-select--narrow {
  width: 96px;
}

/* ── 提及成员下拉（向上展开） ── */
.mention-select {
  position: relative;
  display: inline-flex;
}

.mention-dropdown {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 0;
  width: 250px;
  background: var(--color-surface-white, #fff);
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-md, 8px);
  box-shadow: var(--shadow-lg);
  z-index: 80;
  overflow: hidden;
}

.mention-search {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 10px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
  color: var(--color-text-muted, #64748B);
}

.mention-search input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  font-size: 0.78rem;
  font-family: var(--font-body);
  color: var(--color-text-body, #334155);
}

.mention-search input::placeholder {
  color: #94A3B8;
}

.mention-list {
  max-height: 200px;
  overflow-y: auto;
  padding: 4px;
}

.mention-hint {
  padding: 10px;
  color: var(--color-text-muted, #64748B);
  font-size: 0.72rem;
}

.mention-option {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  border: none;
  background: transparent;
  padding: 6px 8px;
  border-radius: var(--radius-sm, 6px);
  cursor: pointer;
  text-align: left;
  transition: background var(--transition-fast);
}

.mention-option:hover,
.mention-option.is-selected {
  background: var(--color-primary-50, #F0F9FF);
}

.mention-name {
  flex: 1;
  min-width: 0;
  font-size: 0.78rem;
  color: var(--color-text-body, #334155);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mention-expert {
  color: #059669;
}

.mention-check {
  color: var(--color-primary-600, #0284C7);
  flex: 0 0 auto;
}

/* ── 发送按钮：圆形 ── */
.send-btn {
  border: none;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--color-primary-500, #0EA5E9);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex: 0 0 auto;
  transition: background var(--transition-fast), opacity var(--transition-fast);
}

.send-btn:hover:not(:disabled) {
  background: var(--color-primary-600, #0284C7);
}

.send-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.send-btn.is-preinput {
  background: var(--color-primary-600, #0284C7);
}

/* ── 停止按钮：运行中替换发送位置，呼吸动效提示可中断 ── */
.stop-btn {
  position: relative;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: #fff;
  color: #B91C1C;
  border: 1px solid #FECACA;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex: 0 0 auto;
  transition: background var(--transition-fast), color var(--transition-fast), transform var(--transition-fast);
  animation: stop-breathe 1.8s ease-in-out infinite;
}

.stop-btn:hover:not(:disabled) {
  background: #FEF2F2;
  transform: scale(1.06);
}

.stop-btn:disabled {
  cursor: not-allowed;
  opacity: 0.75;
  animation: none;
}

.stop-btn.is-interrupting {
  color: #DC2626;
  animation: none;
}

.stop-icon {
  fill: currentColor;
}

@keyframes stop-breathe {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(185, 28, 28, 0.28);
  }
  50% {
    box-shadow: 0 0 0 6px rgba(185, 28, 28, 0);
  }
}

/* ── 发送 ↔ 停止 切换动效 ── */
.action-swap-enter-active,
.action-swap-leave-active {
  transition: transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.18s ease;
}

.action-swap-enter-from {
  transform: scale(0.5) rotate(-90deg);
  opacity: 0;
}

.action-swap-leave-to {
  transform: scale(0.5) rotate(90deg);
  opacity: 0;
}

.spin {
  animation: input-spin 1s linear infinite;
}

@keyframes input-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
