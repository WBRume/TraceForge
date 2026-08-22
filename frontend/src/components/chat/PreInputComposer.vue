<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { X, Check, Search, ShieldCheck } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import UserAvatar from '@/components/user/UserAvatar.vue'

const props = defineProps<{
  vm: any
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const { t } = useI18n()

type MentionOption = {
  user_id: string
  display_name: string
  avatar_url: string | null
  avatar_svg: string | null
  is_expert: boolean
}

const mainText = ref('')
const mentions = ref<MentionOption[]>([])
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

// ── 提及成员：多选 + 搜索下拉 ──
const mentionSelectRef = ref<HTMLElement | null>(null)
const mentionSearchRef = ref<HTMLInputElement | null>(null)
const mentionPickerOpen = ref(false)
const mentionKeyword = ref('')
const memberPool = ref<MentionOption[]>([])
const memberPoolLoading = ref(false)

const selectedIds = computed(() => new Set(mentions.value.map((m) => m.user_id)))
// 成员列表由服务端按关键词检索返回（本地不再二次过滤，避免“看似没搜索”）
const filteredMembers = computed(() => memberPool.value)

let memberSearchSeq = 0
let memberSearchTimer: number | null = null

const runMemberSearch = async (keyword: string) => {
  const seq = ++memberSearchSeq
  memberPoolLoading.value = true
  const results = await props.vm.searchPreInputMembers(keyword)
  // 丢弃过期响应，避免旧结果覆盖新关键词
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

const openMentionPicker = async () => {
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

// 键入即搜：防抖 250ms 自动请求服务端
watch(mentionKeyword, (keyword) => {
  if (!mentionPickerOpen.value) return
  scheduleMemberSearch(keyword, 250)
})

const canSubmit = computed(() => Boolean(mainText.value.trim()))

const submit = () => {
  if (!canSubmit.value) return
  const ok = props.vm.startPreInput({
    main_text: mainText.value.trim(),
    mentioned_user_ids: mentions.value.map((m) => m.user_id),
    edit_permission: editPermission.value,
    wait_seconds: waitSeconds.value,
  })
  if (ok) {
    ElMessage.success(t('preInput.started_toast'))
    emit('close')
  }
}

watch(() => props.vm?.activePreInput, (value) => {
  if (value) emit('close')
})
</script>

<template>
  <div class="preinput-composer">
    <div class="composer-header">
      <span class="composer-title">{{ $t('preInput.composer_title') }}</span>
      <button type="button" class="icon-btn" :title="$t('common.close')" @click="emit('close')">
        <X class="w-3 h-3" />
      </button>
    </div>

    <div class="composer-body">
      <textarea
        v-model="mainText"
        class="composer-textarea"
        rows="4"
        :placeholder="$t('preInput.main_text_placeholder')"
      ></textarea>

      <!-- 提及成员：多选框 -->
      <div ref="mentionSelectRef" class="mention-select">
        <span class="option-label">{{ $t('preInput.mention_field_label') }}</span>
        <div class="mention-trigger" @click="openMentionPicker">
          <span v-if="mentions.length === 0" class="mention-placeholder">
            {{ $t('preInput.mention_field_placeholder') }}
          </span>
          <template v-else>
            <span v-for="m in mentions" :key="m.user_id" class="mention-chip">
              <UserAvatar
                :display-name="m.display_name"
                :user-id="m.user_id"
                :avatar-svg="m.avatar_svg"
                :avatar-url="m.avatar_url"
                size="xs"
              />
              <span class="chip-name">{{ m.display_name }}</span>
              <button type="button" class="chip-remove" @click.stop="removeMention(m.user_id)">
                <X class="w-2 h-2" />
              </button>
            </span>
          </template>
          <span class="mention-count" v-if="mentions.length > 0">{{ mentions.length }}</span>
        </div>

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
            <div v-else-if="filteredMembers.length === 0" class="mention-hint">{{ $t('preInput.mention_no_results') }}</div>
            <button
              v-for="member in filteredMembers"
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

      <div class="composer-options">
        <div class="option-field">
          <span class="option-label">{{ $t('preInput.edit_permission_label') }}</span>
          <BaseSelect
            v-model="editPermission"
            :options="permissionOptions"
            size="sm"
            drop-up
            class="option-select"
          />
        </div>
        <div class="option-field">
          <span class="option-label">{{ $t('preInput.wait_duration_label') }}</span>
          <BaseSelect
            v-model="waitSeconds"
            :options="durationOptions"
            size="sm"
            drop-up
            class="option-select"
          />
        </div>
      </div>
    </div>

    <div class="composer-footer">
      <span class="footer-hint">{{ $t('preInput.composer_hint') }}</span>
      <div class="footer-actions">
        <button type="button" class="btn-secondary" @click="emit('close')">
          {{ $t('common.cancel') }}
        </button>
        <button type="button" class="btn-primary-fill" :disabled="!canSubmit" @click="submit">
          {{ $t('preInput.start_button') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.preinput-composer {
  margin: var(--space-4) var(--space-6) 0;
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-lg);
  background: var(--color-surface-white);
  box-shadow: var(--shadow-sm);
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
}

.composer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
}

.composer-title {
  font-weight: 600;
  font-size: 0.875rem;
  color: var(--color-text-title);
}

.icon-btn {
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 4px;
  border-radius: var(--radius-sm);
  display: inline-flex;
  transition: all var(--transition-fast);
}

.icon-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}

.composer-body {
  padding: var(--space-3) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.composer-textarea {
  width: 100%;
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-md);
  background: var(--color-surface-white);
  padding: 10px 12px;
  font-size: 0.875rem;
  font-family: var(--font-body);
  line-height: 1.6;
  color: var(--color-text-body);
  resize: vertical;
  outline: none;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
  box-sizing: border-box;
}

.composer-textarea:focus {
  border-color: var(--color-primary-500);
  box-shadow: 0 0 0 3px var(--color-primary-100);
}

.composer-textarea::placeholder {
  color: #94A3B8;
}

.option-label {
  font-size: 0.75rem;
  color: var(--color-text-muted);
  font-weight: 500;
}

/* 提及成员多选 */
.mention-select {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.mention-trigger {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 42px;
  padding: 5px 10px;
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-md);
  background: var(--color-surface-white);
  cursor: pointer;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.mention-trigger:hover {
  border-color: #BAE6FD;
}

.mention-placeholder {
  color: #94A3B8;
  font-size: 0.8125rem;
}

.mention-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 4px 2px 3px;
  border-radius: var(--radius-full);
  background: var(--color-primary-50);
  border: 1px solid var(--color-primary-100);
  color: var(--color-primary-700);
  font-size: 0.72rem;
  font-weight: 500;
}

.chip-name {
  max-width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chip-remove {
  border: none;
  background: transparent;
  color: var(--color-primary-600);
  cursor: pointer;
  padding: 1px;
  border-radius: var(--radius-full);
  display: inline-flex;
  transition: background var(--transition-fast);
}

.chip-remove:hover {
  background: var(--color-primary-100);
}

.mention-count {
  margin-left: auto;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: var(--radius-full);
  background: var(--color-primary-100);
  color: var(--color-primary-700);
  font-size: 0.66rem;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.mention-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  background: var(--color-surface-white);
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  z-index: 60;
  overflow: hidden;
}

.mention-search {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
  color: var(--color-text-muted);
}

.mention-search input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  font-size: 0.8rem;
  font-family: var(--font-body);
  color: var(--color-text-body);
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
  color: var(--color-text-muted);
  font-size: 0.75rem;
}

.mention-option {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  border: none;
  background: transparent;
  padding: 7px 8px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  text-align: left;
  transition: background var(--transition-fast);
}

.mention-option:hover {
  background: var(--color-primary-50);
}

.mention-option.is-selected {
  background: var(--color-primary-50);
}

.mention-name {
  flex: 1;
  min-width: 0;
  font-size: 0.8rem;
  color: var(--color-text-body);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mention-expert {
  color: #059669;
}

.mention-check {
  color: var(--color-primary-600);
  flex: 0 0 auto;
}

.composer-options {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-6);
}

.option-field {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.option-select {
  width: 150px;
}

.composer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid rgba(0, 0, 0, 0.05);
}

.footer-hint {
  font-size: 0.72rem;
  color: var(--color-text-muted);
}

.footer-actions {
  display: flex;
  gap: var(--space-2);
}

.btn-secondary {
  border: 1px solid #E2E8F0;
  background: var(--color-surface-white);
  color: #475569;
  border-radius: var(--radius-md);
  padding: 6px 14px;
  font-size: 0.78rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-secondary:hover {
  background: #F8FAFC;
}

.btn-primary-fill {
  border: none;
  background: var(--color-primary-500);
  color: #fff;
  border-radius: var(--radius-md);
  padding: 6px 16px;
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.btn-primary-fill:hover:not(:disabled) {
  background: var(--color-primary-600);
}

.btn-primary-fill:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
</style>
