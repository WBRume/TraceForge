<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, ChevronDown, Copy, Inbox, Loader2, Pencil, X } from 'lucide-vue-next'
import type { ShareSuggestion } from '@/composables/useShareSuggestions'

/**
 * 发起人「收到的输入」面板：入口（带待处理数徽标）+ 列表（来源署名、
 * 时间、原文/编辑内容）+ 操作（编辑 / 复制 / 采纳 / 忽略）。
 * 采纳时若输入框已有草稿，由父级弹追加/替换选择。
 */
const props = defineProps<{
  suggestions: ShareSuggestion[]
  pendingCount: number
  loading: boolean
  actingIds: Set<string>
  hasDraft: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'edit', suggestion: ShareSuggestion, editedContent: string): void
  (e: 'copy', suggestion: ShareSuggestion): void
  (e: 'adopt', suggestion: ShareSuggestion): void
  (e: 'dismiss', suggestion: ShareSuggestion): void
}>()

const { t } = useI18n()

const editingId = ref<string | null>(null)
const editDraft = ref('')

const pendingSuggestions = computed(() =>
  props.suggestions.filter((item) => item.status === 'PENDING')
)

const formatTime = (value: string): string => new Date(value).toLocaleString()

const sourceLabel = (item: ShareSuggestion): string =>
  item.display_name?.trim() || t('share.anonymous_visitor')

const isEditing = (item: ShareSuggestion): boolean => editingId.value === item.id

const startEdit = (item: ShareSuggestion) => {
  if (props.actingIds.has(item.id)) return
  editingId.value = item.id
  editDraft.value = item.edited_content || item.original_content
}

const cancelEdit = () => {
  editingId.value = null
  editDraft.value = ''
}

const confirmEdit = (item: ShareSuggestion) => {
  const text = editDraft.value.trim()
  if (!text) return
  emit('edit', item, text)
  cancelEdit()
}
</script>

<template>
  <div class="suggestion-panel glass-panel">
    <header class="suggestion-panel-header">
      <div class="suggestion-panel-title">
        <Inbox class="w-4 h-4" />
        <span>{{ $t('share.suggestions_title') }}</span>
        <span v-if="pendingCount > 0" class="suggestion-count-badge">{{ pendingCount }}</span>
      </div>
      <button type="button" class="suggestion-close-btn" :title="$t('common.close')" @click="emit('close')">
        <ChevronDown class="w-4 h-4" />
      </button>
    </header>

    <div class="suggestion-panel-body">
      <div v-if="loading && suggestions.length === 0" class="suggestion-state">
        <Loader2 class="w-4 h-4 spin" />
        <span>{{ $t('common.loading') }}</span>
      </div>
      <p v-else-if="suggestions.length === 0" class="suggestion-state suggestion-empty">
        {{ $t('share.suggestions_empty') }}
      </p>

      <ul v-else class="suggestion-list">
        <li
          v-for="item in pendingSuggestions"
          :key="item.id"
          class="suggestion-item"
          :class="{ 'is-adopted': item.status === 'ADOPTED' }"
        >
          <div class="suggestion-item-head">
            <span class="suggestion-source">{{ sourceLabel(item) }}</span>
            <span class="suggestion-time">{{ formatTime(item.created_at) }}</span>
          </div>

          <template v-if="isEditing(item)">
            <textarea
              v-model="editDraft"
              class="suggestion-edit-input"
              rows="4"
              maxlength="20000"
            ></textarea>
            <div class="suggestion-edit-actions">
              <button type="button" class="btn-micro" @click="cancelEdit">
                {{ $t('common.cancel') }}
              </button>
              <button
                type="button"
                class="btn-micro primary"
                :disabled="!editDraft.trim()"
                @click="confirmEdit(item)"
              >
                <Check class="w-3 h-3" />
                {{ $t('common.confirm') }}
              </button>
            </div>
          </template>
          <template v-else>
            <div v-if="item.edited_content" class="suggestion-original">
              <span class="suggestion-original-label">{{ $t('share.suggestion_original') }}</span>
              <span class="suggestion-original-text">{{ item.original_content }}</span>
            </div>
            <p class="suggestion-content">{{ item.edited_content || item.original_content }}</p>
            <div class="suggestion-item-actions">
              <button
                type="button"
                class="btn-micro"
                :disabled="actingIds.has(item.id)"
                @click="startEdit(item)"
              >
                <Pencil class="w-3 h-3" />
                {{ $t('share.action_edit') }}
              </button>
              <button
                type="button"
                class="btn-micro"
                :disabled="actingIds.has(item.id)"
                @click="emit('copy', item)"
              >
                <Copy class="w-3 h-3" />
                {{ $t('share.action_copy') }}
              </button>
              <button
                type="button"
                class="btn-micro primary"
                :disabled="actingIds.has(item.id)"
                @click="emit('adopt', item)"
              >
                <Loader2 v-if="actingIds.has(item.id)" class="w-3 h-3 spin" />
                <Check v-else class="w-3 h-3" />
                {{ hasDraft ? $t('share.action_adopt_replace_choice') : $t('share.action_adopt') }}
              </button>
              <button
                type="button"
                class="btn-micro danger"
                :disabled="actingIds.has(item.id)"
                @click="emit('dismiss', item)"
              >
                <X class="w-3 h-3" />
                {{ $t('share.action_dismiss') }}
              </button>
            </div>
          </template>
        </li>
      </ul>

      <p v-if="pendingCount === 0 && suggestions.length > 0" class="suggestion-all-done">
        {{ $t('share.suggestions_all_done') }}
      </p>
    </div>
  </div>
