<!--
ProductListTable: product rows with open / edit / delete actions.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { Eye, Pencil, Loader2 } from 'lucide-vue-next'
import DeleteActionButton from '@/components/DeleteActionButton.vue'
import type { Product } from '@/types/management'

const props = defineProps<{
  items: Product[]
  loading: boolean
  canManage: boolean
}>()

const emit = defineEmits<{
  (e: 'open', product: Product): void
  (e: 'edit', product: Product): void
  (e: 'remove', product: Product): void
}>()

const statusPillClass = computed(() => (status: string) => {
  return status === 'ACTIVE' ? 'green' : 'gray'
})

const formatDate = (value: string) => {
  if (!value) return '-'
  return value.replace('T', ' ').slice(0, 16)
}
</script>

<template>
  <div class="mgmt-card">
    <div v-if="loading" class="mgmt-empty">
      <Loader2 class="w-4 h-4 spin" />
      <span>{{ $t('management.common.loading') }}</span>
    </div>

    <div v-else-if="items.length === 0" class="mgmt-empty">
      {{ $t('management.common.empty') }}
    </div>

    <table v-else class="mgmt-table">
      <thead>
        <tr>
          <th>{{ $t('management.common.name') }}</th>
          <th>{{ $t('management.common.code') }}</th>
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
          <td>{{ item.product_line || '-' }}</td>
          <td>
            <span class="mgmt-status-pill" :class="statusPillClass(item.status)">
              {{ item.status === 'ACTIVE'
                ? $t('management.product.status_active')
                : $t('management.product.status_archived') }}
            </span>
          </td>
          <td>{{ formatDate(item.created_at) }}</td>
          <td @click.stop>
            <div class="row-actions">
              <button class="btn-ghost" :title="$t('common.open')" @click="emit('open', item)">
                <Eye class="w-4 h-4" />
              </button>
              <button
                class="btn-ghost"
                :title="$t('common.edit')"
                :disabled="!canManage"
                @click="emit('edit', item)"
              >
                <Pencil class="w-4 h-4" />
              </button>
              <DeleteActionButton
                mode="icon"
                :title="$t('common.delete')"
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

<style scoped>
.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.w-4 {
  width: 1rem;
  height: 1rem;
}
</style>
