<script setup lang="ts">
import { computed } from 'vue'
import DeleteActionButton from '@/components/DeleteActionButton.vue'
import { formatTime } from '@/utils/chatFormatters'
import { Star } from 'lucide-vue-next'

interface ChatTaskListItemData {
  id: string
  name?: string | null
  status?: string | null
  task_type?: string | null
  creator_name?: string | null
  created_at?: string | null
  is_following?: boolean
}

const props = defineProps<{
  task: ChatTaskListItemData
  active: boolean
  canDelete: boolean
}>()

const emit = defineEmits<{
  select: [task: ChatTaskListItemData]
  delete: [task: ChatTaskListItemData]
  toggleFollow: [task: ChatTaskListItemData]
}>()

const normalizedStatus = computed(() => String(props.task.status || '').toLowerCase())
const isDiagnosis = computed(() => props.task.task_type === 'DIAGNOSIS')
const hasMetadata = computed(() => Boolean(props.task.creator_name || props.task.created_at))

const selectTask = () => emit('select', props.task)
const deleteTask = () => emit('delete', props.task)
const toggleFollow = () => emit('toggleFollow', props.task)
</script>

<template>
  <article class="task-item" :class="{ active }">
    <button
      class="task-select"
      type="button"
      :aria-current="active ? 'page' : undefined"
      @click="selectTask"
    >
      <span class="task-name" :title="task.name || ''">{{ task.name }}</span>

      <span class="task-state-row">
        <span class="task-state-group">
          <span
            class="task-type-tag"
            :class="isDiagnosis ? 'is-diagnosis' : 'is-development'"
          >
            {{ isDiagnosis ? $t('task_types.diagnosis') : $t('task_types.development') }}
          </span>
          <span class="task-status">
            <span class="status-dot" :class="normalizedStatus"></span>
            {{ task.status }}
          </span>
        </span>
      </span>

      <span v-if="hasMetadata" class="task-meta">
        <span v-if="task.creator_name" class="task-creator">{{ task.creator_name }}</span>
        <span v-if="task.creator_name && task.created_at" class="task-meta-separator">·</span>
        <time v-if="task.created_at" class="task-date" :datetime="task.created_at">
          {{ formatTime(task.created_at) }}
        </time>
      </span>
    </button>

    <button
      class="follow-btn"
      :class="{ active: task.is_following }"
      type="button"
      :title="$t(task.is_following ? 'chat.task_unfollow_messages' : 'chat.task_follow_messages')"
      :aria-label="$t(task.is_following ? 'chat.task_unfollow_messages' : 'chat.task_follow_messages')"
      :aria-pressed="Boolean(task.is_following)"
      @click.stop="toggleFollow"
    >
      <Star class="follow-icon" :fill="task.is_following ? 'currentColor' : 'none'" />
    </button>

    <DeleteActionButton
      mode="icon"
      class="delete-btn"
      :title="$t('common.delete')"
      :disabled="!canDelete"
      @click="deleteTask"
    />
  </article>
</template>

<style scoped>
.task-item {
  position: relative;
  margin-bottom: var(--space-1);
}

.task-select {
  display: block;
  width: 100%;
  padding: 10px 76px 10px 12px;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  color: inherit;
  background: transparent;
  cursor: pointer;
  outline: none;
  text-align: left;
  transition:
    background-color var(--transition-fast),
    border-color var(--transition-fast),
    box-shadow var(--transition-fast);
}

.task-item:hover .task-select,
.task-select:focus-visible {
  background-color: var(--color-primary-50);
}

.task-select:focus-visible {
  border-color: rgba(37, 99, 235, 0.35);
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.1);
}

.task-item.active .task-select,
.task-item.active:hover .task-select {
  background-color: var(--color-surface-white);
  border-color: rgba(14, 165, 233, 0.25);
  box-shadow:
    0 1px 3px 0 rgba(14, 165, 233, 0.06),
    0 4px 16px -2px rgba(14, 165, 233, 0.12),
    0 2px 4px -1px rgba(15, 23, 42, 0.04);
}

