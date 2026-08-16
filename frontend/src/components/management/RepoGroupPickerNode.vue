<!--
RepoGroupPickerNode: recursive node of the repository group picker tree.
Checking a group selects all repositories inside it (including descendants).
-->
<script setup lang="ts">
import { computed } from 'vue'
import { Folder } from 'lucide-vue-next'
import type { RepoGroupRepo, RepoGroupTreeNode } from '@/types/management'

const props = defineProps<{
  node: RepoGroupTreeNode;
  depth: number;
  excludeIds: string[];
  modelValue: string[];
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void;
}>()

const excluded = computed(() => new Set(props.excludeIds))

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

const toggleRepo = (repositoryId: string) => {
  const selected = new Set(props.modelValue)
  if (selected.has(repositoryId)) {
    selected.delete(repositoryId)
  } else {
    selected.add(repositoryId)
  }
  emit('update:modelValue', [...selected])
}

const indentStyle = computed(() => ({
  marginLeft: props.depth > 0 ? `${props.depth * 1.1}rem` : '0',
}))
</script>

<template>
  <div class="group-node" :style="indentStyle">
    <label class="group-row" :class="{ unassigned: node.id === null }">
      <input
        type="checkbox"
        :checked="groupChecked(node) === true"
        :indeterminate="groupChecked(node) === 'indeterminate'"
        @change="toggleGroup(node)"
      />
      <Folder class="w-4 h-4" />
      <span class="group-name">
        {{ node.id === null ? $t('management.repo_group.unassigned') : node.name }}
      </span>
    </label>
    <div class="group-repos">
      <label
        v-for="repo in node.repositories"
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
        <span class="repo-tag" :class="repo.repo_type === 'CUSTOM' ? 'custom' : 'ootb'">
          {{ repo.repo_type }}
        </span>
      </label>
    </div>

    <RepoGroupPickerNode
      v-for="child in node.children"
      :key="child.id ?? child.name"
      :node="child"
      :depth="depth + 1"
      :exclude-ids="excludeIds"
      :model-value="modelValue"
      @update:model-value="emit('update:modelValue', $event)"
    />
  </div>
</template>

<style scoped>
.group-node {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 0.5rem 0.6rem;
  background: rgba(248, 250, 252, 0.6);
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

.w-4 {
  width: 1rem;
  height: 1rem;
}
</style>
