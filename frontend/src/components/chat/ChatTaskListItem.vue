<script setup lang="ts">
import { computed } from 'vue'
import DeleteActionButton from '@/components/DeleteActionButton.vue'
import { formatTime } from '@/utils/chatFormatters'
import { Star, StarSolid } from '@/components/icons'
import TaskRequirementBadges from './task-rail/TaskRequirementBadges.vue'
import type { RequirementOption } from '@/types/taskRail'

interface ChatTaskListItemData {
  id: string
  name?: string | null
  status?: string | null
  task_type?: string | null
  execution_location?: string | null
  creator_name?: string | null
  created_at?: string | null
  is_following?: boolean
  workspace_id?: string
  requirements?: RequirementOption[]
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
const deleteTask = (event?: MouseEvent) => {
  (event?.currentTarget as HTMLElement)?.blur?.()
  emit('delete', props.task)
}
const toggleFollow = (event?: MouseEvent) => {
  (event?.currentTarget as HTMLElement)?.blur?.()
  emit('toggleFollow', props.task)
}
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
          <span v-if="task.execution_location === 'LOCAL'" class="task-type-tag is-local">本地</span>
          <span
            class="task-type-tag"
            :class="isDiagnosis ? 'is-diagnosis' : 'is-development'"
          >
            {{ isDiagnosis ? $t('task_types.diagnosis_short') : $t('task_types.development_short') }}
          </span>
          <span class="task-status" :title="task.status || ''">
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

    <div v-if="task.requirements?.length" class="task-requirement-row">
      <TaskRequirementBadges :workspace-id="task.workspace_id || ''" :task-id="task.id" :requirements="task.requirements" />
    </div>

    <button
      class="follow-btn"
      :class="{ active: task.is_following }"
      type="button"
      :title="$t(task.is_following ? 'chat.task_unfollow_messages' : 'chat.task_follow_messages')"
      :aria-label="$t(task.is_following ? 'chat.task_unfollow_messages' : 'chat.task_follow_messages')"
      :aria-pressed="Boolean(task.is_following)"
      @click.stop="toggleFollow($event)"
    >
      <StarSolid v-if="task.is_following" class="follow-icon" />
      <Star v-else class="follow-icon" />
    </button>

    <DeleteActionButton
      mode="icon"
      class="delete-btn"
      :title="$t('common.delete')"
      :disabled="!canDelete"
      @click="deleteTask($event)"
    />
  </article>
</template>

<style scoped>
.task-requirement-row { padding:0 10px 8px; }
.independent-label { color:var(--color-text-muted); font-size:.7rem; }
.task-item {
  position: relative;
  margin-bottom: var(--space-1);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  transition: background-color var(--transition-fast), border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.task-select {
  display: block;
  width: 100%;
  padding: 10px 58px 10px 10px;
  border: none;
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

.task-item:hover,
.task-item:has(.task-select:focus-visible) {
  background-color: var(--color-primary-50);
}

.task-item:has(.task-select:focus-visible) {
  border-color: rgba(37, 99, 235, 0.35);
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.1);
}

.task-item.active,
.task-item.active:hover {
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
  gap: 5px;
  min-width: 0;
}

.task-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  overflow: hidden;
  color: var(--color-text-muted);
  font-size: 0.68rem;
  font-weight: 500;
  line-height: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-type-tag {
  flex-shrink: 0;
  padding: 1.5px 5.5px;
  border-radius: 4px;
  font-size: 0.6875rem;
  font-weight: 500;
  letter-spacing: 0.02em;
  line-height: 1.2;
  white-space: nowrap;
}

.task-type-tag.is-local {
  color: #475569;
  background: #f1f5f9;
}

.task-type-tag.is-development {
  color: #0369a1;
  background: #f0f9ff;
}

.task-type-tag.is-diagnosis {
  color: #b45309;
  background: #fef3c7;
}

.task-item.active .task-type-tag.is-local {
  color: #1e293b;
  background: #e2e8f0;
}

.task-item.active .task-type-tag.is-development {
  color: #0284c7;
  background: #e0f2fe;
}

.task-item.active .task-type-tag.is-diagnosis {
  color: #92400e;
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
  width: 22px;
  height: 22px;
  padding: 3px;
  border: 0;
  border-radius: 6px;
  color: #94a3b8;
  background: transparent;
  cursor: pointer;
  opacity: 0.6;
  translate: 0 -50%;
  transition: opacity 0.2s, color 0.2s, background-color 0.2s, box-shadow 0.2s, transform 0.2s;
}

.follow-btn {
  right: 31px;
}

.delete-btn.delete-action-btn {
  right: 7px;
}

.follow-icon {
  width: 0.875rem;
  height: 0.875rem;
}

/* 选中或悬停任务项时：默认未收藏按钮与删除按钮透明度提升并加深背景颜色 */
.task-item:hover .follow-btn:not(.active),
.task-item:hover .delete-btn.delete-action-btn,
.task-item:has(:focus-visible) .follow-btn:not(.active),
.task-item:has(:focus-visible) .delete-btn.delete-action-btn,
.task-item.active .follow-btn:not(.active),
.task-item.active .delete-btn.delete-action-btn {
  opacity: 1;
  background: #f1f5f9;
}

/* 未收藏按钮自身 hover 时的微交互高亮 */
.follow-btn:not(.active):hover,
.task-item:hover .follow-btn:not(.active):hover,
.task-item:has(:focus-visible) .follow-btn:not(.active):hover,
.task-item.active .follow-btn:not(.active):hover {
  color: #d97706;
  background: #fef3c7;
  transform: translateY(-1px);
}

/* 已收藏状态：高辨识度视觉，常驻可见、实心饱满金黄与无边框浅色底 */
.follow-btn.active {
  color: #d97706;
  background: #fef3c7;
  opacity: 1;
}

.follow-btn.active:hover,
.task-item:hover .follow-btn.active:hover,
.task-item:has(:focus-visible) .follow-btn.active:hover,
.task-item.active .follow-btn.active:hover {
  color: #b45309;
  background: #fde68a;
  box-shadow: 0 2px 6px rgba(217, 119, 6, 0.18);
  transform: translateY(-1px);
}

.delete-btn.delete-action-btn:hover:not(:disabled) {
  color: #fff;
  background: #ef4444;
  box-shadow: 0 2px 8px rgba(239, 68, 68, 0.25);
}
</style>
