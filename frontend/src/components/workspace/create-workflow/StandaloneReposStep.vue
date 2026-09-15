<!--
Workspace creation workflow: standalone mode repository selection.
Repositories are presented as a repo-group tree (from 仓库管理); ungrouped
repositories fall into a virtual "ungrouped" node. Checking a group selects
all repositories inside it, and each selected repo needs a branch.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { GitBranch } from 'lucide-vue-next'
import { getRepositoryRefs } from '@/services/managementApi'
import RepoSelectTree from './RepoSelectTree.vue'
import type { RepoSelectTreeNode, RepoSelectTreeRepo } from './RepoSelectTree.vue'
import type { RepoGroupTreeNode, Repository } from '@/types/management'

const props = defineProps<{
  repos: Repository[]
  groups: RepoGroupTreeNode[]
  loading: boolean
  selected: string[]
  branches: Record<string, string>
}>()

const emit = defineEmits<{
  (e: 'update:selected', value: string[]): void
  (e: 'update:branches', value: Record<string, string>): void
}>()

const { t } = useI18n()

// 每个仓库的远端分支列表（懒加载，用于分支下拉建议）
const refsCache = ref<Record<string, string[]>>({})
const refsLoading = ref<Record<string, boolean>>({})

const loadRefs = async (repo: Repository) => {
  if (refsCache.value[repo.id] || refsLoading.value[repo.id]) return
  refsLoading.value = { ...refsLoading.value, [repo.id]: true }
  try {
    const payload = await getRepositoryRefs(repo.id)
    refsCache.value = { ...refsCache.value, [repo.id]: payload.branches || [] }
  } catch {
    // 拉取失败时不阻塞：保留默认分支 + 手动输入
    refsCache.value = { ...refsCache.value, [repo.id]: [] }
  } finally {
    refsLoading.value = { ...refsLoading.value, [repo.id]: false }
  }
}

const repoById = computed(() => {
  const map = new Map<string, Repository>()
  for (const repo of props.repos) map.set(repo.id, repo)
  return map
})

const toTreeRepo = (repo: Repository): RepoSelectTreeRepo => ({
  id: repo.id,
  name: repo.name,
  git_url: repo.git_url,
  repo_type: repo.repo_type,
  default_branch: repo.default_branch,
})

// 组树 + 仓库列表合成选择树；无组的仓库进入“未分组”节点，空组剪枝
const nodes = computed<RepoSelectTreeNode[]>(() => {
  const knownGroupIds = new Set<string>()
  const walkGroups = (items: RepoGroupTreeNode[]): void => {
    for (const item of items) {
      if (item.id) knownGroupIds.add(item.id)
      walkGroups(item.children || [])
    }
  }
  walkGroups(props.groups)

  const reposByGroup = new Map<string, Repository[]>()
  const ungrouped: Repository[] = []
  for (const repo of props.repos) {
    if (repo.group_id && knownGroupIds.has(repo.group_id)) {
      const list = reposByGroup.get(repo.group_id) || []
      list.push(repo)
      reposByGroup.set(repo.group_id, list)
    } else {
      ungrouped.push(repo)
    }
  }

  const buildNode = (group: RepoGroupTreeNode): RepoSelectTreeNode => ({
    key: group.id || group.name,
    name: group.name,
    repos: (reposByGroup.get(group.id || '') || []).map(toTreeRepo),
    children: (group.children || []).map(buildNode),
  })

  const prune = (node: RepoSelectTreeNode): RepoSelectTreeNode | null => {
    const children = node.children
      .map(prune)
      .filter((child): child is RepoSelectTreeNode => child !== null)
    if (node.repos.length === 0 && children.length === 0) return null
    return { ...node, children }
  }

  const result: RepoSelectTreeNode[] = []
  for (const group of props.groups) {
    const node = prune(buildNode(group))
    if (node) result.push(node)
  }
  if (ungrouped.length > 0) {
    result.push({
      key: '__ungrouped__',
      name: t('workspace_create.ungrouped_repos'),
      repos: ungrouped.map(toTreeRepo),
      children: [],
    })
  }
  return result
})

const defaultBranchOf = (repoId: string): string =>
  repoById.value.get(repoId)?.default_branch || 'main'

const branchOf = (repoId: string): string => props.branches[repoId] || ''

const onBranchInput = (repoId: string, value: string) => {
  emit('update:branches', { ...props.branches, [repoId]: value })
}

// 选中项变化：新选中的仓库补默认分支，取消选中的清理分支记录，并懒加载分支建议
watch(
  () => props.selected,
  (ids, previous) => {
    const prev = new Set(previous || [])
    const next = new Set(ids)
    const branches: Record<string, string> = { ...props.branches }
    let changed = false
    for (const id of ids) {
      if (!prev.has(id) && !branches[id]) {
        branches[id] = defaultBranchOf(id)
        changed = true
      }
      const repo = repoById.value.get(id)
      if (repo) void loadRefs(repo)
    }
    for (const id of previous || []) {
      if (!next.has(id) && id in branches) {
        delete branches[id]
        changed = true
      }
    }
    if (changed) emit('update:branches', branches)
  },
  { immediate: true },
)

const proxySelected = computed({
  get: () => props.selected,
  set: (value: string[]) => emit('update:selected', value),
})
</script>

<template>
  <div class="wf-step">
    <p class="mgmt-hint">{{ $t('workspace_create.standalone_repos_hint') }}</p>

    <div v-if="loading" class="mgmt-empty">{{ $t('management.common.loading') }}</div>

    <div v-else-if="repos.length === 0" class="mgmt-empty">
      {{ $t('workspace_create.standalone_no_repo_hint') }}
    </div>

    <RepoSelectTree v-else v-model="proxySelected" :nodes="nodes">
      <template #repo-extra="{ repo }">
        <div v-if="selected.includes(repo.id)" class="wf-branch-picker">
          <GitBranch class="w-3.5 h-3.5" />
          <input
            class="wf-branch-input"
            type="text"
            :list="`wf-branch-refs-${repo.id}`"
            :value="branchOf(repo.id)"
            :placeholder="$t('workspace_create.branch_placeholder', { branch: defaultBranchOf(repo.id) })"
            @input="onBranchInput(repo.id, ($event.target as HTMLInputElement).value)"
          />
          <datalist :id="`wf-branch-refs-${repo.id}`">
            <option v-for="branch in refsCache[repo.id] || []" :key="branch" :value="branch"></option>
          </datalist>
        </div>
      </template>
    </RepoSelectTree>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
<style scoped>
.wf-step {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}

.wf-branch-picker {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  color: #0369a1;
  flex-shrink: 0;
}

.wf-branch-input {
  width: 180px;
  padding: 0.28rem 0.55rem;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 0.78rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  color: #0f172a;
  background: #ffffff;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.wf-branch-input:focus {
  border-color: #0ea5e9;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.12);
}

.w-3\.5 {
  width: 0.875rem;
  height: 0.875rem;
}
</style>
