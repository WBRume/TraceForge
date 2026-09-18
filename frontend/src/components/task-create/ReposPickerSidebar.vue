<!-- ReposPickerSidebar: 任务创建弹窗的仓库选择侧栏（研发态 / 问题定位任务共用）。
     仓库按仓库管理分组树形展示（复用 create-workflow 的 RepoSelectTree），
     支持批量分支与按仓库分支覆盖；仓库状态由对话框经 controller 注入。 -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { GitBranch, GitFork, Loader2 } from 'lucide-vue-next'
import SidebarPanel from './SidebarPanel.vue'
import RepoSelectTree from '@/components/workspace/create-workflow/RepoSelectTree.vue'
import { useRepoGroups } from './composables/useRepoGroups'
import type { WorkspaceReposController } from './composables/useWorkspaceRepos'
import { buildRepoTreeNodes } from './lib/repoTree'

const props = defineProps<{
  open: boolean
  controller: WorkspaceReposController
}>()

const emit = defineEmits<{ close: [] }>()

const { t } = useI18n()
const { groups, loading: groupsLoading, load: loadGroups } = useRepoGroups()

// 侧栏首次展开时拉取仓库组树（失败不阻塞：全部仓库归入“未分组”）
watch(
  () => props.open,
  (open) => {
    if (open) void loadGroups()
  },
  { immediate: true },
)

// 仓库组树：工作区仓库按仓库管理分组挂载，未分组仓库进入“未分组”节点，空组剪枝
const treeNodes = computed(() =>
  buildRepoTreeNodes(groups.value, props.controller.repos, t('workspace_create.ungrouped_repos')),
)

// 批量分支输入：一键应用到所有勾选仓库
const batchBranch = ref('')

const applyBatch = () => {
  props.controller.applyBatchBranch(batchBranch.value)
}
</script>

<template>
  <SidebarPanel
    :open="open"
    :badge="$t('dashboard.task_repo_selected_badge', { selected: controller.selectedCount, total: controller.repos.length })"
    :badge-active="controller.selectedCount > 0"
    :subtitle="$t('dashboard.task_repo_sidebar_subtitle')"
    @close="emit('close')"
  >
    <template #title>
      <div class="skills-sidebar-title">
        <GitFork class="w-4 h-4 text-primary" />
        <h3>{{ $t('dashboard.task_repo_sidebar_title') }}</h3>
      </div>
    </template>

    <!-- 批量分支修改 -->
    <template #tools>
      <div class="skills-sidebar-tools">
        <div class="skills-search-wrapper">
          <GitBranch class="w-4 h-4 skills-search-icon" />
          <input
            v-model="batchBranch"
            type="text"
            class="skills-search-input repo-batch-input"
            :placeholder="$t('dashboard.task_repo_batch_branch')"
          />
        </div>
        <button
          type="button"
          class="tool-text-btn repo-batch-apply-btn"
          :disabled="controller.selectedCount === 0 || !batchBranch.trim()"
          @click="applyBatch"
        >
          {{ $t('dashboard.task_repo_batch_apply') }}
        </button>
      </div>
    </template>

    <!-- 全选 / 清空 -->
    <template #filters>
      <div class="skills-filter-row">
        <span class="repo-sidebar-hint">{{ $t('dashboard.task_repo_sidebar_hint') }}</span>
        <button
          type="button"
          class="tool-text-btn repo-select-all-btn"
          :disabled="controller.repos.length === 0"
          @click="controller.toggleAll()"
        >
          {{ controller.allSelected ? $t('skills.task_panel.clear_all') : $t('skills.task_panel.select_all') }}
        </button>
      </div>
    </template>

    <div v-if="groupsLoading" class="skills-state center">
      <Loader2 class="w-6 h-6 spin text-primary" />
      <span>{{ $t('management.common.loading') }}</span>
    </div>

    <!-- 仓库树内容区（组节点勾选 = 全选其下仓库，支持搜索） -->
    <RepoSelectTree v-else-if="treeNodes.length > 0" v-model="controller.selectedIds" :nodes="treeNodes">
      <template #repo-extra="{ repo }">
        <div v-if="controller.isSelected(repo.id)" class="meta-repo-branch">
          <GitBranch class="w-3 h-3" />
          <input
            class="meta-branch-input"
            type="text"
            :list="`task-branch-refs-${repo.id}`"
            :value="controller.branchOverrides[repo.id] || ''"
            :placeholder="$t('dashboard.task_branch_placeholder', { branch: controller.defaultBranchOf(repo.id) })"
            @focus="controller.loadRefs(repo.id)"
            @input="controller.setBranchOverride(repo.id, ($event.target as HTMLInputElement).value)"
          />
          <datalist :id="`task-branch-refs-${repo.id}`">
            <option v-for="branch in controller.refsCache[repo.id] || []" :key="branch" :value="branch"></option>
          </datalist>
        </div>
      </template>
    </RepoSelectTree>

    <div v-else class="skills-state empty center">
      {{ $t('workspace_create.standalone_no_repo_hint') }}
    </div>
  </SidebarPanel>
</template>

<style scoped src="@/styles/task-create/task-create-shared.css"></style>
<style scoped>
.repo-sidebar-hint {
  font-size: 0.72rem;
  color: #64748b;
}

/* 仓库树内的按仓库分支输入 */
.meta-repo-branch {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #0369a1;
  flex-shrink: 0;
}

.meta-branch-input {
  width: 170px;
  padding: 2px 7px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 0.7rem;
  font-family: var(--font-mono, monospace);
  color: #0f172a;
  background: #ffffff;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.meta-branch-input:focus {
  border-color: #0ea5e9;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.12);
}

.meta-branch-input::placeholder {
  color: #94a3b8;
}
</style>
