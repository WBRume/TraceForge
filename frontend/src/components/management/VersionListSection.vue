<!--
VersionListSection: list of product versions with status, release date,
binding count and per-row actions.
-->
<script setup lang="ts">
import { GitBranch, Pencil, Plus } from 'lucide-vue-next'
import DeleteActionButton from '@/components/DeleteActionButton.vue'
import type { ProductVersion } from '@/types/management'

const props = defineProps<{
  versions: ProductVersion[]
  canManage: boolean
}>()

const emit = defineEmits<{
  (e: 'add'): void
  (e: 'edit', version: ProductVersion): void
  (e: 'remove', version: ProductVersion): void
  (e: 'toggleBindings', version: ProductVersion): void
}>()

const pillClass = (status: string) => {
  if (status === 'PLANNED') return 'blue'
  if (status === 'ACTIVE') return 'green'
  return 'gray'
}

const statusLabel = (status: string) => {
  if (status === 'PLANNED') return 'management.product.version_status_planned'
  if (status === 'ACTIVE') return 'management.product.version_status_active'
  return 'management.product.version_status_eol'
}

const formatDate = (value: string | null) => {
  if (!value) return '-'
  return value.slice(0, 10)
}
</script>

<template>
  <div class="mgmt-card">
    <div class="mgmt-section-head">
      <h3>{{ $t('management.product.versions_title') }}</h3>
      <button v-if="canManage" class="btn-primary" @click="emit('add')">
        <Plus class="w-4 h-4" />
        {{ $t('management.product.add_version') }}
      </button>
    </div>

    <div v-if="versions.length === 0" class="mgmt-empty">
      <p>{{ $t('management.product.no_versions') }}</p>
      <button v-if="canManage" class="btn-secondary" @click="emit('add')">
        {{ $t('management.product.add_version') }}
      </button>
    </div>

    <table v-else class="mgmt-table">
      <thead>
        <tr>
          <th>{{ $t('management.product.version_no') }}</th>
          <th>{{ $t('management.common.status') }}</th>
          <th>{{ $t('management.product.release_date') }}</th>
          <th>{{ $t('management.product.bindings_title') }}</th>
          <th>{{ $t('management.common.actions') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="version in versions" :key="version.id">
          <td>{{ version.version_no }}</td>
          <td>
            <span class="mgmt-status-pill" :class="pillClass(version.status)">
              {{ $t(statusLabel(version.status)) }}
            </span>
          </td>
          <td>{{ formatDate(version.release_date) }}</td>
          <td>{{ version.repo_bindings.length }}</td>
          <td>
            <div class="row-actions">
              <button class="btn-ghost" :title="$t('management.product.bindings_title')" @click="emit('toggleBindings', version)">
                <GitBranch class="w-4 h-4" />
              </button>
              <button class="btn-ghost" :title="$t('common.edit')" :disabled="!canManage" @click="emit('edit', version)">
                <Pencil class="w-4 h-4" />
              </button>
              <DeleteActionButton
                mode="icon"
                :title="$t('common.delete')"
                :disabled="!canManage"
                @click="emit('remove', version)"
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
.mgmt-section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}

.mgmt-section-head h3 {
  margin: 0;
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}
</style>
