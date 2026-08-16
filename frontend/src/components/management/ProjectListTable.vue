<script setup lang="ts">
import { Eye, Pencil, Trash2 } from 'lucide-vue-next'
import IconActionButton from '@/components/management/IconActionButton.vue'
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
</script>

<template>
  <div class="mgmt-card">
    <table class="mgmt-table">
      <thead>
        <tr>
          <th>{{ $t('management.project.name') }}</th>
          <th>{{ $t('management.project.code') }}</th>
          <th>{{ $t('management.project.customer') }}</th>
          <th>{{ $t('management.project.lifecycle_title') }}</th>
          <th>{{ $t('management.project.products_title') }}</th>
          <th>{{ $t('management.common.actions') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in items" :key="item.id" class="mgmt-row-click" @click="emit('open', item)">
          <td>{{ item.name }}</td>
          <td class="mgmt-code-cell">{{ item.code }}</td>
          <td>{{ item.customer || '-' }}</td>
          <td><LifecycleBadge :status="item.lifecycle_status" /></td>
          <td>{{ item.product_count ?? '-' }}</td>
          <td>
            <div class="row-actions" @click.stop>
              <IconActionButton :icon="Eye" :title="$t('management.common.view')" @click="emit('open', item)" />
              <IconActionButton
                :icon="Pencil"
                :title="$t('management.common.edit')"
                :disabled="!canManage"
                @click="emit('edit', item)"
              />
              <IconActionButton
                :icon="Trash2"
                :title="$t('common.delete')"
                :disabled="!canManage"
                tone="danger"
                @click="emit('remove', item)"
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

.mgmt-row-click {
  cursor: pointer;
}
</style>