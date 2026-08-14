<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { GitBranch, Tag, RefreshCw } from 'lucide-vue-next'
import { listRepositoryRefs } from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import type { RepoRef } from '@/types/management'

const props = defineProps<{
  repositoryId: string;
}>()

const { t } = useI18n()

const items = ref<RepoRef[]>([])
const lastSyncedAt = ref<string | null>(null)
const loading = ref(false)

const branches = computed(() => items.value.filter((item) => item.ref_type === 'BRANCH'))
const tags = computed(() => items.value.filter((item) => item.ref_type === 'TAG'))

const shortSha = (sha: string | null): string => (sha ? sha.slice(0, 8) : '')

const load = async () => {
  loading.value = true
  try {
    const res = await listRepositoryRefs(props.repositoryId)
    items.value = res.items ?? []
    lastSyncedAt.value = res.last_synced_at ?? null
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    loading.value = false
  }
}

watch(() => props.repositoryId, (id) => {
  if (id) {
    void load()
  }
}, { immediate: true })
</script>

<template>
  <div class="mgmt-refs-panel">
    <div class="mgmt-refs-header">
      <span class="mgmt-refs-synced">
        {{ $t('management.repository.last_synced_at') }}:
        <template v-if="lastSyncedAt">{{ lastSyncedAt }}</template>
        <span v-else class="text-muted">{{ $t('management.repository.never_synced') }}</span>
      </span>
      <button class="btn-ghost" :disabled="loading" @click="load">
        <RefreshCw class="mgmt-refs-refresh-icon" :class="{ 'is-spin': loading }" />
        {{ $t('common.refresh') }}
      </button>
    </div>

    <div v-if="loading" class="mgmt-refs-empty text-muted">
      {{ $t('common.loading') }}
    </div>

    <div v-else-if="!branches.length && !tags.length" class="mgmt-refs-empty text-muted">
      {{ $t('management.repository.refs_empty') }}
    </div>

    <template v-else>
      <div class="mgmt-refs-group">
        <div class="mgmt-refs-group-title">
          <GitBranch class="mgmt-refs-group-icon" />
          {{ $t('management.repository.refs_branch') }}
          <span class="mgmt-refs-badge">{{ branches.length }}</span>
        </div>
        <ul v-if="branches.length" class="mgmt-refs-list">
          <li v-for="ref in branches" :key="ref.id" class="mgmt-refs-item">
            <span class="mgmt-refs-name">{{ ref.ref_name }}</span>
            <span v-if="ref.ref_sha" class="mgmt-refs-sha">{{ shortSha(ref.ref_sha) }}</span>
          </li>
        </ul>
      </div>

      <div class="mgmt-refs-group">
        <div class="mgmt-refs-group-title">
          <Tag class="mgmt-refs-group-icon" />
          {{ $t('management.repository.refs_tag') }}
          <span class="mgmt-refs-badge">{{ tags.length }}</span>
        </div>
        <ul v-if="tags.length" class="mgmt-refs-list">
          <li v-for="ref in tags" :key="ref.id" class="mgmt-refs-item">
            <span class="mgmt-refs-name">{{ ref.ref_name }}</span>
            <span v-if="ref.ref_sha" class="mgmt-refs-sha">{{ shortSha(ref.ref_sha) }}</span>
          </li>
        </ul>
      </div>
    </template>
  </div>
</template>

<style scoped>
.mgmt-refs-panel {
  padding: 0.5rem 0.25rem;
}

.mgmt-refs-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.5rem 0.9rem 0.75rem;
  border-bottom: 1px solid #e2e8f0;
}

.mgmt-refs-synced {
  font-size: 0.78rem;
  color: #64748b;
}

.mgmt-refs-refresh-icon {
  width: 0.9rem;
  height: 0.9rem;
}

.mgmt-refs-refresh-icon.is-spin {
  animation: mgmt-refs-spin 1s linear infinite;
}

.mgmt-refs-empty {
  padding: 1rem 0.9rem;
  font-size: 0.82rem;
}

.mgmt-refs-group {
  margin-top: 0.5rem;
}

.mgmt-refs-group-title {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0 0.9rem;
  font-size: 0.78rem;
  font-weight: 700;
  color: #334155;
}

.mgmt-refs-group-icon {
  width: 0.85rem;
  height: 0.85rem;
  color: #64748b;
}

.mgmt-refs-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 1.2rem;
  padding: 0.05rem 0.4rem;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 700;
  color: #1d4ed8;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
}

.mgmt-refs-list {
  list-style: none;
  margin: 0.25rem 0 0;
  padding: 0.25rem 0.9rem;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.mgmt-refs-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.2rem 0;
  font-size: 0.8rem;
}

.mgmt-refs-name {
  color: #334155;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mgmt-refs-sha {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.75rem;
  color: #94a3b8;
}

@keyframes mgmt-refs-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>

<style scoped src="@/styles/management/management-shared.css"></style>