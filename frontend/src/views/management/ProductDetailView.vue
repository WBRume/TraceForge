<!--
ProductDetailView: thin shell over product header + version list + modals.
-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { ArrowLeft } from 'lucide-vue-next'
import AdminGuard from '@/components/management/AdminGuard.vue'
import VersionListSection from '@/components/management/VersionListSection.vue'
import VersionFormModal from '@/components/management/VersionFormModal.vue'
import VersionRepoBindingPanel from '@/components/management/VersionRepoBindingPanel.vue'
import ProductFormModal from '@/components/management/ProductFormModal.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import { deleteProductVersion, getProduct } from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import { useAuthStore } from '@/stores/auth'
import type { ProductDetail, ProductVersion } from '@/types/management'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()

const productId = computed(() => String(route.params.productId ?? ''))

const isAdmin = computed(() => Boolean(authStore.user?.is_admin))

const detail = ref<ProductDetail | null>(null)
const loading = ref(false)

const showEdit = ref(false)

const showVersionForm = ref(false)
const editingVersion = ref<ProductVersion | null>(null)

const selectedBindingVersionId = ref<string | null>(null)

const deleteVersionTarget = ref<ProductVersion | null>(null)
const deletingVersion = ref(false)

const load = async () => {
  loading.value = true
  try {
    detail.value = await getProduct(productId.value)
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    loading.value = false
  }
}

onMounted(load)

const goBack = () => {
  if (window.history.length > 1) {
    router.back()
  } else {
    router.push('/management/products')
  }
}

const onProductSaved = () => {
  showEdit.value = false
  load()
}

const openAddVersion = () => {
  editingVersion.value = null
  showVersionForm.value = true
}

const openEditVersion = (version: ProductVersion) => {
  editingVersion.value = version
  showVersionForm.value = true
}

const onVersionSaved = () => {
  showVersionForm.value = false
  load()
}

const toggleBindings = (version: ProductVersion) => {
  selectedBindingVersionId.value = selectedBindingVersionId.value === version.id ? null : version.id
}

const confirmDeleteVersion = async () => {
  if (!deleteVersionTarget.value) return
  deletingVersion.value = true
  try {
    await deleteProductVersion(productId.value, deleteVersionTarget.value.id)
    ElMessage.success(t('management.common.deleted'))
    deleteVersionTarget.value = null
    load()
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    deletingVersion.value = false
  }
}
</script>

<template>
  <div>
    <div class="mgmt-page-header">
      <div>
        <button class="btn-ghost mgmt-back" @click="goBack">
          <ArrowLeft class="w-4 h-4" />
          {{ $t('management.product.back_to_list') }}
        </button>
        <h2 v-if="detail" class="mgmt-detail-title">{{ detail.name }}</h2>
        <p v-if="detail" class="mgmt-subtitle">
          <span class="mgmt-detail-code">{{ detail.code }}</span>
          <span v-if="detail.product_line"> · {{ detail.product_line }}</span>
        </p>
        <p v-if="detail && detail.description" class="text-muted">{{ detail.description }}</p>
      </div>
      <AdminGuard>
        <button v-if="detail" class="btn-secondary" @click="showEdit = true">
          {{ $t('common.edit') }}
        </button>
      </AdminGuard>
    </div>

    <VersionListSection
      :versions="detail?.versions ?? []"
      :can-manage="isAdmin"
      @add="openAddVersion"
      @edit="openEditVersion"
      @remove="deleteVersionTarget = $event"
      @toggle-bindings="toggleBindings"
    />

    <div
      v-for="version in detail?.versions ?? []"
      :key="version.id"
    >
      <VersionRepoBindingPanel
        v-if="selectedBindingVersionId === version.id"
        :product-id="productId"
        :version="version"
        :can-manage="isAdmin"
        @changed="load"
      />
    </div>

    <ProductFormModal
      :show="showEdit"
      :product="detail"
      @saved="onProductSaved"
      @cancel="showEdit = false"
    />

    <VersionFormModal
      :show="showVersionForm"
      :product-id="productId"
      :version="editingVersion"
      @saved="onVersionSaved"
      @cancel="showVersionForm = false"
    />

    <ConfirmActionModal
      :show="Boolean(deleteVersionTarget)"
      :title="$t('management.product.versions_title')"
      :message="$t('management.product.delete_version_confirm', {
        version: deleteVersionTarget?.version_no ?? '',
      })"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('common.confirm')"
      tone="danger"
      :loading="deletingVersion"
      @cancel="deleteVersionTarget = null"
      @confirm="confirmDeleteVersion"
    />
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.mgmt-back {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.5rem;
}

.mgmt-detail-title {
  margin-top: 0.25rem;
}

.mgmt-detail-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  color: #334155;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}
</style>
