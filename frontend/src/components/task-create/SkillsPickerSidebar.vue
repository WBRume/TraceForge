<!-- SkillsPickerSidebar: 任务创建弹窗的技能选择侧栏（研发 / 诊断态任务均可展开）。
     服务端分页搜索 / scope 过滤 / 分页为选择器私有状态；
     勾选集经 v-model 交给对话框，提交时组装 skill_ids。 -->
<script setup lang="ts">
import { onMounted } from 'vue'
import { FolderOpen, Globe, Loader2, RefreshCw, Search, Sparkles, X } from 'lucide-vue-next'
import SidebarPanel from './SidebarPanel.vue'
import { isDraftSkill, useTaskSkillPicker } from './composables/useTaskSkillPicker'

const props = defineProps<{
  wsId: string
  open: boolean
}>()

const emit = defineEmits<{ close: [] }>()

const selectedIds = defineModel<string[]>('selectedIds', { required: true })

const {
  skills,
  loading,
  keyword,
  scope,
  page,
  total,
  totalPages,
  hasDrafts,
  isCurrentPageAllSelected,
  load,
  onSearchInput,
  clearSearch,
  onScopeChange,
  prevPage,
  nextPage,
  toggleSkill,
  toggleCurrentPageAll,
} = useTaskSkillPicker({ wsId: () => props.wsId, selectedIds })

onMounted(() => {
  void load(1)
})
</script>

<template>
  <SidebarPanel
    :open="open"
    :badge="$t('skills.task_panel.selected_count', { count: selectedIds.length })"
    :badge-active="selectedIds.length > 0"
    :subtitle="$t('skills.task_panel.sidebar_subtitle')"
    @close="emit('close')"
  >
    <template #title>
      <div class="skills-sidebar-title">
        <Sparkles class="w-4 h-4 text-primary" />
        <h3>{{ $t('skills.task_panel.sidebar_title') }}</h3>
      </div>
    </template>

    <!-- 服务端关键字搜索 + 刷新（搜索框纯白背景） -->
    <template #tools>
      <div class="skills-sidebar-tools">
        <div class="skills-search-wrapper">
          <Search class="w-4 h-4 skills-search-icon" />
          <input
            v-model="keyword"
            type="text"
            class="skills-search-input"
            :placeholder="$t('skills.task_panel.search_placeholder')"
            @input="onSearchInput"
          />
          <button v-if="keyword" type="button" class="skills-search-clear" @click="clearSearch">
            <X class="w-3.5 h-3.5" />
          </button>
        </div>
        <button
          type="button"
          class="tool-icon-btn"
          :title="$t('skills.task_panel.refresh')"
          :disabled="loading"
          @click="load(page)"
        >
          <RefreshCw class="w-3.5 h-3.5" :class="{ spin: loading }" />
        </button>
      </div>
    </template>

    <!-- 范围过滤 Pills + 全选当前页 -->
    <template #filters>
      <div class="skills-filter-row">
        <div class="scope-pills">
          <button type="button" class="scope-pill" :class="{ active: scope === 'all' }" @click="onScopeChange('all')">
            {{ $t('skills.task_panel.scope_all') }}
          </button>
          <button type="button" class="scope-pill" :class="{ active: scope === 'workspace' }" @click="onScopeChange('workspace')">
            <FolderOpen class="w-3.5 h-3.5" />
            {{ $t('skills.task_panel.scope_workspace') }}
          </button>
          <button type="button" class="scope-pill" :class="{ active: scope === 'global' }" @click="onScopeChange('global')">
            <Globe class="w-3.5 h-3.5" />
            {{ $t('skills.task_panel.scope_global') }}
          </button>
        </div>
        <button type="button" class="tool-text-btn" :disabled="skills.length === 0" @click="toggleCurrentPageAll">
          {{ isCurrentPageAllSelected ? $t('skills.task_panel.clear_all') : $t('skills.task_panel.select_all') }}
        </button>
      </div>
    </template>

    <!-- 草稿技能提示 -->
    <template v-if="hasDrafts" #notice>
      <div class="skills-state-note">{{ $t('skills.task_panel.draft_publish_hint') }}</div>
    </template>

    <div v-if="loading" class="skills-state center">
      <Loader2 class="w-6 h-6 spin text-primary" />
      <span>{{ $t('skills.task_panel.loading') }}</span>
    </div>

    <div v-else-if="skills.length === 0 && keyword" class="skills-state empty center">
      {{ $t('skills.task_panel.search_empty') }}
    </div>

    <div v-else-if="skills.length === 0" class="skills-state empty center">
      {{ $t('skills.task_panel.empty') }}
    </div>

    <div v-else class="skills-list">
      <div
        v-for="skill in skills"
        :key="skill.id"
        class="skill-card-item"
        :class="{ selected: selectedIds.includes(skill.id) }"
        @click="toggleSkill(skill.id)"
      >
        <div class="skill-checkbox-wrapper">
          <input
            type="checkbox"
            :checked="selectedIds.includes(skill.id)"
            @click.stop
            @change="toggleSkill(skill.id)"
          />
        </div>
        <div class="skill-item-body">
          <div class="skill-title-row">
            <div class="skill-name-group">
              <FolderOpen v-if="skill.dimension === 'WORKSPACE'" class="w-3.5 h-3.5 text-primary flex-shrink-0" />
              <Globe v-else class="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
              <span class="skill-name">{{ skill.name }}</span>
            </div>
            <span class="skill-status-tag" :class="{ draft: isDraftSkill(skill) }">
              {{ isDraftSkill(skill) ? $t('skills.task_panel.status_draft') : $t('skills.task_panel.status_published') }}
            </span>
          </div>
          <div class="skill-desc" :title="skill.description">{{ skill.description || $t('skills.list.no_description') }}</div>
        </div>
      </div>
    </div>

    <!-- 服务端分页底部栏（与 skills 配置页面风格完全一致） -->
    <template #footer>
      <button class="btn-secondary mini page-nav-btn" :disabled="page <= 1 || loading" @click="prevPage">
        {{ $t('skills.list.prev_page') }}
      </button>
      <div class="pagination-info">
        <span class="skills-page-info">
          {{ $t('skills.list.page_info', { page, total: totalPages }) }}
        </span>
        <span class="pagination-badge">{{ total }}</span>
      </div>
      <button class="btn-secondary mini page-nav-btn" :disabled="page >= totalPages || loading" @click="nextPage">
        {{ $t('skills.list.next_page') }}
      </button>
    </template>
  </SidebarPanel>
