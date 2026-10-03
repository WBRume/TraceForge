<script setup lang="ts">
import { computed } from 'vue'
import { usePinnedFloatsStore } from '@/stores/pinnedFloats'
import { Pin } from '@/components/icons'

const props = defineProps<{ taskId: string; taskName: string; workspaceId: string; workspaceName: string }>()
const store = usePinnedFloatsStore()

const isPinned = computed(() => store.items.some(item => item.kind === 'task' && item.taskId === props.taskId))

const togglePin = () => {
  const existing = store.items.find(item => item.kind === 'task' && item.taskId === props.taskId)
  if (existing) {
    store.unpin(existing.id)
  } else {
    store.pinTask({
      id: props.taskId,
      name: props.taskName,
      workspaceId: props.workspaceId,
      workspaceName: props.workspaceName,
    })
  }
}
</script>

<template>
  <button
    type="button"
    class="task-pin-icon-btn"
    :class="{ 'is-pinned': isPinned }"
    :title="isPinned ? '取消窗口钉选' : '钉在窗口中'"
    :aria-label="isPinned ? '取消窗口钉选' : '钉在窗口中'"
    :aria-pressed="isPinned ? 'true' : 'false'"
    @click="togglePin"
  >
    <Pin class="w-3.5 h-3.5 pin-icon" />
    <span class="sr-only">钉在窗口中</span>
  </button>
</template>

<style scoped>
.task-pin-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: var(--radius-md, 6px);
  border: 1px solid transparent;
  background: transparent;
  color: var(--color-text-muted, #64748b);
  cursor: pointer;
  transition: all 0.15s ease;
  flex-shrink: 0;
  padding: 0;
}

.task-pin-icon-btn:hover {
  background-color: rgba(0, 0, 0, 0.05);
  color: var(--color-text-main, #0f172a);
}

.task-pin-icon-btn.is-pinned {
  color: var(--color-primary-600, #0284c7);
  background-color: var(--color-primary-50, #f0f9ff);
  border-color: rgba(14, 165, 233, 0.2);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border-width: 0;
}
</style>
