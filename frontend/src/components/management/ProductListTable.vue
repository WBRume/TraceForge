<!--
ProductListTable: product rows with open / edit / delete actions.
-->
<script setup lang="ts">
import { Eye, Pencil, Trash2 } from 'lucide-vue-next';
import IconActionButton from '@/components/management/IconActionButton.vue';
import type { Product } from '@/types/management';

defineProps<{
  items: Product[];
  loading: boolean;
  canManage: boolean;
}>();

const emit = defineEmits<{
  (e: 'open', product: Product): void;
  (e: 'edit', product: Product): void;
  (e: 'remove', product: Product): void;
}>();

const formatDate = (value: string): string => {
  if (!value) return '-';
  return value.replace('T', ' ').slice(0, 16);
};
</script>

<template>
  <div class="mgmt-card">
    <div v-if="loading" class="mgmt-empty">{{ $t('management.common.loading') }}</div>

    <div v-else-if="items.length === 0" class="mgmt-empty">
      {{ $t('management.common.empty') }}
    </div>

    <table v-else class="mgmt-table">
      <thead>
        <tr>
          <th>{{ $t('management.common.name') }}</th>
          <th>{{ $t('management.common.code') }}</th>
          <th>{{ $t('management.product.version_no') }}</th>
          <th>{{ $t('management.product.product_line') }}</th>
          <th>{{ $t('management.common.status') }}</th>
          <th>{{ $t('management.common.created_at') }}</th>
          <th>{{ $t('management.common.actions') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in items" :key="item.id" @click="emit('open', item)">
          <td>{{ item.name }}</td>
          <td>{{ item.code }}</td>
          <td>{{ item.version_no || '-' }}</td>
          <td>{{ item.product_line || '-' }}</td>
          <td>
            <span
              class="mgmt-status-pill"
              :class="item.status === 'ACTIVE' ? 'green' : 'gray'"
            >
              {{ item.status === 'ACTIVE'
                ? $t('management.product.status_active')
                : $t('management.product.status_archived') }}
            </span>
          </td>
          <td>{{ formatDate(item.created_at) }}</td>
          <td @click.stop>
            <div class="row-actions">
              <IconActionButton
                :icon="Eye"
                :title="$t('management.common.view')"
                @click="emit('open', item)"
              />
              <IconActionButton
                :icon="Pencil"
                :title="$t('management.common.edit')"
                :disabled="!canManage"
                @click="emit('edit', item)"
              />
              <IconActionButton
                :icon="Trash2"
                :title="$t('management.common.delete')"
                tone="danger"
                :disabled="!canManage"
                @click="emit('remove', item)"
              />
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
