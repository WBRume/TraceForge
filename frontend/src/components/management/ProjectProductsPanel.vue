<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { ArrowRight, Plus, Trash2 } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import IconActionButton from '@/components/management/IconActionButton.vue'
import LifecycleBadge from '@/components/management/LifecycleBadge.vue'
import {
  addProjectProduct,
  listProducts,
  removeProjectProduct,
  transitionProjectProductDelivery,
} from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import { LIFECYCLE_FLOW } from '@/types/management'
import type { Product, ProjectDetail, ProjectLifecycleStatus, ProjectProduct } from '@/types/management'

const props = defineProps<{
  project: ProjectDetail;
  canManage: boolean;
}>()

const emit = defineEmits<{
  (e: 'changed'): void;
}>()

const { t } = useI18n()

const lifecycleLabel = (status: ProjectLifecycleStatus): string =>
  t('management.project.lifecycle_' + status.toLowerCase())

// 添加产品
const products = ref<Product[]>([])
const pendingProductId = ref<string | null>(null)
const adding = ref(false)

const includedProductIds = computed(() => new Set(props.project.products.map((p) => p.product_id)))

const availableProducts = computed(() =>
  products.value.filter((p) => !includedProductIds.value.has(p.id))
)

const availableOptions = computed(() =>
  availableProducts.value.map((p) => ({ label: p.name, value: p.id }))
)

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

const addProduct = async () => {
  if (!pendingProductId.value) return
  adding.value = true
  try {
    await addProjectProduct(props.project.id, pendingProductId.value)
    pendingProductId.value = null
    emit('changed')
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    adding.value = false
  }
}

// 推进交付进度
const advancing = ref<ProjectProduct | null>(null)
const advancingNext = computed<ProjectLifecycleStatus | null>(() =>
  advancing.value ? LIFECYCLE_FLOW[advancing.value.delivery_status] ?? null : null
)
const transitionLoading = ref(false)

const nextStatusFor = (product: ProjectProduct): ProjectLifecycleStatus | null =>
  LIFECYCLE_FLOW[product.delivery_status] ?? null

const openAdvance = (product: ProjectProduct) => {
  advancing.value = product
}

const confirmAdvance = async () => {
  const product = advancing.value
  const next = advancingNext.value
  if (!product || !next) return
  transitionLoading.value = true
  try {
    await transitionProjectProductDelivery(props.project.id, product.product_id, next)
    advancing.value = null
    emit('changed')
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    transitionLoading.value = false
  }
}

// 移除产品
const removing = ref<ProjectProduct | null>(null)
const removeLoading = ref(false)

const confirmRemove = async () => {
  if (!removing.value) return
  removeLoading.value = true
  try {
    await removeProjectProduct(props.project.id, removing.value.product_id)
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
    <h3>{{ $t('management.project.products_title') }}</h3>

    <table v-if="project.products.length > 0" class="mgmt-table">
      <thead>
        <tr>
          <th>{{ $t('management.product.name') }}</th>
          <th>{{ $t('management.product.code') }}</th>
          <th>{{ $t('management.project.product_version_label') }}</th>
          <th>{{ $t('management.project.delivery_title') }}</th>
          <th v-if="canManage">{{ $t('management.common.actions') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="product in project.products" :key="product.product_id">
          <td>{{ product.product_name || product.product_id }}</td>
          <td class="mgmt-code-cell">{{ product.product_code || '-' }}</td>
          <td class="mgmt-code-cell">{{ product.product_version_no || '-' }}</td>
          <td><LifecycleBadge :status="product.delivery_status" /></td>
          <td v-if="canManage">
            <div class="row-actions">
              <IconActionButton
                :icon="ArrowRight"
                :title="$t('management.project.next_transition', {
                  target: nextStatusFor(product) ? lifecycleLabel(nextStatusFor(product)!) : '',
                })"
                tone="primary"
                :disabled="!nextStatusFor(product)"
                @click="openAdvance(product)"
              />
              <IconActionButton
                :icon="Trash2"
                :title="$t('common.delete')"
                tone="danger"
                @click="removing = product"
              />
            </div>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-else class="mgmt-empty">{{ $t('management.project.no_products') }}</div>

    <div v-if="canManage" class="mgmt-product-add">
      <div class="mgmt-product-add-select">
        <BaseSelect
          v-model="pendingProductId"
          :options="availableOptions"
          :placeholder="$t('management.project.product_select')"
        />
      </div>
      <button
        class="btn-primary"
        :disabled="!pendingProductId || adding"
        @click="addProduct"
      >
        <Plus class="w-4 h-4" /> {{ $t('management.project.add_product') }}
      </button>
    </div>

    <ConfirmActionModal
      :show="Boolean(advancing)"
      :title="$t('management.project.delivery_title')"
      :message="$t('management.project.transition_product_confirm', {
        product: advancing?.product_name || advancing?.product_id || '',
        from: advancing ? lifecycleLabel(advancing.delivery_status) : '',
        to: advancingNext ? lifecycleLabel(advancingNext) : '',
      })"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('common.confirm')"
      tone="primary"
      :loading="transitionLoading"
      @cancel="advancing = null"
      @confirm="confirmAdvance"
    />

    <ConfirmActionModal
      :show="Boolean(removing)"
      :title="$t('management.project.products_title')"
      :message="$t('management.project.remove_product_confirm', {
        name: removing?.product_name || removing?.product_id || '',
      })"
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
.mgmt-code-cell {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.82rem;
  color: #475569;
}

.mgmt-product-add {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-top: 1rem;
}

.mgmt-product-add-select {
  flex: 1;
  max-width: 360px;
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