</template>

<style scoped src="@/styles/task-create/task-create-shared.css"></style>
<style scoped>
.skills-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.skill-card-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.skill-card-item:hover {
  border-color: #7dd3fc;
  background: #f0f9ff;
  transform: translateY(-1px);
}

.skill-card-item.selected {
  border-color: #0ea5e9;
  background: #f0f9ff;
  box-shadow: 0 0 0 1px #0ea5e9, 0 2px 6px rgba(14, 165, 233, 0.08);
}

.skill-checkbox-wrapper {
  margin-top: 2px;
  display: flex;
  align-items: center;
}

.skill-checkbox-wrapper input[type="checkbox"] {
  appearance: none;
  -webkit-appearance: none;
  width: 17px;
  height: 17px;
  margin: 0;
  border-radius: 5px;
  border: 1.5px solid #cbd5e1;
  background-color: #ffffff;
  background-repeat: no-repeat;
  background-position: center;
  background-size: 11px 11px;
  cursor: pointer;
  transition: all 0.16s cubic-bezier(0.4, 0, 0.2, 1);
  flex-shrink: 0;
  outline: none;
  display: inline-block;
}

.skill-checkbox-wrapper input[type="checkbox"]:hover:not(:checked):not(:disabled) {
  border-color: #38bdf8;
  background-color: #f0f9ff;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.12);
}

.skill-checkbox-wrapper input[type="checkbox"]:checked:hover:not(:disabled) {
  border-color: #0284c7;
  background-color: #0284c7;
  box-shadow: 0 2px 6px rgba(14, 165, 233, 0.35);
}

.skill-checkbox-wrapper input[type="checkbox"]:checked {
  border-color: #0ea5e9;
  background-color: #0ea5e9;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 14 14' fill='none'%3E%3Cpath d='M2.5 7L5.5 10L11.5 4' stroke='%23ffffff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  box-shadow: 0 2px 5px rgba(14, 165, 233, 0.28);
}

.skill-checkbox-wrapper input[type="checkbox"]:focus-visible {
  border-color: #0ea5e9;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.22);
}

.skill-item-body {
  min-width: 0;
  flex: 1;
}

.skill-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.skill-name-group {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
}

.skill-name {
  font-size: 0.82rem;
  font-weight: 700;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.skill-card-item.selected .skill-name {
  color: #0369a1;
}

.skill-status-tag {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 0.65rem;
  font-weight: 600;
  color: #15803d;
  background: #dcfce7;
  border: 1px solid #bbf7d0;
  white-space: nowrap;
  flex-shrink: 0;
}

.skill-status-tag.draft {
  color: #c2410c;
  background: #ffedd5;
  border-color: #fed7aa;
}

.skill-desc {
  margin-top: 3px;
  font-size: 0.72rem;
  color: #64748b;
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
