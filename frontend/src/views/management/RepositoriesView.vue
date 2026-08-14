<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Plus } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import AdminGuard from '@/components/management/AdminGuard.vue'
import BaseSelect from '@/components/BaseSelect.vue'
import OrgTreePanel from '@/components/management/OrgTreePanel.vue'
import RepoFormModal from '@/components/management/RepoFormModal.vue'
import RepoListTable from '@/components/management/RepoListTable.vue'
import RepoRefListPanel from '@/components/management/RepoRefListPanel.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import {
  deleteRepository,
  listRepositories,
  syncRepositoryRefs,
} from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import type { OrgTreeNode, Repository } from '@/types/management'

const { t } = useI18n()
const authStore = useAuthStore()

const isAdmin = computed(() => Boolean(authStore.user?.is_admin))

// 筛选状态
const keyword = ref('')
const repoType = ref<string>('')
const selectedOrgNodeId = ref<string | null>(null)

// 列表状态
const items = ref<Repository[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const syncingRepoId = ref<string | null>(null)

// 组织树节点（供表单拍平）
const orgNodes = ref<OrgTreeNode[]>([])

// 展开引用
const expandedRepoId = ref<string | null>(null)

// 表单弹窗
const formVisible = ref(false)
const editingRepo = ref<Repository | null>(null)
const defaultOrgNodeId = ref<string | null>(null)

// 删除确认
const deletingRepo = ref<Repository | null>(null)
const deleteLoading = ref(false)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

const repoTypeOptions = computed(() => [
  { label: t('chat.session_filter_all'), value: '' },
  { label: t('management.repository.type_ootb'), value: 'OOTB' },
  { label: t('management.repository.type_custom'), value: 'CUSTOM' },
])

const load = async () => {
  loading.value = true
  try {
    const res = await listRepositories({
      keyword: keyword.value || undefined,
      repo_type: (repoType.value || '') as Repository['repo_type'] | '',
      org_node_id: selectedOrgNodeId.value ?? undefined,
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
})

watch(keyword, () => {
  page.value = 1
  void load()
})

watch(repoType, () => {
  page.value = 1
  void load()
})

const handleSelectOrgNode = (nodeId: string | null) => {
  selectedOrgNodeId.value = nodeId
  page.value = 1
  void load()
}

const handleOrgLoad = (nodes: OrgTreeNode[]) => {
  orgNodes.value = nodes
}

const openCreate = () => {
  editingRepo.value = null
  defaultOrgNodeId.value = selectedOrgNodeId.value
  formVisible.value = true
}

const openEdit = (repo: Repository) => {
  editingRepo.value = repo
  defaultOrgNodeId.value = repo.org_node_id ?? null
  formVisible.value = true
}

const handleRepoSaved = () => {
  formVisible.value = false
  void load()
}

const openDelete = (repo: Repository) => {
  deletingRepo.value = repo
}

const handleDeleteConfirm = async () => {
  if (!deletingRepo.value) return
  deleteLoading.value = true
  try {
    await deleteRepository(deletingRepo.value.id)
    ElMessage.success(t('common.success'))
    deletingRepo.value = null
    void load()
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    deleteLoading.value = false
  }
}

const toggleRefs = (repo: Repository) => {
  expandedRepoId.value = expandedRepoId.value === repo.id ? null : repo.id
}

const handleSync = async (repo: Repository) => {
  if (syncingRepoId.value) return
  syncingRepoId.value = repo.id
  try {
    await syncRepositoryRefs(repo.id)
    ElMessage.success(t('management.repository.sync_queued'))
    void load()
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    syncingRepoId.value = null
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
        <OrgTreePanel
          :can-manage="isAdmin"
          :selected-repo-id="expandedRepoId"
          @select="handleSelectOrgNode"
          @changed="load"
          @load="handleOrgLoad"
        />
      </div>

      <div class="mgmt-repo-main">
        <div class="mgmt-toolbar">
          <input
            v-model="keyword"
            class="mgmt-search"
            type="text"
            :placeholder="$t('management.common.search_placeholder')"
          />
          <BaseSelect
            v-model="repoType"
            :options="repoTypeOptions"
            :placeholder="$t('management.repository.repo_type')"
            class="mgmt-repo-type-select"
          />
          <AdminGuard>
            <button class="btn-primary" @click="openCreate">
              <Plus class="mgmt-create-icon" />
              {{ $t('management.repository.create') }}
            </button>
          </AdminGuard>
        </div>

        <RepoListTable
          :items="items"
          :loading="loading"
          :can-manage="isAdmin"
          :expanded-repo-id="expandedRepoId"
          @edit="openEdit"
          @remove="openDelete"
          @toggle-refs="toggleRefs"
          @sync="handleSync"
        >
          <template #expanded="{ repo }">
            <RepoRefListPanel :repository-id="repo.id" />
          </template>
        </RepoListTable>

        <div class="mgmt-pagination">
          <button
            class="btn-secondary"
            :disabled="page <= 1"
            @click="goToPage(page - 1)"
          >
            {{ $t('workspaces.queue.prev_page') }}
          </button>
          <span class="mgmt-pagination-info">
            {{ $t('settings.members.page_info', { page, total: totalPages }) }}
          </span>
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
          :org-nodes="orgNodes"
          :default-org-node-id="defaultOrgNodeId"
          @saved="handleRepoSaved"
          @cancel="formVisible = false"
        />

        <ConfirmActionModal
          :show="Boolean(deletingRepo)"
          :title="t('management.repository.title')"
          :message="$t('management.repository.delete_confirm', { name: deletingRepo?.name ?? '' })"
          :cancel-text="t('common.cancel')"
          :confirm-text="t('common.delete')"
          :loading="deleteLoading"
          :tone="'danger'"
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

.mgmt-pagination-info {
  font-size: 0.85rem;
  color: #64748b;
}
</style>

<style scoped src="@/styles/management/management-shared.css"></style>