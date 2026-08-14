<!--
ProductsView: thin shell over product list / form / delete components.
-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import AdminGuard from '@/components/management/AdminGuard.vue'
import ProductListTable from '@/components/management/ProductListTable.vue'
import ProductFormModal from '@/components/management/ProductFormModal.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import BaseSelect from '@/components/BaseSelect.vue'
import { deleteProduct, listProducts } from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import { useAuthStore } from '@/stores/auth'
import type { Product, ProductStatus } from '@/types/management'

const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()

const isAdmin = computed(() => Boolean(authStore.user?.is_admin))

const items = ref<Product[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const keyword = ref('')
const statusFilter = ref<'ALL' | ProductStatus>('ALL')

const pageSize = 20

const statusOptions = computed(() => [
  { label: t('chat.session_filter_all'), value: 'ALL' },
  { label: t('management.product.status_active'), value: 'ACTIVE' },
  { label: t('management.product.status_archived'), value: 'ARCHIVED' },
])

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

const showForm = ref(false)
const editingProduct = ref<Product | null>(null)

const deleteTarget = ref<Product | null>(null)
const deleting = ref(false)

const load = async () => {
  loading.value = true
  try {
    const res = await listProducts({
      keyword: keyword.value || undefined,
      status: statusFilter.value === 'ALL' ? undefined : statusFilter.value,
      page: page.value,
      page_size: pageSize,
    })
    items.value = res.items
    total.value = res.total
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    loading.value = false
  }
}

onMounted(load)

const reload = () => {
  page.value = 1
  load()
}

const openCreate = () => {
  editingProduct.value = null
  showForm.value = true
}

const openEdit = (product: Product) => {
  editingProduct.value = product
  showForm.value = true
}

const onSaved = () => {
  showForm.value = false
  ElMessage.success(t('management.common.save'))
  load()
}

const confirmDelete = async () => {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await deleteProduct(deleteTarget.value.id)
    ElMessage.success(t('management.common.deleted'))
    deleteTarget.value = null
    reload()
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    deleting.value = false
  }
}

const openDetail = (product: Product) => {
  router.push('/management/products/' + product.id)
}

const changePage = (delta: number) => {
  const next = page.value + delta
  if (next < 1 || next > totalPages.value) return
  page.value = next
  load()
}
</script>

<template>
  <div>
    <div class="mgmt-page-header">
      <div>
        <h2>{{ $t('management.product.title') }}</h2>
        <p class="mgmt-subtitle">{{ $t('management.product.subtitle') }}</p>
      </div>
      <AdminGuard>
        <button class="btn-primary" @click="openCreate">
          {{ $t('management.product.create') }}
        </button>
      </AdminGuard>
    </div>

    <div class="mgmt-toolbar">
      <input
        v-model="keyword"
        class="mgmt-search"
        type="text"
        :placeholder="$t('management.common.search_placeholder')"
        @keyup.enter="reload"
      />
      <button class="btn-secondary" @click="reload">{{ $t('common.refresh') }}</button>
      <BaseSelect v-model="statusFilter" :options="statusOptions" class="mgmt-status-filter" />
    </div>

    <ProductListTable
      :items="items"
      :loading="loading"
      :can-manage="isAdmin"
      @open="openDetail"
      @edit="openEdit"
      @remove="deleteTarget = $event"
    />

    <div v-if="total > 0" class="mgmt-pagination">
      <button class="btn-secondary" :disabled="page <= 1" @click="changePage(-1)">
        {{ $t('workspaces.queue.prev_page') }}
      </button>
      <span class="text-muted">{{ page }} / {{ totalPages }} · {{ total }}</span>
      <button class="btn-secondary" :disabled="page >= totalPages" @click="changePage(1)">
        {{ $t('workspaces.queue.next_page') }}
      </button>
    </div>

    <ProductFormModal
      :show="showForm"
      :product="editingProduct"
      @saved="onSaved"
      @cancel="showForm = false"
    />

    <ConfirmActionModal
      :show="Boolean(deleteTarget)"
      :title="$t('management.product.title')"
      :message="$t('management.product.delete_confirm', { name: deleteTarget?.name ?? '' })"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('common.confirm')"
      tone="danger"
      :loading="deleting"
      @cancel="deleteTarget = null"
      @confirm="confirmDelete"
    />
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.mgmt-status-filter {
  width: 160px;
  flex-shrink: 0;
}

.mgmt-pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 0.75rem 0;
}
</style>
