<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { GitFork, Pencil, Plus, Trash2 } from 'lucide-vue-next'
import IconActionButton from '@/components/management/IconActionButton.vue'
import type { ProjectRelease, ReleaseStatus } from '@/types/management'

defineProps<{
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
          <th>{{ $t('management.project.release_product') }}</th>
          <th>{{ $t('management.common.status') }}</th>
          <th>{{ $t('management.project.release_date') }}</th>
          <th>{{ $t('management.project.repos_title') }}</th>
          <th>{{ $t('management.common.actions') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="release in releases" :key="release.id">
          <td class="mgmt-code-cell">{{ release.release_no }}</td>
          <td>{{ release.name }}</td>
          <td>{{ release.product_name || '-' }}</td>
          <td>
            <span class="mgmt-status-pill" :class="statusTone(release.status)">
              {{ statusLabel(release.status) }}
            </span>
          </td>
          <td>{{ formatDate(release.release_date) }}</td>
          <td>
            <span class="mgmt-repo-count">
              <GitFork class="w-4 h-4" />
              {{ release.repos.length }}
            </span>
          </td>
          <td>
            <div class="row-actions">
              <IconActionButton
                :icon="Pencil"
                :title="$t('management.common.edit')"
                :disabled="!canManage"
                @click="emit('edit', release)"
              />
              <IconActionButton
                :icon="Trash2"
                :title="$t('common.delete')"
                :disabled="!canManage"
                tone="danger"
                @click="emit('remove', release)"
              />
            </div>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-else class="mgmt-empty">{{ $t('management.project.no_releases') }}</div>
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
}

.w-4 {
  width: 1rem;
  height: 1rem;
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}
</style>