.task-name {
  display: -webkit-box;
  min-width: 0;
  overflow: hidden;
  color: var(--color-text-body);
  font-size: 0.875rem;
  font-weight: 600;
  line-height: 1.4;
  overflow-wrap: anywhere;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.task-item.active .task-name {
  color: var(--color-text-title);
  font-weight: 700;
}

.task-state-row {
  display: flex;
  align-items: center;
  min-width: 0;
  margin-top: 7px;
}

.task-state-group {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.task-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  overflow: hidden;
  color: var(--color-text-muted);
  font-size: 0.7rem;
  font-weight: 500;
  line-height: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-type-tag {
  flex-shrink: 0;
  padding: 3px 7px;
  border-radius: 999px;
  font-size: 0.64rem;
  font-weight: 600;
  letter-spacing: 0.01em;
  line-height: 1;
  white-space: nowrap;
}

.task-type-tag.is-development {
  border: 1px solid rgba(14, 165, 233, 0.25);
  color: #0369a1;
  background: #e0f2fe;
}

.task-type-tag.is-diagnosis {
  border: 1px solid rgba(245, 158, 11, 0.3);
  color: #92400e;
  background: #fef3c7;
}

.task-item.active .task-type-tag.is-development {
  border-color: rgba(14, 165, 233, 0.35);
  background: #dbeafe;
}

.task-item.active .task-type-tag.is-diagnosis {
  border-color: rgba(245, 158, 11, 0.45);
  background: #fde68a;
}

.status-dot {
  width: 6px;
  height: 6px;
  flex: 0 0 auto;
  border-radius: 50%;
  background-color: var(--color-text-muted);
}

.status-dot.coding,
.status-dot.running {
  background-color: var(--color-primary-500);
}

.status-dot.pending {
  background-color: var(--color-accent-amber);
}

.status-dot.done {
  background-color: var(--color-accent-emerald);
}

.status-dot.failed {
  background-color: var(--color-accent-rose);
}

.status-dot.interrupted {
  background-color: #f59e0b;
}

.task-meta {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  margin-top: 6px;
  overflow: hidden;
  color: var(--color-text-muted);
  font-size: 0.68rem;
  line-height: 1.2;
  opacity: 0.88;
}

.task-creator,
.task-date {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-creator {
  flex: 0 1 auto;
  max-width: 42%;
  color: var(--color-primary-600);
  font-weight: 600;
}

.task-date {
  flex: 1 1 auto;
}

.task-meta-separator {
  flex: 0 0 auto;
  opacity: 0.55;
}

.follow-btn,
.delete-btn.delete-action-btn {
  position: absolute;
  top: 50%;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 6px;
  border: 0;
  border-radius: 8px;
  color: #94a3b8;
  background: transparent;
  cursor: pointer;
  opacity: 0.6;
  translate: 0 -50%;
  transition: opacity 0.2s, color 0.2s, background-color 0.2s, box-shadow 0.2s, transform 0.2s;
}

.follow-btn {
  right: 38px;
}

.delete-btn.delete-action-btn {
  right: 10px;
}

.follow-icon {
  width: 0.85rem;
  height: 0.85rem;
}

/* 选中或悬停任务项时：按钮透明度提升并加深背景颜色 */
.task-item:hover .follow-btn,
.task-item:hover .delete-btn.delete-action-btn,
.task-item:focus-within .follow-btn,
.task-item:focus-within .delete-btn.delete-action-btn,
.task-item.active .follow-btn,
.task-item.active .delete-btn.delete-action-btn {
  opacity: 1;
  background: #f1f5f9;
}

/* 按钮自身 hover / active 时的微交互高亮 */
.follow-btn:hover,
.task-item:hover .follow-btn:hover,
.task-item:focus-within .follow-btn:hover,
.task-item.active .follow-btn:hover {
  color: #94a3b8;
  background: #fef3c7;
  box-shadow: 0 2px 8px rgba(217, 119, 6, 0.25);
  transform: translateY(-1px);
}

.follow-btn.active {
  color: #d97706;
  background: #fef3c7;
  opacity: 1;
}

.delete-btn.delete-action-btn:hover:not(:disabled) {
  color: #fff;
  background: #ef4444;
  box-shadow: 0 2px 8px rgba(239, 68, 68, 0.25);
}
</style>
