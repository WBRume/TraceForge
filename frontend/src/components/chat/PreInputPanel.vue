<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Check, Circle, Send, X } from 'lucide-vue-next'
import UserAvatar from '@/components/user/UserAvatar.vue'

const props = defineProps<{
  vm: any
}>()

const preInput = computed(() => props.vm?.activePreInput)
const isCreator = computed(() => Boolean(props.vm?.isPreInputCreator))
const canEditShared = computed(() => Boolean(props.vm?.canEditPreInputShared))
const myContribution = computed(() => props.vm?.myPreInputContribution || null)

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
const contributions = computed(() => preInput.value?.contributions || [])
const doneCount = computed(() => mentionees.value.filter((m: any) => m.done).length)

const memberColor = (userId: string) => props.vm?.memberColorFor?.(userId) || '#0284C7'

// ── 主文本编辑 ──
const mainTextEditing = ref(false)
const mainTextDraft = ref('')
const startEditMainText = () => {
  mainTextDraft.value = preInput.value?.main_text || ''
  mainTextEditing.value = true
}
const saveMainText = () => {
  const text = mainTextDraft.value.trim()
  if (!text) return
  props.vm.editPreInputMainText(text)
  mainTextEditing.value = false
}

// ── 我的输入：常驻输入框 ──
const myDraft = ref('')
watch(
  () => myContribution.value?.content,
  (content, prev) => {
    // 服务端内容更新时同步草稿（未编辑中的本地草稿跟随）
    if (myDraft.value === '' || myDraft.value === prev) {
      myDraft.value = content || ''
    }
  },
  { immediate: true },
)
const submitMyInput = () => {
  const text = myDraft.value.trim()
  if (!text) return
  props.vm.submitPreInputContribution(text)
}

// ── 编辑他人输入段 ──
const editingContributionUserId = ref('')
const contributionDraft = ref('')
const startEditContribution = (userId: string, content: string) => {
  editingContributionUserId.value = userId
  contributionDraft.value = content
}
const saveContribution = (userId: string) => {
  const text = contributionDraft.value.trim()
  if (!text) return
  props.vm.editPreInputContributionOf(userId, text)
  editingContributionUserId.value = ''
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

    <!-- 主文本 -->
    <template v-if="!mainTextEditing">
      <div class="main-text-row">
        <div class="main-text-content">{{ preInput.main_text }}</div>
        <button
          v-if="canEditShared"
          type="button"
          class="text-btn"
          @click="startEditMainText"
        >
          {{ $t('common.edit') }}
        </button>
      </div>
    </template>
    <template v-else>
      <textarea v-model="mainTextDraft" class="panel-textarea" rows="3"></textarea>
      <div class="row-actions">
        <button type="button" class="btn-mini-primary" @click="saveMainText">{{ $t('common.save') }}</button>
        <button type="button" class="btn-mini-ghost" @click="mainTextEditing = false">{{ $t('common.cancel') }}</button>
      </div>
    </template>

    <!-- 成员状态：单行紧凑 chips -->
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

    <!-- 成员输入段：极简列表 -->
    <div v-if="contributions.length > 0" class="contributions">
      <div
        v-for="item in contributions"
        :key="item.user_id"
        class="contribution-item"
        :class="{ 'is-editing': editingContributionUserId === item.user_id }"
      >
        <template v-if="editingContributionUserId === item.user_id">
          <div class="contribution-head">
            <UserAvatar
              :display-name="item.display_name"
              :user-id="item.user_id"
              :avatar-svg="item.avatar_svg"
              :avatar-url="item.avatar_url"
              size="xs"
              :accent-color="memberColor(item.user_id)"
            />
            <span class="contribution-author" :style="{ color: memberColor(item.user_id) }">{{ item.display_name }}</span>
          </div>
          <textarea v-model="contributionDraft" class="panel-textarea" rows="2"></textarea>
          <div class="row-actions">
            <button type="button" class="btn-mini-primary" @click="saveContribution(item.user_id)">{{ $t('common.save') }}</button>
            <button type="button" class="btn-mini-ghost" @click="editingContributionUserId = ''">{{ $t('common.cancel') }}</button>
          </div>
        </template>
        <template v-else>
          <div class="contribution-head">
            <UserAvatar
              :display-name="item.display_name"
              :user-id="item.user_id"
              :avatar-svg="item.avatar_svg"
              :avatar-url="item.avatar_url"
              size="xs"
              :accent-color="memberColor(item.user_id)"
            />
            <span class="contribution-author" :style="{ color: memberColor(item.user_id) }">{{ item.display_name }}</span>
            <button
              v-if="vm.canEditPreInputContributionOf(item.user_id)"
              type="button"
              class="text-btn"
              @click="startEditContribution(item.user_id, item.content)"
            >
              {{ $t('common.edit') }}
            </button>
          </div>
          <div class="contribution-content">{{ item.content }}</div>
        </template>
      </div>
    </div>

    <!-- 底部：我的输入（常驻输入框）+ 发起人操作 -->
    <div class="panel-footer">
      <div class="my-input-area">
        <textarea
          v-model="myDraft"
          class="panel-textarea"
          rows="2"
          :placeholder="$t('preInput.my_input_placeholder')"
        ></textarea>
        <div class="row-actions">
          <button
            type="button"
            class="btn-mini-primary"
            :disabled="!myDraft.trim()"
            @click="submitMyInput"
          >
            {{ myContribution ? $t('preInput.update_my_input') : $t('preInput.submit_my_input') }}
          </button>
          <span v-if="myContribution" class="my-input-saved-hint">
            <Check class="w-2 h-2" />
            {{ $t('preInput.my_input_saved') }}
          </span>
        </div>
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

.main-text-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
}

.main-text-content {
  flex: 1;
  min-width: 0;
  font-size: 0.8125rem;
  line-height: 1.6;
  color: var(--color-text-body);
  white-space: pre-wrap;
  word-break: break-word;
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
  transition: color var(--transition-fast);
}

.text-btn:hover {
  color: var(--color-primary-700);
  text-decoration: underline;
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

.contributions {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.contribution-item {
  padding: var(--space-2) var(--space-3);
  background: #F8FAFC;
  border-radius: var(--radius-md);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.contribution-item.is-editing {
  background: var(--color-surface-white);
  border: 1px solid var(--color-primary-100);
}

.contribution-head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.contribution-author {
  font-size: 0.72rem;
  font-weight: 600;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.contribution-content {
  font-size: 0.78rem;
  line-height: 1.55;
  color: var(--color-text-body);
  white-space: pre-wrap;
  word-break: break-word;
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

.panel-textarea::placeholder {
  color: #94A3B8;
}

.row-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: 6px;
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

.my-input-saved-hint {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 0.7rem;
  color: var(--color-accent-emerald, #10B981);
}

.panel-footer {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
  border-top: 1px solid rgba(0, 0, 0, 0.05);
  padding-top: var(--space-3);
}

.my-input-area {
  flex: 1;
  min-width: 220px;
}

.creator-actions {
  display: flex;
  gap: var(--space-2);
}
</style>
