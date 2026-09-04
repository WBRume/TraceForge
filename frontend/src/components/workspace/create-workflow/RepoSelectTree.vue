<!-- RepoSelectTree: searchable repo selection tree; checking a group node
     selects every visible repository in its subtree. Repo row extras are
     provided through the "repo-extra" scoped slot. -->
<script lang="ts">
export interface RepoSelectTreeRepo {
  id: string
  name: string
  git_url: string
  repo_type?: string
  default_branch?: string
  ref_type?: string
  ref_name?: string
}

export interface RepoSelectTreeNode {
  key: string
  name: string
  repos: RepoSelectTreeRepo[]
  children: RepoSelectTreeNode[]
}
</script>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Folder, Search } from 'lucide-vue-next'

const props = defineProps<{
  nodes: RepoSelectTreeNode[]
  modelValue: string[]
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
}>()

const keyword = ref('')
const kw = computed(() => keyword.value.trim().toLowerCase())

const repoMatches = (repo: RepoSelectTreeRepo): boolean => {
  if (!kw.value) return true
  return (
    repo.name.toLowerCase().includes(kw.value)
    || repo.git_url.toLowerCase().includes(kw.value)
  )
}

// 命中组名时保留整棵子树；否则只保留命中的仓库及祖先路径
const filterNode = (node: RepoSelectTreeNode): RepoSelectTreeNode | null => {
  if (kw.value && node.name.toLowerCase().includes(kw.value)) {
    return { ...node }
  }
  const repos = node.repos.filter(repoMatches)
  const children = (node.children || [])
    .map(filterNode)
    .filter((child): child is RepoSelectTreeNode => child !== null)
  if (repos.length === 0 && children.length === 0) return null
  return { ...node, repos, children }
}

const filteredNodes = computed<RepoSelectTreeNode[]>(() =>
  props.nodes
    .map(filterNode)
    .filter((node): node is RepoSelectTreeNode => node !== null),
)

const countRepos = (node: RepoSelectTreeNode): number =>
  node.repos.length + (node.children || []).reduce((sum, child) => sum + countRepos(child), 0)

const totalRepos = computed(() =>
  props.nodes.reduce((sum, node) => sum + countRepos(node), 0),
)

const collectVisibleRepos = (node: RepoSelectTreeNode): RepoSelectTreeRepo[] => {
  const repos = [...node.repos]
  for (const child of node.children || []) {
    repos.push(...collectVisibleRepos(child))
  }
  return repos
}

const groupChecked = (node: RepoSelectTreeNode): boolean | 'indeterminate' => {
  const repos = collectVisibleRepos(node)
  if (repos.length === 0) return false
  const count = repos.filter((repo) => props.modelValue.includes(repo.id)).length
  if (count === 0) return false
  return count === repos.length ? true : 'indeterminate'
}

const toggleGroup = (node: RepoSelectTreeNode): void => {
  const repos = collectVisibleRepos(node)
  const allSelected = repos.length > 0 && repos.every((repo) => props.modelValue.includes(repo.id))
  const selected = new Set(props.modelValue)
  for (const repo of repos) {
    if (allSelected) {
      selected.delete(repo.id)
    } else {
      selected.add(repo.id)
    }
  }
  emit('update:modelValue', [...selected])
}

const toggleRepo = (repoId: string): void => {
  const selected = new Set(props.modelValue)
  if (selected.has(repoId)) {
    selected.delete(repoId)
  } else {
    selected.add(repoId)
  }
  emit('update:modelValue', [...selected])
}

interface GroupRow {
  type: 'group'
  node: RepoSelectTreeNode
  depth: number
}

interface RepoRow {
  type: 'repo'
  repo: RepoSelectTreeRepo
  depth: number
}

type TreeRow = GroupRow | RepoRow

const flatRows = computed<TreeRow[]>(() => {
  const rows: TreeRow[] = []
  const walk = (node: RepoSelectTreeNode, depth: number): void => {
    rows.push({ type: 'group', node, depth })
    for (const repo of node.repos) {
      rows.push({ type: 'repo', repo, depth: depth + 1 })
    }
    for (const child of node.children || []) {
      walk(child, depth + 1)
    }
  }
  for (const node of filteredNodes.value) {
    walk(node, 0)
  }
  return rows
})

const indentStyle = (depth: number) => ({
  paddingLeft: depth > 0 ? `${depth * 1.1}rem` : '0',
})
</script>

