<!--
ProductBaseReposPanel: changeable product-level repository pool.
Versions can inherit this pool when they are created; each version then binds
its own branches/tags and may add version-specific repositories.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { GitBranch, Plus, Trash2 } from 'lucide-vue-next'
import IconActionButton from '@/components/management/IconActionButton.vue'
import RepoGroupPicker from '@/components/management/RepoGroupPicker.vue'
import { addProductBaseRepo, removeProductBaseRepo } from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import type { ProductDetail } from '@/types/management'

const props = defineProps<{
  product: ProductDetail | null
  canManage: boolean
}>()

const emit = defineEmits<{
  (e: 'changed'): void
}>()

const { t } = useI18n()

const pickerVisible = ref(false)
const selectedRepoIds = ref<string[]>([])
const saving = ref(false)
const removingRepoId = ref<string | null>(null)

const allowedRepoTypes = computed(() =>
  props.product?.product_type === 'CUSTOM' ? ['CUSTOM'] : ['OOTB']
)

const keyword = ref('')
const page = ref(1)
const pageSize = 10

const filteredRepos = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  const repos = props.product?.base_repos ?? []
  if (!kw) return repos
  return repos.filter((repo) =>
    String(repo.repository_name || '').toLowerCase().includes(kw)
    || String(repo.git_url || '').toLowerCase().includes(kw)
  )
})

const totalPages = computed(() => Math.max(1, Math.ceil(filteredRepos.value.length / pageSize)))

const pagedRepos = computed(() => {
  const start = (page.value - 1) * pageSize
  return filteredRepos.value.slice(start, start + pageSize)
})

watch(keyword, () => {
  page.value = 1
})

const goPage = (delta: number): void => {
  const next = page.value + delta
  if (next < 1 || next > totalPages.value) return
  page.value = next
}

const openPicker = () => {
  selectedRepoIds.value = []
  pickerVisible.value = true
}

const cancelPicker = () => {
  pickerVisible.value = false
  selectedRepoIds.value = []
}

const confirmPicker = async () => {
  pickerVisible.value = false
  if (!props.product || selectedRepoIds.value.length === 0) return
  saving.value = true
  try {
    for (const repositoryId of selectedRepoIds.value) {
      await addProductBaseRepo(props.product.id, repositoryId)
    }
    selectedRepoIds.value = []
    ElMessage.success(t('common.success'))
    emit('changed')
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    saving.value = false
  }
}

const confirmRemove = async (repositoryId: string) => {
  if (!props.product) return
  removingRepoId.value = repositoryId
  try {
    await removeProductBaseRepo(props.product.id, repositoryId)
    ElMessage.success(t('common.success'))
    emit('changed')
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    removingRepoId.value = null
  }
}
</script>

<template>
  <div class="mgmt-card">
    <div class="mgmt-section-head">
      <h3>{{ $t('management.product.base_repos_title') }}</h3>
      <button v-if="canManage" class="btn-secondary" :disabled="saving" @click="openPicker">
        <Plus class="w-4 h-4" /> {{ $t('management.product.add_base_repo') }}
      </button>
    </div>

    <p class="mgmt-hint">{{ $t('management.product.base_repos_hint') }}</p>

    <div v-if="product && product.base_repos.length > 0" class="mgmt-list-toolbar">
      <input
        v-model="keyword"
        class="mgmt-search"
        type="text"
        :placeholder="$t('management.repository.search_placeholder')"
      />
      <span class="text-muted">{{ $t('management.common.total_count', { count: filteredRepos.length }) }}</span>
    </div>

    <div v-if="!product || product.base_repos.length === 0" class="mgmt-empty">
      {{ $t('management.product.no_base_repos') }}
    </div>

    <div v-else-if="filteredRepos.length === 0" class="mgmt-empty">
      {{ $t('management.common.empty') }}
    </div>

    <table v-else class="mgmt-table">
      <thead>
        <tr>
          <th>{{ $t('management.common.name') }}</th>
          <th>{{ $t('management.repository.git_url') }}</th>
          <th>{{ $t('management.repository.repo_type') }}</th>
          <th>{{ $t('management.repository.default_branch') }}</th>
          <th v-if="canManage">{{ $t('management.common.actions') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="repo in pagedRepos" :key="repo.id">
          <td class="mgmt-repo-name">{{ repo.repository_name }}</td>
          <td class="mgmt-repo-url">{{ repo.git_url }}</td>
          <td>
            <span class="mgmt-tag" :class="repo.repo_type === 'CUSTOM' ? 'custom' : 'ootb'">
              {{ repo.repo_type === 'CUSTOM'
                ? $t('management.repository.type_custom')
                : $t('management.repository.type_ootb') }}
            </span>
          </td>
          <td>
            <span class="mgmt-ref-badge">
              <GitBranch class="w-4 h-4" />
              <span>{{ repo.default_branch || '-' }}</span>
            </span>
          </td>
          <td v-if="canManage">
            <IconActionButton
              :icon="Trash2"
              :title="$t('management.common.delete')"
              tone="danger"
              :disabled="removingRepoId === repo.id"
              @click="confirmRemove(repo.repository_id)"
            />
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="filteredRepos.length > pageSize" class="mgmt-pagination">
      <button class="btn-secondary" :disabled="page <= 1" @click="goPage(-1)">
        {{ $t('workspaces.queue.prev_page') }}
      </button>
      <span class="text-muted">{{ page }} / {{ totalPages }}</span>
      <button class="btn-secondary" :disabled="page >= totalPages" @click="goPage(1)">
        {{ $t('workspaces.queue.next_page') }}
      </button>
    </div>

    <RepoGroupPicker
      :show="pickerVisible"
      :exclude-ids="product ? product.base_repos.map((repo) => repo.repository_id) : []"
      :allowed-repo-types="allowedRepoTypes"
      v-model="selectedRepoIds"
      @close="cancelPicker"
      @confirm="confirmPicker"
    />
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.mgmt-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.5rem;
}

.mgmt-section-head .btn-secondary {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}

.mgmt-list-toolbar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

.mgmt-list-toolbar .mgmt-search {
  max-width: 320px;
}

.mgmt-repo-name {
  font-weight: 600;
  color: #334155;
}

.mgmt-repo-url {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.8rem;
  color: #64748b;
  word-break: break-all;
}

.mgmt-ref-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  color: #475569;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}
</style>
