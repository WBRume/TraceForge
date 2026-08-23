<!-- Workspace creation workflow: step 4 repository selection (baseline + custom, multi-select). -->
<script setup lang="ts">
import { computed } from 'vue'
import { Boxes, FolderCog, Tag, GitBranch } from 'lucide-vue-next'
import type { ProjectRepoSetItem } from '@/types/management'

const props = defineProps<{
  modelValue: string[]
  repos: ProjectRepoSetItem[]
  loading: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
}>()

const ootbRepos = computed(() => props.repos.filter((item) => item.repo_kind === 'OOTB'))
const customRepos = computed(() => props.repos.filter((item) => item.repo_kind === 'CUSTOM'))

const isSelected = (repoId: string): boolean => props.modelValue.includes(repoId)

const toggle = (repoId: string): void => {
  const selected = new Set(props.modelValue)
  if (selected.has(repoId)) {
    selected.delete(repoId)
  } else {
    selected.add(repoId)
  }
  emit('update:modelValue', [...selected])
}
</script>

<template>
  <div class="wf-step">
    <p class="mgmt-hint">{{ $t('workspace_create.repos_select_hint') }}</p>

    <div v-if="loading" class="mgmt-empty">{{ $t('management.common.loading') }}</div>

    <div v-else-if="repos.length === 0" class="mgmt-empty">
      {{ $t('workspace_create.no_repo_hint') }}
    </div>

    <div v-else>
      <div v-if="ootbRepos.length > 0" class="wf-repo-group">
        <div class="wf-group-title">
          <Boxes class="w-4 h-4" />
          <span>{{ $t('workspace_create.ootb_repos') }}（{{ ootbRepos.length }}）</span>
        </div>
        <label
          v-for="repo in ootbRepos"
          :key="repo.repository_id"
          class="wf-repo-row"
          :class="{ selected: isSelected(repo.repository_id) }"
        >
          <input
            type="checkbox"
            class="wf-checkbox"
            :checked="isSelected(repo.repository_id)"
            @change="toggle(repo.repository_id)"
          />
          <div class="wf-repo-info">
            <span class="wf-repo-name">{{ repo.repository_name }}</span>
            <span class="wf-repo-url">{{ repo.git_url }}</span>
          </div>
          <span class="wf-ref-badge" :class="repo.ref_type === 'TAG' ? 'tag' : 'branch'">
            <Tag v-if="repo.ref_type === 'TAG'" class="w-3.5 h-3.5" />
            <GitBranch v-else class="w-3.5 h-3.5" />
            {{ repo.ref_name }}
          </span>
        </label>
      </div>

      <div v-if="customRepos.length > 0" class="wf-repo-group">
        <div class="wf-group-title">
          <FolderCog class="w-4 h-4" />
          <span>{{ $t('workspace_create.custom_repos') }}（{{ customRepos.length }}）</span>
        </div>
        <label
          v-for="repo in customRepos"
          :key="repo.repository_id"
          class="wf-repo-row"
          :class="{ selected: isSelected(repo.repository_id) }"
        >
          <input
            type="checkbox"
            class="wf-checkbox"
            :checked="isSelected(repo.repository_id)"
            @change="toggle(repo.repository_id)"
          />
          <div class="wf-repo-info">
            <span class="wf-repo-name">{{ repo.repository_name }}</span>
            <span class="wf-repo-url">{{ repo.git_url }}</span>
          </div>
          <span class="wf-ref-badge" :class="repo.ref_type === 'TAG' ? 'tag' : 'branch'">
            <Tag v-if="repo.ref_type === 'TAG'" class="w-3.5 h-3.5" />
            <GitBranch v-else class="w-3.5 h-3.5" />
            {{ repo.ref_name }}
          </span>
        </label>
      </div>
    </div>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
<style scoped>
.wf-step {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}

.wf-repo-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.wf-group-title {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  font-size: 0.82rem;
  font-weight: 700;
  color: #334155;
  margin-top: 0.4rem;
}

.wf-repo-row {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  border: 1.5px solid #e2e8f0;
  border-radius: 10px;
  padding: 0.6rem 0.9rem 0.6rem 2.4rem;
  background: rgba(248, 250, 252, 0.7);
  cursor: pointer;
  transition: all 0.2s;
}

.wf-repo-row:hover {
  border-color: #7dd3fc;
  background: #f0f9ff;
}

.wf-repo-row.selected {
  border-color: #0ea5e9;
  background: #f0f9ff;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.12);
}

.wf-checkbox {
  position: absolute;
  left: 0.8rem;
  top: 50%;
  transform: translateY(-50%);
  width: 1rem;
  height: 1rem;
  accent-color: #0ea5e9;
}

.wf-repo-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.wf-repo-name {
  font-weight: 600;
  font-size: 0.88rem;
  color: #0f172a;
}

.wf-repo-url {
  font-size: 0.75rem;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 340px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.wf-ref-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.15rem 0.6rem;
  border-radius: 999px;
  font-size: 0.76rem;
  font-weight: 700;
  white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.wf-ref-badge.branch {
  color: #1d4ed8;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
}

.wf-ref-badge.tag {
  color: #15803d;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
}
</style>
