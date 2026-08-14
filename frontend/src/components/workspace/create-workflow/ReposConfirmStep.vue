<!-- Workspace creation workflow: step 3 repository set confirmation. -->
<script setup lang="ts">
import { computed } from 'vue'
import { Boxes, FolderCog } from 'lucide-vue-next'
import BranchSelect from '@/components/management/BranchSelect.vue'
import type { ProjectRepoSetItem } from '@/types/management'

const props = defineProps<{
  repos: ProjectRepoSetItem[]
  overrides: Record<string, string>
  loading: boolean
}>()

const emit = defineEmits<{
  (e: 'update:overrides', value: Record<string, string>): void
}>()

const ootbRepos = computed(() => props.repos.filter((item) => item.repo_kind === 'OOTB'))
const customRepos = computed(() => props.repos.filter((item) => item.repo_kind === 'CUSTOM'))

const branchFor = (repo: ProjectRepoSetItem) => {
  return props.overrides[repo.repository_id] || repo.branch_name
}

const onBranchChange = (repositoryId: string, branch: string) => {
  const next = { ...props.overrides, [repositoryId]: branch }
  emit('update:overrides', next)
}
</script>

<template>
  <div class="wf-step">
    <div v-if="loading" class="mgmt-empty">{{ $t('management.common.loading') }}</div>

    <div v-else-if="repos.length === 0" class="mgmt-empty">
      {{ $t('workspace_create.no_repo_hint') }}
    </div>

    <div v-else>
      <p class="mgmt-hint">{{ $t('workspace_create.repos_hint') }}</p>

      <div v-if="ootbRepos.length > 0" class="wf-repo-group">
        <div class="wf-group-title">
          <Boxes class="w-4 h-4" />
          <span>{{ $t('workspace_create.ootb_repos') }}</span>
        </div>
        <div v-for="repo in ootbRepos" :key="repo.repository_id" class="wf-repo-row">
          <div class="wf-repo-info">
            <span class="wf-repo-name">{{ repo.repository_name }}</span>
            <span class="wf-repo-url">{{ repo.git_url }}</span>
          </div>
          <div class="wf-repo-branch">
            <BranchSelect
              :model-value="branchFor(repo)"
              :repository-id="repo.repository_id"
              @update:model-value="onBranchChange(repo.repository_id, $event)"
            />
          </div>
        </div>
      </div>

      <div v-if="customRepos.length > 0" class="wf-repo-group">
        <div class="wf-group-title">
          <FolderCog class="w-4 h-4" />
          <span>{{ $t('workspace_create.custom_repos') }}</span>
        </div>
        <div v-for="repo in customRepos" :key="repo.repository_id" class="wf-repo-row">
          <div class="wf-repo-info">
            <span class="wf-repo-name">{{ repo.repository_name }}</span>
            <span class="wf-repo-url">{{ repo.git_url }}</span>
          </div>
          <div class="wf-repo-branch">
            <BranchSelect
              :model-value="branchFor(repo)"
              :repository-id="repo.repository_id"
              @update:model-value="onBranchChange(repo.repository_id, $event)"
            />
          </div>
        </div>
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
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 0.6rem 0.9rem;
  background: rgba(248, 250, 252, 0.7);
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

.wf-repo-branch {
  width: 260px;
  flex-shrink: 0;
}
</style>
