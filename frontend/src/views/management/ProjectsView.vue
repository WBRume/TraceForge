<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Plus } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import AdminGuard from '@/components/management/AdminGuard.vue'
import ProjectListTable from '@/components/management/ProjectListTable.vue'
import ProjectFormModal from '@/components/management/ProjectFormModal.vue'
import { deleteProject, listProjects } from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import { useAuthStore } from '@/stores/auth'
import type { Project, ProjectLifecycleStatus } from '@/types/management'

const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()

const isAdmin = computed(() => Boolean(authStore.user?.is_admin))

const items = ref<Project[]>([])
const total = ref(0)
const loading = ref(false)

const keyword = ref('')
const lifecycleStatus = ref<string>('')
const page = ref(1)
const pageSize = 20

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

const lifecycleOptions = computed(() => [
  { label: t('chat.session_filter_all'), value: '' },
  ...([
    'INITIATED',
    'DEVELOPING',
    'DELIVERING',
    'MAINTAINING',
    'RETIRED',
  ] as ProjectLifecycleStatus[]).map((status) => ({
    label: t('management.project.lifecycle_' + status.toLowerCase()),
    value: status,
  })),
])

const load = async () => {
  loading.value = true
  try {
    const res = await listProjects({
      keyword: keyword.value || undefined,
      lifecycle_status: lifecycleStatus.value || undefined,
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

const applySearch = () => {
  page.value = 1
  void load()
}

const prevPage = () => {
  if (page.value <= 1 || loading.value) return
  page.value -= 1
  void load()
}

const nextPage = () => {
  if (page.value >= totalPages.value || loading.value) return
  page.value += 1
  void load()
}

onMounted(() => {
  void load()
})

// 新建 / 编辑
const formShow = ref(false)
const editing = ref<Project | null>(null)

const openCreate = () => {
  editing.value = null
  formShow.value = true
}

const openEdit = (project: Project) => {
  router.push({ path: '/management/projects/' + project.id, query: { mode: 'edit' } })
}

const handleSaved = () => {
  formShow.value = false
  void load()
}

// 删除
const removing = ref<Project | null>(null)
const removeLoading = ref(false)

const confirmRemove = async () => {
  if (!removing.value) return
  removeLoading.value = true
  try {
    await deleteProject(removing.value.id)
    removing.value = null
    ElMessage.success(t('common.success'))
    void load()
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    removeLoading.value = false
  }
}

const openDetail = (project: Project) => {
  router.push({ path: '/management/projects/' + project.id, query: { mode: 'view' } })
}
</script>

<template>
  <div>
    <div class="mgmt-page-header">
      <div>
        <h2>{{ $t('management.project.title') }}</h2>
        <p class="mgmt-subtitle">{{ $t('management.project.subtitle') }}</p>
      </div>
      <AdminGuard :show-hint="false">
        <button class="btn-primary" @click="openCreate">
          <Plus class="w-4 h-4" /> {{ $t('management.project.create') }}
        </button>
      </AdminGuard>
    </div>

    <div class="mgmt-toolbar">
      <input
        v-model="keyword"
        class="mgmt-search"
        type="text"
        :placeholder="$t('management.common.search_placeholder')"
        @keyup.enter="applySearch"
      />
      <div class="mgmt-filter-select">
        <BaseSelect
          v-model="lifecycleStatus"
          :options="lifecycleOptions"
          @update:model-value="applySearch"
        />
      </div>
    </div>

    <AdminGuard />

    <ProjectListTable
      :items="items"
      :loading="loading"
      :can-manage="isAdmin"
      @open="openDetail"
      @edit="openEdit"
      @remove="removing = $event"
    />

    <div class="mgmt-pagination">
      <button class="btn-secondary" :disabled="page <= 1 || loading" @click="prevPage">
        {{ $t('workspaces.queue.prev_page') }}
      </button>
      <span class="mgmt-pagination-info">{{ page }} / {{ totalPages }}</span>
      <button class="btn-secondary" :disabled="page >= totalPages || loading" @click="nextPage">
        {{ $t('workspaces.queue.next_page') }}
      </button>
    </div>

    <ProjectFormModal
      :show="formShow"
      :project="editing"
      @saved="handleSaved"
      @cancel="formShow = false"
    />

    <ConfirmActionModal
      :show="Boolean(removing)"
      :title="$t('management.project.delete_confirm', { name: removing?.name || '' })"
      :message="$t('management.project.delete_confirm', { name: removing?.name || '' })"
      :emphasis-label="$t('management.project.name')"
      :emphasis-value="removing?.name || ''"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('common.confirm')"
      tone="danger"
      :loading="removeLoading"
      @cancel="removing = null"
      @confirm="confirmRemove"
    />
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.mgmt-filter-select {
  width: 200px;
  flex-shrink: 0;
}

.mgmt-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  margin-top: 1rem;
}

.mgmt-pagination-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.35rem 0.6rem;
}

.mgmt-pagination-info {
  font-size: 0.82rem;
  color: #64748b;
  min-width: 70px;
  text-align: center;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}
</style>