</template>

<style scoped>
/* 外边距对齐 .preinput-panel（与输入卡同宽同缩进） */
.suggestion-panel {
  margin: var(--space-4, 16px) var(--space-6, 24px) 0;
  border-radius: 12px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.06);
  overflow: hidden;
  flex-shrink: 0;
}

.suggestion-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.65rem 0.9rem;
  border-bottom: 1px solid #f1f5f9;
  background: #f8fafc;
}

.suggestion-panel-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.82rem;
  font-weight: 700;
  color: #1e293b;
}

.suggestion-panel-title svg {
  color: #0ea5e9;
}

.suggestion-count-badge {
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 999px;
  background: #ef4444;
  color: #ffffff;
  font-size: 0.7rem;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.suggestion-close-btn {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  border: none;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s ease;
}

.suggestion-close-btn:hover {
  background: #e2e8f0;
}

.suggestion-panel-body {
  max-height: 320px;
  overflow-y: auto;
  padding: 0.6rem 0.75rem;
}

.suggestion-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 1.2rem 0;
  color: #94a3b8;
  font-size: 0.78rem;
}

.suggestion-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.suggestion-item {
  border: 1px solid #edf2f7;
  border-radius: 10px;
  padding: 0.6rem 0.75rem;
  background: #ffffff;
}

.suggestion-item.is-adopted {
  opacity: 0.65;
}

.suggestion-item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.4rem;
}

.suggestion-source {
  font-size: 0.76rem;
  font-weight: 700;
  color: #0f172a;
}

.suggestion-time {
  font-size: 0.68rem;
  color: #94a3b8;
}

.suggestion-content {
  margin: 0;
  font-size: 0.78rem;
  color: #334155;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.suggestion-original {
  margin-bottom: 0.4rem;
  padding: 0.35rem 0.55rem;
  background: #f8fafc;
  border-radius: 7px;
  border-left: 2px solid #cbd5e1;
}

.suggestion-original-label {
  display: block;
  font-size: 0.66rem;
  color: #94a3b8;
  font-weight: 600;
  margin-bottom: 0.15rem;
}

.suggestion-original-text {
  font-size: 0.72rem;
  color: #64748b;
  text-decoration: line-through;
  word-break: break-word;
}

/* 自足按钮样式：.btn-micro 定义在 ChatView 的 scoped 样式里，作用域
   到不了子组件，这里按同规格实现（chat-view-modal-buttons.css:185） */
.suggestion-item-actions {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.55rem;
  flex-wrap: wrap;
}

.suggestion-item-actions .btn-micro,
.suggestion-edit-actions .btn-micro {
  background: #ffffff;
  color: #475569;
  border: 1px solid #e2e8f0;
  padding: 4px 10px;
  border-radius: var(--radius-md, 8px);
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: inherit;
  transition: all 0.2s;
}

.suggestion-item-actions .btn-micro:hover:not(:disabled),
.suggestion-edit-actions .btn-micro:hover:not(:disabled) {
  background: var(--color-primary-50, #f0f9ff);
  color: var(--color-primary-600, #0284c7);
  border-color: var(--color-primary-200, #bae6fd);
}

.suggestion-item-actions .btn-micro:disabled,
.suggestion-edit-actions .btn-micro:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* w-3/h-3 工具类同样定义在 ChatView scoped 样式里，这里显式定尺寸 */
.suggestion-item-actions .btn-micro svg,
.suggestion-edit-actions .btn-micro svg {
  width: 12px;
  height: 12px;
  flex-shrink: 0;
}

.suggestion-panel-header svg,
.suggestion-state svg {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

.suggestion-panel-header .spin,
.suggestion-state .spin {
  animation: suggestion-spin 1s linear infinite;
}

.suggestion-item-actions .btn-micro.primary,
.suggestion-edit-actions .btn-micro.primary {
  color: #0284c7;
  border-color: #7dd3fc;
}

.suggestion-item-actions .btn-micro.primary:hover:not(:disabled),
.suggestion-edit-actions .btn-micro.primary:hover:not(:disabled) {
  background: #f0f9ff;
}

.suggestion-item-actions .btn-micro.danger,
.suggestion-edit-actions .btn-micro.danger {
  color: #dc2626;
  border-color: #fecaca;
}

.suggestion-item-actions .btn-micro.danger:hover:not(:disabled),
.suggestion-edit-actions .btn-micro.danger:hover:not(:disabled) {
  background: #fef2f2;
}

.suggestion-edit-input {
  width: 100%;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 0.5rem 0.65rem;
  font-size: 0.78rem;
  font-family: inherit;
  color: #0f172a;
  resize: vertical;
  outline: none;
}

.suggestion-edit-input:focus {
  border-color: #0ea5e9;
}

.suggestion-edit-actions {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  justify-content: flex-end;
  margin-top: 0.4rem;
}

.suggestion-all-done {
  margin: 0;
  text-align: center;
  font-size: 0.74rem;
  color: #94a3b8;
  padding: 0.4rem 0;
}

.spin {
  animation: suggestion-spin 1s linear infinite;
}

@keyframes suggestion-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
