<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Plus } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import {
  addProjectProductDep,
  getProduct,
  listProducts,
  removeProjectProductDep,
  updateProjectProductDep,
} from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import type { Product, ProductDetail, ProjectDetail, ProjectProductDep } from '@/types/management'

const props = defineProps<{
  project: ProjectDetail;
  canManage: boolean;
}>()

const emit = defineEmits<{
  (e: 'changed'): void;
}>()

const { t } = useI18n()

const products = ref<Product[]>([])

const depVersions = reactive<Record<string, ProductDetail | null>>({})
const depVersionPending = reactive<Record<string, boolean>>({})

const loadProducts = async () => {
  try {
    const res = await listProducts({ page_size: 100 })
    products.value = res.items ?? []
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  }
}

onMounted(() => {
  void loadProducts()
})

const findProduct = (productId: string): ProductDetail | null =>
  depVersions[productId] ?? null

const loadProduct = async (productId: string) => {
  if (depVersions[productId]) return
  depVersionPending[productId] = true
  try {
    depVersions[productId] = await getProduct(productId)
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    depVersionPending[productId] = false
  }
}

const depProductIds = computed(() => new Set(props.project.product_deps.map((d) => d.product_id)))

const availableProducts = computed(() =>
  products.value.filter((p) => !depProductIds.value.has(p.id))
)

const availableOptions = computed(() =>
  availableProducts.value.map((p) => ({ label: p.name, value: p.id }))
)

const versionOptionsFor = (dep: ProjectProductDep): { label: string; value: string | null }[] => {
  const detail = findProduct(dep.product_id)
  const versions = detail?.versions ?? []
  return [
    { label: t('management.project.dep_follow_latest'), value: null },
    ...versions.map((v) => ({ label: v.version_no, value: v.id })),
  ]
}

const versionLabel = (dep: ProjectProductDep): string => {
  if (!dep.product_version_no) return t('management.project.dep_follow_latest')
  return dep.product_version_no
}

// 添加依赖
const pendingProductId = ref<string | null>(null)
const adding = ref(false)

const addDep = async () => {
  if (!pendingProductId.value) return
  adding.value = true
  try {
    await addProjectProductDep(props.project.id, { product_id: pendingProductId.value })
    pendingProductId.value = null
    emit('changed')
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    adding.value = false
  }
}

// 切换锁定版本
const savingVersionFor = ref<string | null>(null)

const changeVersion = async (dep: ProjectProductDep, versionId: string | null) => {
  savingVersionFor.value = dep.product_id
  try {
    await updateProjectProductDep(props.project.id, dep.product_id, {
      product_version_id: versionId,
    })
    emit('changed')
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    savingVersionFor.value = null
  }
}

// 移除依赖
const removing = ref<ProjectProductDep | null>(null)
const removeLoading = ref(false)

const confirmRemove = async () => {
  if (!removing.value) return
  removeLoading.value = true
  try {
    await removeProjectProductDep(props.project.id, removing.value.product_id)
    removing.value = null
    emit('changed')
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    removeLoading.value = false
  }
}
</script>

<template>
  <div class="mgmt-card">
    <h3>{{ $t('management.project.deps_title') }}</h3>

    <table v-if="project.product_deps.length > 0" class="mgmt-table">
      <thead>
        <tr>
          <th>{{ $t('management.project.dep_product') }}</th>
          <th>{{ $t('management.project.dep_version') }}</th>
          <th v-if="canManage">{{ $t('management.common.actions') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="dep in project.product_deps" :key="dep.product_id">
          <td>
            <button
              v-if="!findProduct(dep.product_id)"
              class="btn-ghost mgmt-dep-load"
              :disabled="depVersionPending[dep.product_id]"
              @click="loadProduct(dep.product_id)"
            >
              {{ dep.product_name || dep.product_id }}
            </button>
            <span v-else>{{ dep.product_name || dep.product_id }}</span>
          </td>
          <td>
            <BaseSelect
              v-if="canManage && findProduct(dep.product_id)"
              :model-value="dep.product_version_id ?? null"
              :options="versionOptionsFor(dep)"
              :disabled="savingVersionFor === dep.product_id"
              @update:model-value="changeVersion(dep, $event as string | null)"
            />
            <span v-else class="mgmt-dep-version-label">
              {{ versionLabel(dep) }}
            </span>
          </td>
          <td v-if="canManage">
            <div class="row-actions">
              <button
                class="btn-ghost mgmt-dep-remove"
                :title="$t('common.delete')"
                @click="removing = dep"
              >
                {{ $t('common.delete') }}
              </button>
            </div>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-else class="mgmt-empty">{{ $t('management.project.no_deps') }}</div>

    <div v-if="canManage" class="mgmt-dep-add">
      <div class="mgmt-dep-add-select">
        <BaseSelect
          v-model="pendingProductId"
          :options="availableOptions"
          :placeholder="$t('management.project.dep_product')"
        />
      </div>
      <button
        class="btn-primary"
        :disabled="!pendingProductId || adding"
        @click="addDep"
      >
        <Plus class="w-4 h-4" /> {{ $t('management.project.add_dep') }}
      </button>
    </div>

    <ConfirmActionModal
      :show="Boolean(removing)"
      :title="$t('management.project.deps_title')"
      :message="$t('management.project.dep_remove_confirm', { name: removing?.product_name || removing?.product_id || '' })"
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
.mgmt-dep-load {
  font-size: 0.82rem;
}

.mgmt-dep-version-label {
  font-size: 0.82rem;
  color: #334155;
}

.mgmt-dep-remove {
  font-size: 0.78rem;
  color: #b91c1c;
}

.mgmt-dep-add {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-top: 1rem;
}

.mgmt-dep-add-select {
  flex: 1;
  max-width: 360px;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}
</style>