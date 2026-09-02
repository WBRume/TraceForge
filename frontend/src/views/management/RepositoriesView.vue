<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Plus } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import AdminGuard from '@/components/management/AdminGuard.vue'
import BaseSelect from '@/components/BaseSelect.vue'
import RepoGroupTreePanel from '@/components/management/RepoGroupTreePanel.vue'
import RepoFormModal from '@/components/management/RepoFormModal.vue'
import RepoListTable from '@/components/management/RepoListTable.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import { deleteRepository, getRepoGroupTree, listRepositories } from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import type { Repository, RepoGroupTreeNode, RepositoryType } from '@/types/management'

const { t } = useI18n()
const authStore = useAuthStore()

const isAdmin = computed(() => Boolean(authStore.user?.is_admin))

const keyword = ref('')
const repoType = ref<string>('')
const selectedGroupId = ref<string | null>(null)

const items = ref<Repository[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)

const groups = ref<RepoGroupTreeNode[]>([])

const formVisible = ref(false)
const editingRepo = ref<Repository | null>(null)
const defaultGroupId = ref<string | null>(null)

const deletingRepo = ref<Repository | null>(null)
const deleteLoading = ref(false)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

const repoTypeOptions = computed(() => [
  { label: t('chat.session_filter_all'), value: '' },
  { label: t('management.repository.type_ootb'), value: 'OOTB' },
  { label: t('management.repository.type_custom'), value: 'CUSTOM' },
])

const loadGroups = async () => {
  try {
    const res = await getRepoGroupTree()
    groups.value = res.items ?? []
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  }
}

const load = async () => {
  loading.value = true
  try {
    const res = await listRepositories({
      keyword: keyword.value || undefined,
      repo_type: (repoType.value || '') as RepositoryType | '',
      group_id: selectedGroupId.value,
      page: page.value,
      page_size: pageSize,
    })
    items.value = res.items ?? []
    total.value = res.total ?? 0
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
  void loadGroups()
})

watch(keyword, () => {
  page.value = 1
  void load()
})

watch(repoType, () => {
  page.value = 1
  void load()
})

const handleSelectGroup = (groupId: string | null) => {
  selectedGroupId.value = groupId
  page.value = 1
  void load()
}

const handleChanged = () => {
  void loadGroups()
  void load()
}

const openCreate = () => {
  editingRepo.value = null
  defaultGroupId.value = selectedGroupId.value
  formVisible.value = true
}

const openEdit = (repo: Repository) => {
  editingRepo.value = repo
  defaultGroupId.value = repo.group_id ?? null
  formVisible.value = true
}

const handleRepoSaved = () => {
  formVisible.value = false
  void load()
  void loadGroups()
}

const openDelete = (repo: Repository) => {
  deletingRepo.value = repo
}

const handleDeleteConfirm = async () => {
  if (!deletingRepo.value) return
  deleteLoading.value = true
  try {
    await deleteRepository(deletingRepo.value.id)
    ElMessage.success(t('management.common.deleted'))
    deletingRepo.value = null
    void load()
    void loadGroups()
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    deleteLoading.value = false
  }
}

const goToPage = (target: number) => {
  const next = Math.min(Math.max(1, target), totalPages.value)
  if (next === page.value) return
  page.value = next
  void load()
}
</script>

<template>
  <div>
    <div class="mgmt-page-header">
      <div>
        <h2>{{ $t('management.repository.title') }}</h2>
        <p class="mgmt-subtitle">{{ $t('management.repository.subtitle') }}</p>
      </div>
    </div>

    <div class="mgmt-repo-layout">
      <div class="mgmt-repo-sidebar">
        <RepoGroupTreePanel
          :can-manage="isAdmin"
          :selected-group-id="selectedGroupId"
          @select-group="handleSelectGroup"
          @changed="handleChanged"
        />
      </div>

      <div class="mgmt-repo-main">
        <div class="mgmt-toolbar">
          <input
            v-model="keyword"
            class="mgmt-search"
            type="text"
            :placeholder="$t('management.common.search_placeholder')"
            @keyup.enter="page = 1; load()"
          />
          <BaseSelect
            v-model="repoType"
            :options="repoTypeOptions"
            class="mgmt-repo-type-select"
          />
          <AdminGuard>
            <button
              class="btn-primary"
              :disabled="!selectedGroupId"
              :title="selectedGroupId
                ? $t('management.repository.create')
                : $t('management.repository.create_requires_group')"
              @click="openCreate"
            >
              <Plus class="mgmt-create-icon" />
              {{ $t('management.repository.create') }}
            </button>
          </AdminGuard>
        </div>

        <RepoListTable
          :items="items"
          :loading="loading"
          :can-manage="isAdmin"
          @edit="openEdit"
          @remove="openDelete"
        />

        <div class="mgmt-pagination">
          <button class="btn-secondary" :disabled="page <= 1" @click="goToPage(page - 1)">
            {{ $t('workspaces.queue.prev_page') }}
          </button>
          <span class="text-muted">{{ page }} / {{ totalPages }}</span>
          <button
            class="btn-secondary"
            :disabled="page >= totalPages"
            @click="goToPage(page + 1)"
          >
            {{ $t('workspaces.queue.next_page') }}
          </button>
        </div>

        <RepoFormModal
          :show="formVisible"
          :repository="editingRepo"
          :groups="groups"
          :default-group-id="defaultGroupId"
          @saved="handleRepoSaved"
          @cancel="formVisible = false"
        />

        <ConfirmActionModal
          :show="Boolean(deletingRepo)"
          :title="$t('management.repository.title')"
          :message="$t('management.repository.delete_confirm', { name: deletingRepo?.name ?? '' })"
          :cancel-text="$t('common.cancel')"
          :confirm-text="$t('common.delete')"
          tone="danger"
          :loading="deleteLoading"
          @cancel="deletingRepo = null"
          @confirm="handleDeleteConfirm"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.mgmt-repo-layout {
  display: flex;
  gap: 1.25rem;
  align-items: flex-start;
}

.mgmt-repo-sidebar {
  width: 300px;
  flex-shrink: 0;
}

.mgmt-repo-main {
  flex: 1;
  min-width: 0;
}

.mgmt-repo-type-select {
  width: 180px;
  flex-shrink: 0;
}

.mgmt-create-icon {
  width: 0.9rem;
  height: 0.9rem;
}

.mgmt-pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.75rem;
  margin-top: 1rem;
}
</style>

<style scoped src="@/styles/management/management-shared.css"></style>
