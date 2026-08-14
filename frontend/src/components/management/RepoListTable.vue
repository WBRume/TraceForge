<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { GitFork, GitBranch, Tag, RefreshCw, Pencil } from 'lucide-vue-next'
import DeleteActionButton from '@/components/DeleteActionButton.vue'
import type { Repository } from '@/types/management'

const props = withDefaults(defineProps<{
  items: Repository[];
  loading: boolean;
  canManage: boolean;
  expandedRepoId: string | null;
}>(), {
  loading: false,
  expandedRepoId: null,
})

const emit = defineEmits<{
  (e: 'edit', repo: Repository): void;
  (e: 'remove', repo: Repository): void;
  (e: 'toggleRefs', repo: Repository): void;
  (e: 'sync', repo: Repository): void;
}>()

const { t } = useI18n()

const syncedAt = (repo: Repository): string =>
  repo.last_synced_at ?? t('management.repository.never_synced')
</script>

<template>
  <div class="mgmt-card">
    <table class="mgmt-table">
      <thead>
        <tr>
          <th>{{ $t('management.common.name') }}</th>
          <th>{{ $t('management.repository.git_url') }}</th>
          <th>{{ $t('management.repository.repo_type') }}</th>
          <th>{{ $t('management.repository.default_branch') }}</th>
          <th>{{ $t('management.repository.refs_branch') }}</th>
          <th>{{ $t('management.repository.refs_tag') }}</th>
          <th>{{ $t('management.repository.last_synced_at') }}</th>
          <th>{{ $t('management.common.actions') }}</th>
        </tr>
      </thead>
      <tbody>
        <template v-if="loading">
          <tr>
            <td colspan="8" class="mgmt-empty">
              {{ $t('common.loading') }}
            </td>
          </tr>
        </template>
        <template v-else-if="!items.length">
          <tr>
            <td colspan="8" class="mgmt-empty">
              {{ $t('management.common.empty') }}
            </td>
          </tr>
        </template>
        <template v-else v-for="repo in items" :key="repo.id">
          <tr>
            <td class="mgmt-repo-name">{{ repo.name }}</td>
            <td class="mgmt-repo-url">{{ repo.git_url }}</td>
            <td>
              <span class="mgmt-tag" :class="repo.repo_type === 'OOTB' ? 'ootb' : 'custom'">
                {{ repo.repo_type === 'OOTB'
                  ? $t('management.repository.type_ootb')
                  : $t('management.repository.type_custom') }}
              </span>
            </td>
            <td>{{ repo.default_branch || '-' }}</td>
            <td>
              <span class="mgmt-count-cell">
                <GitBranch class="mgmt-count-icon" />
                {{ repo.branch_count }}
              </span>
            </td>
            <td>
              <span class="mgmt-count-cell">
                <Tag class="mgmt-count-icon" />
                {{ repo.tag_count }}
              </span>
            </td>
            <td class="text-muted">{{ syncedAt(repo) }}</td>
            <td>
              <div class="row-actions">
                <button
                  class="btn-ghost mgmt-icon-btn"
                  :class="{ 'is-active': repo.id === expandedRepoId }"
                  :title="$t('common.expand')"
                  @click="emit('toggleRefs', repo)"
                >
                  <GitFork class="mgmt-icon-btn-icon" />
                </button>
                <button
                  v-if="canManage"
                  class="btn-ghost mgmt-icon-btn"
                  :title="$t('management.repository.sync')"
                  @click="emit('sync', repo)"
                >
                  <RefreshCw class="mgmt-icon-btn-icon" />
                </button>
                <button
                  v-if="canManage"
                  class="btn-ghost mgmt-icon-btn"
                  :title="$t('management.repository.edit')"
                  @click="emit('edit', repo)"
                >
                  <Pencil class="mgmt-icon-btn-icon" />
                </button>
                <DeleteActionButton
                  v-if="canManage"
                  mode="icon"
                  :title="$t('common.delete')"
                  @click.stop="emit('remove', repo)"
                />
              </div>
            </td>
          </tr>
          <tr v-if="expandedRepoId === repo.id" class="mgmt-expanded-row">
            <td colspan="8">
              <slot name="expanded" :repo="repo" />
            </td>
          </tr>
        </template>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.mgmt-repo-name {
  font-weight: 600;
  color: #1e293b;
}

.mgmt-repo-url {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.8rem;
  color: #64748b;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mgmt-count-cell {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
}

.mgmt-count-icon {
  width: 0.9rem;
  height: 0.9rem;
  color: #64748b;
}

.mgmt-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.35rem;
  border-radius: 8px;
}

.mgmt-icon-btn.is-active {
  color: #0ea5e9;
  background: rgba(14, 165, 233, 0.12);
}

.mgmt-icon-btn-icon {
  width: 0.9rem;
  height: 0.9rem;
}

.mgmt-expanded-row td {
  background: rgba(14, 165, 233, 0.04);
  padding: 0.25rem 0.9rem;
}
</style>

<style scoped src="@/styles/management/management-shared.css"></style>