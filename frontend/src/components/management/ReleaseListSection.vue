<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { GitFork, Pencil, Plus } from 'lucide-vue-next'
import DeleteActionButton from '@/components/DeleteActionButton.vue'
import type { ProjectRelease, ReleaseStatus } from '@/types/management'

const props = defineProps<{
  releases: ProjectRelease[];
  canManage: boolean;
}>()

const emit = defineEmits<{
  (e: 'add'): void;
  (e: 'edit', release: ProjectRelease): void;
  (e: 'remove', release: ProjectRelease): void;
}>()

const { t } = useI18n()

const statusToneMap: Record<ReleaseStatus, string> = {
  DRAFT: 'gray',
  PUBLISHED: 'green',
  RETIRED: 'red',
}

const statusLabel = (status: ReleaseStatus): string =>
  t('management.project.release_status_' + status.toLowerCase())

const statusTone = (status: ReleaseStatus): string => statusToneMap[status] ?? 'gray'

const formatDate = (value: string | null): string => (value ? value.slice(0, 10) : '-')

const productVersionText = computed(() => {
  const map: Record<string, string> = {}
  for (const release of props.releases) {
    if (release.product_name && release.product_version_no) {
      map[release.id] = release.product_name + ' v' + release.product_version_no
    } else {
      map[release.id] = '-'
    }
  }
  return map
})
</script>

<template>
  <div class="mgmt-card">
    <div class="mgmt-card-header">
      <h3>{{ $t('management.project.releases_title') }}</h3>
      <button v-if="canManage" class="btn-primary" @click="emit('add')">
        <Plus class="w-4 h-4" /> {{ $t('management.project.add_release') }}
      </button>
    </div>

    <table v-if="releases.length > 0" class="mgmt-table">
      <thead>
        <tr>
          <th>{{ $t('management.project.release_no') }}</th>
          <th>{{ $t('management.project.release_name') }}</th>
          <th>{{ $t('management.project.release_product') }} + {{ $t('management.project.release_version') }}</th>
          <th>{{ $t('management.common.status') }}</th>
          <th>{{ $t('management.project.release_date') }}</th>
          <th>{{ $t('management.common.actions') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="release in releases" :key="release.id">
          <td class="mgmt-code-cell">{{ release.release_no }}</td>
          <td>{{ release.name }}</td>
          <td>{{ productVersionText[release.id] }}</td>
          <td>
            <span class="mgmt-status-pill" :class="statusTone(release.status)">
              {{ statusLabel(release.status) }}
            </span>
          </td>
          <td>{{ formatDate(release.release_date) }}</td>
          <td>
            <div class="row-actions">
              <span v-if="release.repos.length > 0" class="mgmt-repo-count" :title="$t('management.project.repos_title')">
                <GitFork class="w-4 h-4" />
                {{ release.repos.length }}
              </span>
              <button class="btn-ghost" :title="$t('common.edit')" :disabled="!canManage" @click="emit('edit', release)">
                <Pencil class="w-4 h-4" />
              </button>
              <DeleteActionButton
                mode="icon"
                :title="$t('common.delete')"
                :disabled="!canManage"
                @click.stop="emit('remove', release)"
              />
            </div>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-else class="mgmt-empty">
      {{ $t('management.project.no_releases') }}
      <div v-if="canManage" class="mgmt-empty-action">
        <button class="btn-secondary" @click="emit('add')">
          <Plus class="w-4 h-4" /> {{ $t('management.project.add_release') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.mgmt-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

.mgmt-card-header h3 {
  margin: 0;
}

.mgmt-code-cell {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.82rem;
  color: #475569;
}

.mgmt-repo-count {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.78rem;
  color: #64748b;
  margin-right: 0.25rem;
}

.mgmt-empty-action {
  margin-top: 0.75rem;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}

.row-actions button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-primary,
.btn-secondary {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}
</style>