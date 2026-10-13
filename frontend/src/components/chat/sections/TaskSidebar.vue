<script setup lang="ts">
import { computed, shallowRef, useId, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { Plus, Search, Funnel, Loader2, X } from '@/components/icons'
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
const advancedFilterOpen = shallowRef(false)
const filterButton = useTemplateRef<HTMLButtonElement>('filterButton')
const filterId = `task-filters-${useId()}`
const activeFilterCount = computed(() => props.vm.taskRelationFilter.length
  + Number(props.vm.taskStatusFilter !== 'ALL')
  + Number(props.vm.taskTypeFilter !== 'ALL'))
const filterLabel = computed(() => activeFilterCount.value
  ? t('chat.task_filter_count', { count: activeFilterCount.value })
  : t('chat.task_advanced_filter'))
</script>

<template>
  <aside class="task-sidebar glass-panel">
    <div class="sidebar-header">
      <div class="sidebar-title-row">
        <h3 :title="props.vm.taskViewLabel">{{ props.vm.taskViewLabel }}</h3>
        <button type="button" class="new-session-btn" :disabled="!props.vm.canCreateTask" @click="props.vm.openNewTaskModal" :title="t('dashboard.new_task')" :aria-label="t('dashboard.new_task')">
          <Plus class="w-4 h-4" />
        </button>
      </div>
      <div class="sidebar-search">
        <Search class="sidebar-search-icon" aria-hidden="true" />
        <input
          v-model="props.vm.taskSearchQuery"
          type="search"
          class="sidebar-search-input"
          :placeholder="t('chat.task_search_placeholder')"
          :aria-label="t('chat.task_search_label')"
          maxlength="200"
        />
        <button v-if="props.vm.taskSearchQuery" type="button" class="search-clear-btn" :aria-label="t('chat.task_search_clear')" @click="props.vm.taskSearchQuery = ''">
          <X class="w-3 h-3" />
        </button>
        <button
          ref="filterButton"
          class="advanced-filter-btn"
          :class="{ active: activeFilterCount > 0 || advancedFilterOpen }"
          type="button"
          :title="filterLabel"
          :aria-label="filterLabel"
          :aria-expanded="advancedFilterOpen"
          :aria-controls="filterId"
          aria-haspopup="dialog"
          @click="advancedFilterOpen = !advancedFilterOpen"
        >
          <Funnel class="w-4 h-4" />
          <span v-if="activeFilterCount" class="advanced-filter-badge" aria-hidden="true">{{ activeFilterCount }}</span>
        </button>
        <TaskAdvancedFilterDrawer
          :id="filterId"
          v-model="advancedFilterOpen"
          :trigger="filterButton"
          :status="props.vm.taskStatusFilter"
          :task-type="props.vm.taskTypeFilter"
          :relations="props.vm.taskRelationFilter"
          @apply="props.vm.applyTaskFilters"
          @reset="props.vm.resetTaskFilters"
        />
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
      <button v-else-if="props.vm.taskListError" type="button" class="empty-hint retry-list" @click="props.vm.retryTaskList">{{ t('task_rail.retry') }}</button>
      <div v-else-if="props.vm.tasks.length === 0" class="empty-hint">
        {{ props.vm.taskSearchQuery.trim() || activeFilterCount ? t('chat.task_search_empty') : t('task_rail.empty_tasks', { view: props.vm.taskViewLabel }) }}
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
.sidebar-title-row h3 { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:.9rem; }
.retry-list { border:0; background:transparent; cursor:pointer; }
.task-sidebar {
  width: 280px;
  max-width: 100%;
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
  padding: 16px 10px 12px;
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
  gap: 12px;
}
.sidebar-header h3 {
  margin: 0;
  font-weight: 600;
  color: var(--color-primary-900);
}
.sidebar-search {
  position: relative;
  display: flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 4px 0 8px;
  border: 1px solid #dce5ef;
  border-radius: 8px;
  background: var(--color-bg-base);
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}
.sidebar-search:focus-within {
  border-color: var(--color-primary-500);
  box-shadow: 0 0 0 2px var(--color-primary-100);
}
.sidebar-search-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  color: #94a3b8;
}
.sidebar-search-input {
  flex: 1;
  min-width: 0;
  width: 100%;
  height: 100%;
  padding: 0;
  border: 0;
  outline: none;
  background: transparent;
  color: var(--color-text-body);
  font: inherit;
  font-size: 0.75rem;
}
.sidebar-search-input::placeholder { color: #94a3b8; }
.sidebar-search-input::-webkit-search-cancel-button { display: none; }
.search-clear-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 20px;
  height: 24px;
  padding: 0;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}
.search-clear-btn:hover { background: var(--color-primary-100); }
.new-session-btn:focus-visible,
.advanced-filter-btn:focus-visible,
.search-clear-btn:focus-visible {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 2px;
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

.advanced-filter-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 28px;
  height: 24px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 5px;
  color: var(--color-primary-600);
  background: var(--color-primary-50);
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
  top: -4px;
  right: -4px;
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
  flex-shrink: 0;
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
