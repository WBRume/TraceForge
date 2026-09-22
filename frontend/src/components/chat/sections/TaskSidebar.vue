<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Plus, SlidersHorizontal, Loader2 } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import TaskAdvancedFilterDrawer from '@/components/chat/TaskAdvancedFilterDrawer.vue'
import ChatTaskListItem from '@/components/chat/ChatTaskListItem.vue'
import type { Ref } from 'vue'
import type { ChatViewVm } from '@/composables/chat/useChatViewModel'

/**
 * 会话列表侧栏：状态/类型过滤、高级关系过滤、会话列表与滚动分页加载。
 * 列表滚动容器的 DOM 归属由视图模型（useTaskList）持有，经 listContainerRef 注入。
 */
const props = defineProps<{
  vm: ChatViewVm
  listContainerRef: Ref<HTMLElement | null>
}>()

const { t } = useI18n()
const advancedFilterOpen = ref(false)
</script>

<template>
  <aside class="task-sidebar glass-panel">
    <div class="sidebar-header">
      <div class="sidebar-title-row">
        <h3>{{ t('chat.terminal') }}</h3>
        <div class="sidebar-title-actions">
          <span class="advanced-filter-anchor">
            <button
              class="advanced-filter-btn"
              :class="{ active: props.vm.taskRelationFilter.length > 0 }"
              type="button"
              :title="t('chat.task_advanced_filter')"
              :aria-label="t('chat.task_advanced_filter')"
              @click="advancedFilterOpen = true"
            >
              <SlidersHorizontal class="w-4 h-4" />
              <span v-if="props.vm.taskRelationFilter.length > 0" class="advanced-filter-badge">{{ props.vm.taskRelationFilter.length }}</span>
            </button>
            <TaskAdvancedFilterDrawer
              v-model="advancedFilterOpen"
              :relations="props.vm.taskRelationFilter"
              @apply="props.vm.applyTaskRelationFilter"
              @reset="props.vm.resetTaskRelationFilter"
            />
          </span>
          <button class="new-session-btn" :disabled="!props.vm.canCreateTask" @click="props.vm.openNewTaskModal" :title="t('dashboard.new_task')">
            <Plus class="w-4 h-4" />
          </button>
        </div>
      </div>
      <div class="sidebar-filter-row">
        <div class="sidebar-filter-item">
          <span class="sidebar-filter-label">{{ t('chat.session_filter_label') }}</span>
          <BaseSelect
            v-model="props.vm.taskStatusFilter"
            :options="[
              { label: t('chat.session_filter_all'), value: 'ALL' },
              { label: t('chat.session_filter_success'), value: 'DONE' },
              { label: t('chat.session_filter_failed'), value: 'FAILED' },
            ]"
            size="sm"
            class="task-filter-select"
            @update:modelValue="props.vm.applyTaskStatusFilter"
          />
        </div>
        <div class="sidebar-filter-item">
          <span class="sidebar-filter-label">{{ t('chat.session_type_label') }}</span>
          <BaseSelect
            v-model="props.vm.taskTypeFilter"
            :options="[
              { label: t('chat.session_type_all'), value: 'ALL' },
              { label: t('task_types.development'), value: 'DEVELOPMENT' },
              { label: t('task_types.diagnosis'), value: 'DIAGNOSIS' },
            ]"
            size="sm"
            class="task-filter-select"
            @update:modelValue="props.vm.applyTaskTypeFilter"
          />
        </div>
      </div>
    </div>
    <div class="task-list" :ref="props.listContainerRef" @scroll="props.vm.handleTaskListScroll">
      <ChatTaskListItem
        v-for="task in props.vm.tasks"
        :key="task.id"
        :task="task"
        :active="props.vm.currentTask?.id === task.id"
        :can-delete="props.vm.canDeleteTask"
        @select="props.vm.selectTask"
        @delete="props.vm.handleDeleteTask"
        @toggle-follow="props.vm.toggleTaskFollow"
      />
      <div v-if="props.vm.taskListLoading && props.vm.tasks.length === 0" class="empty-hint">
        {{ t('common.loading') }}
      </div>
      <div v-else-if="props.vm.tasks.length === 0" class="empty-hint">
        {{ t('chat.empty_hint') }}
      </div>
      <div v-if="props.vm.taskListLoadingMore" class="task-list-footer">
        <Loader2 class="w-4 h-4 spin" />
        <span>{{ t('common.loading') }}</span>
      </div>
      <div v-else-if="props.vm.taskListHasMore" class="task-list-footer task-list-footer-hint">
        {{ t('chat.session_scroll_load_more') }}
      </div>
    </div>
  </aside>