<template>
  <div class="wf-repo-tree">
    <div class="wf-tree-search">
      <div class="wf-search-wrap">
        <Search class="w-4 h-4 wf-search-icon" />
        <input
          v-model="keyword"
          type="text"
          class="mgmt-search"
          :placeholder="$t('management.repository.search_placeholder')"
        />
      </div>
      <span class="wf-tree-summary">
        {{ $t('workspace_create.selected_count', { count: modelValue.length, total: totalRepos }) }}
      </span>
    </div>

    <div class="wf-tree-scroll">
      <div v-if="flatRows.length === 0" class="mgmt-empty">
        {{ $t('workspace_create.repo_search_empty') }}
      </div>

      <template v-for="row in flatRows" :key="row.type === 'group' ? `g-${row.node.key}` : `r-${row.repo.id}`">
        <label
          v-if="row.type === 'group'"
          class="wf-tree-group"
          :style="indentStyle(row.depth)"
        >
          <input
            type="checkbox"
            class="wf-tree-checkbox"
            :checked="groupChecked(row.node) === true"
            :indeterminate="groupChecked(row.node) === 'indeterminate'"
            @change="toggleGroup(row.node)"
          />
          <Folder class="w-4 h-4 wf-tree-folder" />
          <span class="wf-tree-group-name">{{ row.node.name }}</span>
          <span class="wf-tree-group-count">{{ collectVisibleRepos(row.node).length }}</span>
        </label>

        <div
          v-else
          class="wf-tree-repo"
          :class="{ selected: modelValue.includes(row.repo.id) }"
          :style="indentStyle(row.depth)"
        >
          <label class="wf-tree-repo-main">
            <input
              type="checkbox"
              class="wf-tree-checkbox"
              :checked="modelValue.includes(row.repo.id)"
              @change="toggleRepo(row.repo.id)"
            />
            <span class="wf-tree-repo-info">
              <span class="wf-tree-repo-name">{{ row.repo.name }}</span>
              <span class="wf-tree-repo-url" :title="row.repo.git_url">{{ row.repo.git_url }}</span>
            </span>
          </label>
          <div class="wf-tree-repo-extra">
            <slot name="repo-extra" :repo="row.repo" />
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
<style scoped>
.wf-repo-tree {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.wf-tree-search {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.wf-search-wrap {
  position: relative;
  flex: 1;
  min-width: 0;
}

.wf-search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: #94a3b8;
  pointer-events: none;
}

.wf-search-wrap .mgmt-search {
  width: 100%;
  padding-left: 2rem;
}

.wf-tree-summary {
  flex-shrink: 0;
  font-size: 0.78rem;
  font-weight: 600;
  color: #0ea5e9;
  white-space: nowrap;
}

.wf-tree-scroll {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  max-height: 320px;
  overflow-y: auto;
  padding: 0.25rem;
}

.wf-tree-group {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.45rem 0.6rem;
  border: 1.5px solid #e2e8f0;
  border-radius: 10px;
  background: rgba(248, 250, 252, 0.85);
  cursor: pointer;
  transition: all 0.2s;
}

.wf-tree-group:hover {
  border-color: #7dd3fc;
  background: #f0f9ff;
}

.wf-tree-folder {
  color: #0ea5e9;
  flex-shrink: 0;
}

.wf-tree-group-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 700;
  font-size: 0.86rem;
  color: #334155;
}

.wf-tree-group-count {
  flex-shrink: 0;
  padding: 0.05rem 0.5rem;
  border-radius: 999px;
  background: #e0f2fe;
  color: #0369a1;
  font-size: 0.72rem;
  font-weight: 700;
}

.wf-tree-checkbox {
  width: 1rem;
  height: 1rem;
  flex-shrink: 0;
  accent-color: #0ea5e9;
  cursor: pointer;
}

.wf-tree-repo {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  border: 1.5px solid #e2e8f0;
  border-radius: 10px;
  padding: 0.45rem 0.7rem;
  background: rgba(255, 255, 255, 0.75);
  transition: all 0.2s;
}

.wf-tree-repo:hover {
  border-color: #7dd3fc;
  background: #f0f9ff;
}

.wf-tree-repo.selected {
  border-color: #0ea5e9;
  background: #f0f9ff;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.12);
}

.wf-tree-repo-main {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
  flex: 1;
  cursor: pointer;
}

.wf-tree-repo-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.wf-tree-repo-name {
  font-weight: 600;
  font-size: 0.84rem;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wf-tree-repo-url {
  font-size: 0.72rem;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 300px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.wf-tree-repo-extra {
  flex-shrink: 0;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}
</style>
