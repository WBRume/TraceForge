<!-- Workspace creation workflow: step 4 repository selection (OOTB / custom groups as tree). -->
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { GitBranch, Tag } from 'lucide-vue-next'
import RepoSelectTree from './RepoSelectTree.vue'
import type { RepoSelectTreeNode, RepoSelectTreeRepo } from './RepoSelectTree.vue'
import type { ProjectRepoSetItem } from '@/types/management'

const props = defineProps<{
  modelValue: string[]
  repos: ProjectRepoSetItem[]
  loading: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
}>()

const { t } = useI18n()

const toTreeRepo = (item: ProjectRepoSetItem): RepoSelectTreeRepo => ({
  id: item.repository_id,
  name: item.repository_name,
  git_url: item.git_url,
  repo_type: item.repo_type,
  ref_type: item.ref_type,
  ref_name: item.ref_name,
})

const nodes = computed<RepoSelectTreeNode[]>(() => {
  const nodes: RepoSelectTreeNode[] = []
  const ootb = props.repos.filter((item) => item.repo_kind === 'OOTB')
  const custom = props.repos.filter((item) => item.repo_kind === 'CUSTOM')
  if (ootb.length > 0) {
    nodes.push({
      key: 'ootb',
      name: t('workspace_create.ootb_repos'),
      repos: ootb.map(toTreeRepo),
      children: [],
    })
  }
  if (custom.length > 0) {
    nodes.push({
      key: 'custom',
      name: t('workspace_create.custom_repos'),
      repos: custom.map(toTreeRepo),
      children: [],
    })
  }
  return nodes
})

const proxySelected = computed({
  get: () => props.modelValue,
  set: (value: string[]) => emit('update:modelValue', value),
})
</script>

<template>
  <div class="wf-step">
    <p class="mgmt-hint">{{ $t('workspace_create.repos_select_hint') }}</p>

    <div v-if="loading" class="mgmt-empty">{{ $t('management.common.loading') }}</div>

    <div v-else-if="repos.length === 0" class="mgmt-empty">
      {{ $t('workspace_create.no_repo_hint') }}
    </div>

    <RepoSelectTree v-else v-model="proxySelected" :nodes="nodes">
      <template #repo-extra="{ repo }">
        <span class="wf-ref-badge" :class="repo.ref_type === 'TAG' ? 'tag' : 'branch'">
          <Tag v-if="repo.ref_type === 'TAG'" class="w-3.5 h-3.5" />
          <GitBranch v-else class="w-3.5 h-3.5" />
          {{ repo.ref_name }}
        </span>
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

.w-3\.5 {
  width: 0.875rem;
  height: 0.875rem;
}
</style>
