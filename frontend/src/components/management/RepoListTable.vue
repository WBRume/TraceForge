<script setup lang="ts">
import { Pencil, Trash2 } from 'lucide-vue-next'
import IconActionButton from '@/components/management/IconActionButton.vue'
import type { Repository } from '@/types/management'

withDefaults(defineProps<{
  items: Repository[];
  loading: boolean;
  canManage: boolean;
}>(), {
  loading: false,
})

const emit = defineEmits<{
  (e: 'edit', repo: Repository): void;
  (e: 'remove', repo: Repository): void;
}>()
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
          <th>{{ $t('management.repository.group') }}</th>
          <th>{{ $t('management.common.actions') }}</th>
        </tr>
      </thead>
      <tbody>
        <template v-if="loading">
          <tr>
            <td colspan="6" class="mgmt-empty">
              {{ $t('common.loading') }}
            </td>
          </tr>
        </template>
        <template v-else-if="!items.length">
          <tr>
            <td colspan="6" class="mgmt-empty">
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
            <td>{{ repo.group_name || '-' }}</td>
            <td>
              <div v-if="canManage" class="row-actions">
                <IconActionButton
                  :icon="Pencil"
                  :title="$t('management.repository.edit')"
                  @click="emit('edit', repo)"
                />
                <IconActionButton
                  :icon="Trash2"
                  :title="$t('common.delete')"
                  tone="danger"
                  @click="emit('remove', repo)"
                />
              </div>
              <span v-else class="text-muted">-</span>
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
</style>

<style scoped src="@/styles/management/management-shared.css"></style>
