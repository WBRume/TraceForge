<script setup lang="ts">
import { computed } from 'vue'
import DeleteActionButton from '@/components/DeleteActionButton.vue'
import { formatTime } from '@/utils/chatFormatters'

interface ChatTaskListItemData {
  id: string
  name?: string | null
  status?: string | null
  task_type?: string | null
  creator_name?: string | null
  created_at?: string | null
}

const props = defineProps<{
  task: ChatTaskListItemData
  active: boolean
  canDelete: boolean
}>()

const emit = defineEmits<{
  select: [task: ChatTaskListItemData]
  delete: [task: ChatTaskListItemData]
}>()

const normalizedStatus = computed(() => String(props.task.status || '').toLowerCase())
const isDiagnosis = computed(() => props.task.task_type === 'DIAGNOSIS')
const hasMetadata = computed(() => Boolean(props.task.creator_name || props.task.created_at))

const selectTask = () => emit('select', props.task)
const deleteTask = () => emit('delete', props.task)
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
  padding: 10px 44px 10px 12px;
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

.task-item.active .task-select {
  border-color: rgba(37, 99, 235, 0.12);
  border-left: 3px solid var(--color-primary-500);
  background-color: var(--color-primary-100);
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
  color: var(--color-primary-900);
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

.delete-btn {
  position: absolute;
  top: 50%;
  right: 10px;
  z-index: 1;
  color: var(--color-text-muted);
  opacity: 0.35;
  translate: 0 -50%;
  transition: opacity 0.2s, color 0.2s;
}

.task-item:hover .delete-btn,
.task-item:focus-within .delete-btn {
  opacity: 1;
}

.delete-btn:hover {
  color: var(--color-accent-rose);
}
</style>
