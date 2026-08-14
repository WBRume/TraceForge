<!-- Repository group tree picker: checking a group selects all repositories
     inside it. Emits the selected repository ids. -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Folder, Search } from 'lucide-vue-next'
import { getRepoGroupTree } from '@/services/managementApi'
import type { RepoGroupRepo, RepoGroupTreeNode } from '@/types/management'

const props = defineProps<{
  show: boolean
  excludeIds?: string[]
  modelValue: string[]
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
  (e: 'close'): void
}>()

const tree = ref<RepoGroupTreeNode[]>([])
const loading = ref(false)
const keyword = ref('')

const excluded = computed(() => new Set(props.excludeIds || []))

const load = async () => {
  loading.value = true
  try {
    const res = await getRepoGroupTree()
    tree.value = res.items || []
  } finally {
    loading.value = false
  }
}

watch(
  () => props.show,
  (visible) => {
    if (visible) void load()
  },
  { immediate: true },
)

const toggleRepo = (repositoryId: string) => {
  const selected = new Set(props.modelValue)
  if (selected.has(repositoryId)) {
    selected.delete(repositoryId)
  } else {
    selected.add(repositoryId)
  }
  emit('update:modelValue', [...selected])
}

const toggleGroup = (node: RepoGroupTreeNode) => {
  const repos = collectRepos(node)
  const allSelected = repos.length > 0 && repos.every((repo) => props.modelValue.includes(repo.id))
  const selected = new Set(props.modelValue)
  for (const repo of repos) {
    if (allSelected) {
      selected.delete(repo.id)
    } else if (!excluded.value.has(repo.id)) {
      selected.add(repo.id)
    }
  }
  emit('update:modelValue', [...selected])
}

const collectRepos = (node: RepoGroupTreeNode): RepoGroupRepo[] => {
  const repos: RepoGroupRepo[] = [...node.repositories]
  for (const child of node.children) {
    repos.push(...collectRepos(child))
  }
  return repos
}

const groupChecked = (node: RepoGroupTreeNode): boolean | 'indeterminate' => {
  const repos = collectRepos(node).filter((repo) => !excluded.value.has(repo.id))
  if (repos.length === 0) return false
  const selectedCount = repos.filter((repo) => props.modelValue.includes(repo.id)).length
  if (selectedCount === 0) return false
  if (selectedCount === repos.length) return true
  return 'indeterminate'
}

const matchesKeyword = (repo: RepoGroupRepo): boolean => {
  const normalized = keyword.value.trim().toLowerCase()
  if (!normalized) return true
  return repo.name.toLowerCase().includes(normalized)
}

const visibleRepos = (node: RepoGroupTreeNode): RepoGroupRepo[] => (
  node.repositories.filter((repo) => matchesKeyword(repo))
)
</script>

<template>
  <div
    v-if="show"
    class="mgmt-modal-overlay"
    @pointerdown.self="emit('close')"
  >
    <section class="mgmt-modal group-picker-dialog" role="dialog" aria-modal="true">
      <header class="group-picker-header">
        <h3>{{ $t('management.product.select_repos_hint') }}</h3>
      </header>

      <div class="group-picker-toolbar">
        <div class="mgmt-search-wrap">
          <Search class="w-4 h-4 search-icon" />
          <input v-model="keyword" type="text" class="mgmt-search" :placeholder="$t('management.common.search_placeholder')" />
        </div>
      </div>

      <div v-if="loading" class="mgmt-empty">{{ $t('management.common.loading') }}</div>

      <div v-else class="group-picker-tree">
        <template v-for="node in tree" :key="node.id ?? 'unassigned'">
          <div class="group-node">
            <label class="group-row" :class="{ unassigned: node.id === null }">
              <input
                type="checkbox"
                :checked="groupChecked(node) === true"
                :indeterminate="groupChecked(node) === 'indeterminate'"
                @change="toggleGroup(node)"
              />
              <Folder class="w-4 h-4" />
              <span class="group-name">{{ node.id === null ? $t('management.repo_group.unassigned') : node.name }}</span>
            </label>
            <div class="group-repos">
              <label
                v-for="repo in visibleRepos(node)"
                :key="repo.id"
                class="repo-row"
                :class="{ excluded: excluded.has(repo.id) }"
              >
                <input
                  type="checkbox"
                  :checked="modelValue.includes(repo.id)"
                  :disabled="excluded.has(repo.id)"
                  @change="toggleRepo(repo.id)"
                />
                <span class="repo-name">{{ repo.name }}</span>
                <span class="repo-tag" :class="repo.repo_type === 'CUSTOM' ? 'custom' : 'ootb'">{{ repo.repo_type }}</span>
              </label>
            </div>
          </div>
          <template v-for="child in node.children" :key="child.id ?? child.name">
            <div class="group-node child">
              <label class="group-row">
                <input
                  type="checkbox"
                  :checked="groupChecked(child) === true"
                  :indeterminate="groupChecked(child) === 'indeterminate'"
                  @change="toggleGroup(child)"
                />
                <Folder class="w-4 h-4" />
                <span class="group-name">{{ child.name }}</span>
              </label>
              <div class="group-repos">
                <label v-for="repo in visibleRepos(child)" :key="repo.id" class="repo-row" :class="{ excluded: excluded.has(repo.id) }">
                  <input
                    type="checkbox"
                    :checked="modelValue.includes(repo.id)"
                    :disabled="excluded.has(repo.id)"
                    @change="toggleRepo(repo.id)"
                  />
                  <span class="repo-name">{{ repo.name }}</span>
                  <span class="repo-tag" :class="repo.repo_type === 'CUSTOM' ? 'custom' : 'ootb'">{{ repo.repo_type }}</span>
                </label>
              </div>
            </div>
          </template>
        </template>
      </div>

      <footer class="mgmt-modal-actions">
        <button type="button" class="btn-primary" @click="emit('close')">
          {{ $t('common.confirm') }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
<style scoped>
.group-picker-dialog {
  max-width: 560px;
}

.group-picker-header h3 {
  font-size: 0.95rem;
}

.group-picker-toolbar {
  margin-bottom: 0.75rem;
}

.mgmt-search-wrap {
  position: relative;
}

.search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: #94a3b8;
}

.mgmt-search-wrap .mgmt-search {
  width: 100%;
  padding-left: 2rem;
}

.group-picker-tree {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  max-height: 380px;
  overflow-y: auto;
}

.group-node {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 0.5rem 0.6rem;
  background: rgba(248, 250, 252, 0.6);
}

.group-node.child {
  margin-left: 1.1rem;
}

.group-row {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  font-weight: 600;
  font-size: 0.86rem;
  color: #334155;
  cursor: pointer;
}

.group-row.unassigned {
  color: #64748b;
}

.group-repos {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  margin-top: 0.4rem;
  padding-left: 0.4rem;
}

.repo-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.82rem;
  color: #475569;
  cursor: pointer;
  padding: 0.2rem 0.3rem;
  border-radius: 6px;
}

.repo-row:hover {
  background: rgba(14, 165, 233, 0.06);
}

.repo-row.excluded {
  opacity: 0.5;
  cursor: not-allowed;
}

.repo-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.repo-tag {
  font-size: 0.68rem;
  font-weight: 700;
  padding: 0.05rem 0.4rem;
  border-radius: 4px;
}

.repo-tag.ootb {
  color: #1d4ed8;
  background: #eff6ff;
}

.repo-tag.custom {
  color: #92400e;
  background: #fffbeb;
}
</style>