</template>

<style scoped>
.task-sidebar {
  width: 280px;
  border-radius: 0;
  border: none;
  border-right: 1px solid rgba(0,0,0,0.05);
  display: flex;
  flex-direction: column;
  background-color: var(--color-surface-white);
  z-index: 5;
  flex: 0 0 auto;
  transition: margin-left 0.28s ease, opacity 0.24s ease, visibility 0s;
}

/* SOP 模式折叠态：负外边距滑出视口（chat-layout overflow hidden 裁切），
   不改宽度以避免内容回流抖动；visibility 延迟到滑动结束后生效 */
.task-sidebar.is-collapsed {
  margin-left: -280px;
  opacity: 0;
  pointer-events: none;
  visibility: hidden;
  transition: margin-left 0.28s ease, opacity 0.24s ease, visibility 0s 0.28s;
}

.sidebar-header {
  padding: var(--space-4);
  border-bottom: 1px solid rgba(0,0,0,0.05);
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 10px;
}
.sidebar-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.sidebar-title-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.sidebar-header h3 {
  margin: 0;
  font-weight: 600;
  color: var(--color-primary-900);
}
.sidebar-filter-row {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
}
.sidebar-filter-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}
.sidebar-filter-label {
  font-size: 0.75rem;
  color: var(--color-text-muted);
  white-space: nowrap;
  flex-shrink: 0;
}
.task-filter-select {
  flex: 1;
  min-width: 0;
}
.task-filter-select:deep(.select-trigger) {
  height: 32px;
  border-radius: 8px;
  padding: 0 8px;
  border-color: rgba(148, 163, 184, 0.35);
}
.task-filter-select:deep(.selected-text) {
  font-size: 0.8rem;
}

.task-list { flex: 1; overflow-y: auto; padding: var(--space-2); }

.empty-hint {
  padding: var(--space-4);
  font-size: 0.875rem;
  color: var(--color-text-muted);
  text-align: center;
}
.task-list-footer {
  margin: 6px 2px 2px;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 0.75rem;
  color: var(--color-text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.task-list-footer-hint {
  color: var(--color-primary-500);
  background: rgba(37, 99, 235, 0.06);
}

.advanced-filter-anchor {
  position: relative;
  display: inline-flex;
}

.advanced-filter-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 8px;
  color: var(--color-text-muted);
  background: transparent;
  cursor: pointer;
  transition: color var(--transition-fast), background-color var(--transition-fast), border-color var(--transition-fast);
}

.advanced-filter-btn:hover,
.advanced-filter-btn.active {
  border-color: rgba(37, 99, 235, 0.22);
  color: var(--color-primary-600);
  background: var(--color-primary-50);
}

.advanced-filter-badge {
  position: absolute;
  top: -3px;
  right: -3px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  color: #fff;
  background: var(--color-primary-600);
  font-size: 0.6rem;
  font-weight: 700;
  line-height: 1;
}

.new-session-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: linear-gradient(135deg, var(--color-primary-500) 0%, var(--color-primary-700) 100%);
  color: white;
  border: none;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.4);
}

.new-session-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 6px 15px rgba(14, 165, 233, 0.4);
  filter: brightness(1.1);
}

.new-session-btn:active:not(:disabled) {
  transform: translateY(0);
}

.new-session-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  background: var(--color-text-muted);
  box-shadow: none;
}
</style>
