<script setup lang="ts">
import { ExternalLink, Pencil } from 'lucide-vue-next'
import DeleteActionButton from '@/components/DeleteActionButton.vue'
import LifecycleBadge from '@/components/management/LifecycleBadge.vue'
import type { Project } from '@/types/management'

defineProps<{
  items: Project[];
  loading: boolean;
  canManage: boolean;
}>()

const emit = defineEmits<{
  (e: 'open', project: Project): void;
  (e: 'edit', project: Project): void;
  (e: 'remove', project: Project): void;
}>()

const formatDate = (value: string | null): string => {
  if (!value) return '-';
  return value.slice(0, 10);
};
</script>

<template>
  <div class="mgmt-card">
    <table class="mgmt-table">
      <thead>
        <tr>
          <th>{{ $t('management.project.name') }}</th>
          <th>{{ $t('management.project.code') }}</th>
          <th>{{ $t('management.project.customer') }}</th>
          <th>{{ $t('management.project.organization') }}</th>
          <th>{{ $t('management.project.lifecycle_title') }}</th>
          <th>{{ $t('management.common.created_at') }}</th>
          <th>{{ $t('management.common.actions') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in items" :key="item.id" @click="emit('open', item)">
          <td>{{ item.name }}</td>
          <td class="mgmt-code-cell">{{ item.code }}</td>
          <td>{{ item.customer || '-' }}</td>
          <td>{{ item.organization || '-' }}</td>
          <td><LifecycleBadge :status="item.lifecycle_status" /></td>
          <td>{{ formatDate(item.created_at) }}</td>
          <td>
            <div class="row-actions" @click.stop>
              <button class="btn-ghost" :title="$t('common.open')" @click="emit('open', item)">
                <ExternalLink class="w-4 h-4" />
              </button>
              <button class="btn-ghost" :title="$t('common.edit')" :disabled="!canManage" @click="emit('edit', item)">
                <Pencil class="w-4 h-4" />
              </button>
              <DeleteActionButton
                mode="icon"
                :title="$t('common.delete')"
                :disabled="!canManage"
                @click.stop="emit('remove', item)"
              />
            </div>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="!loading && items.length === 0" class="mgmt-empty">{{ $t('management.common.empty') }}</div>
    <div v-if="loading" class="mgmt-empty">{{ $t('management.common.loading') }}</div>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.mgmt-code-cell {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.82rem;
  color: #475569;
}

.btn-ghost.w-4 {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}

.row-actions button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
