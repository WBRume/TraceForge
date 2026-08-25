<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { ArrowLeft, ArrowRight, Plus, Trash2 } from 'lucide-vue-next'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import IconActionButton from '@/components/management/IconActionButton.vue'
import LifecycleBadge from '@/components/management/LifecycleBadge.vue'
import {
  addProjectProduct,
  listProducts,
  removeProjectProduct,
  transitionProjectProductDelivery,
  updateProjectProductVersion,
} from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import { LIFECYCLE_FLOW, LIFECYCLE_PREV } from '@/types/management'
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

// 添加产品（弹窗勾选产品 + 选择版本）
const products = ref<Product[]>([])
const addDialogVisible = ref(false)
const pickIds = ref<string[]>([])
const pickVersions = ref<Record<string, string>>({})
const picking = ref(false)

const includedProductIds = computed(() => new Set(props.project.products.map((p) => p.product_id)))

const availableProducts = computed(() =>
  products.value.filter(
    (p) => !includedProductIds.value.has(p.id) && (p.versions ?? []).length > 0,
  )
)

const isBaselineConflict = (product: Product): boolean => {
  const boundProducts = props.project.products
  if (product.baseline_product_id && boundProducts.some((p) => p.product_id === product.baseline_product_id)) {
    return true
  }
  return boundProducts.some((p) => products.value.find((candidate) => candidate.id === p.product_id)?.baseline_product_id === product.id)
}

const versionOptions = (product: Product): { label: string; value: string }[] =>
  (product.versions ?? []).map((v) => ({ label: v.version_no, value: v.id }))

const defaultVersionId = (product: Product): string | null =>
  (product.versions ?? []).length > 0 ? (product.versions ?? []).at(-1)!.id : null

const loadProducts = async () => {
  try {
    const res = await listProducts({ page_size: 100, include_versions: true })
    products.value = res.items ?? []
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  }
}

onMounted(() => {
  void loadProducts()
})

const openAddDialog = () => {
  pickIds.value = []
  pickVersions.value = {}
  addDialogVisible.value = true
}

const closeAddDialog = () => {
  if (picking.value) return
  addDialogVisible.value = false
}

const togglePick = (product: Product, checked: boolean) => {
  if (checked) {
    if (!pickIds.value.includes(product.id)) {
      pickIds.value.push(product.id)
    }
    if (!pickVersions.value[product.id]) {
      const latest = defaultVersionId(product)
      if (latest) pickVersions.value[product.id] = latest
    }
  } else {
    pickIds.value = pickIds.value.filter((id) => id !== product.id)
    delete pickVersions.value[product.id]
  }
}

const addProducts = async () => {
  if (pickIds.value.length === 0) return
  picking.value = true
  try {
    for (const productId of pickIds.value) {
      await addProjectProduct(props.project.id, productId, pickVersions.value[productId] || undefined)
    }
    addDialogVisible.value = false
    pickIds.value = []
    pickVersions.value = {}
    ElMessage.success(t('common.success'))
    emit('changed')
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    picking.value = false
  }
}

// 切换绑定版本（产品版本持续演进，项目可跟进新版本）
const switchingVersionId = ref<string | null>(null)

const productVersions = (productId: string) =>
  products.value.find((p) => p.id === productId)?.versions ?? []

const switchVersion = async (item: ProjectProduct, versionId: string) => {
  if (!versionId || versionId === item.product_version_id) return
  switchingVersionId.value = item.product_id
  try {
    await updateProjectProductVersion(props.project.id, item.product_id, versionId)
    ElMessage.success(t('common.success'))
    emit('changed')
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    switchingVersionId.value = null
  }
}

// 交付进度推进 / 回退
const transitionTarget = ref<{
  product: ProjectProduct;
  target: ProjectLifecycleStatus;
  backward: boolean;
} | null>(null)
const transitionLoading = ref(false)

const nextStatusFor = (product: ProjectProduct): ProjectLifecycleStatus | null =>
  LIFECYCLE_FLOW[product.delivery_status] ?? null

const prevStatusFor = (product: ProjectProduct): ProjectLifecycleStatus | null =>
  LIFECYCLE_PREV[product.delivery_status] ?? null

const openAdvance = (product: ProjectProduct) => {
  const next = nextStatusFor(product)
  if (!next) return
  transitionTarget.value = { product, target: next, backward: false }
}

const openBack = (product: ProjectProduct) => {
  const prev = prevStatusFor(product)
  if (!prev) return
  transitionTarget.value = { product, target: prev, backward: true }
}

const confirmTransition = async () => {
  const target = transitionTarget.value
  if (!target) return
  transitionLoading.value = true
  try {
    await transitionProjectProductDelivery(
      props.project.id,
      target.product.product_id,
      target.target,
    )
    transitionTarget.value = null
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
    <div class="mgmt-section-head">
      <h3>{{ $t('management.project.products_title') }}</h3>
      <button v-if="canManage" class="btn-secondary" @click="openAddDialog">
        <Plus class="w-4 h-4" /> {{ $t('management.project.add_product') }}
      </button>
    </div>

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
          <td>
            <el-select
              v-if="canManage"
              :model-value="product.product_version_id ?? ''"
              class="version-switch-select"
              size="small"
              :loading="switchingVersionId === product.product_id"
              @update:model-value="(value: string) => switchVersion(product, value)"
            >
              <el-option
                v-for="option in productVersions(product.product_id)"
                :key="option.id"
                :label="option.version_no"
                :value="option.id"
              />
            </el-select>
            <span v-else class="mgmt-code-cell">{{ product.product_version_no || '-' }}</span>
          </td>
          <td><LifecycleBadge :status="product.delivery_status" /></td>
          <td v-if="canManage">
            <div class="row-actions">
              <IconActionButton
                :icon="ArrowLeft"
                :title="$t('management.project.previous_transition', {
                  target: prevStatusFor(product) ? lifecycleLabel(prevStatusFor(product)!) : '',
                })"
                tone="primary"
                :disabled="!prevStatusFor(product)"
                @click="openBack(product)"
              />
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

    <!-- 添加产品弹窗：勾选产品（含对应产品版本） -->
    <Teleport to="body">
      <div v-if="addDialogVisible" class="mgmt-modal-overlay" @pointerdown.self="closeAddDialog">
        <div class="mgmt-modal product-pick-dialog" role="dialog" aria-modal="true">
          <h3>{{ $t('management.project.product_pick_title') }}</h3>
          <p class="mgmt-hint">{{ $t('management.project.product_pick_hint') }}</p>

          <div v-if="availableProducts.length === 0" class="mgmt-empty">
            {{ $t('management.project.no_available_products') }}
          </div>

          <div v-else class="product-pick-list">
            <div
              v-for="product in availableProducts"
              :key="product.id"
              class="product-pick-row"
              :class="{ checked: pickIds.includes(product.id), disabled: isBaselineConflict(product) }"
            >
              <input
                type="checkbox"
                :checked="pickIds.includes(product.id)"
                :disabled="isBaselineConflict(product)"
                @change="togglePick(product, ($event.target as HTMLInputElement).checked)"
              />
              <span class="product-pick-name">{{ product.name }}</span>
              <span class="product-pick-code">{{ product.code }}</span>
              <el-select
                v-model="pickVersions[product.id]"
                class="product-pick-version-select"
                :placeholder="$t('management.project.product_version_label')"
                :disabled="!pickIds.includes(product.id) || isBaselineConflict(product)"
                size="small"
              >
                <el-option
                  v-for="option in versionOptions(product)"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
              <span v-if="isBaselineConflict(product)" class="product-pick-conflict">
                {{ $t('management.project.custom_baseline_conflict') }}
              </span>
            </div>
          </div>

          <div class="mgmt-modal-actions">
            <button class="btn-secondary" :disabled="picking" @click="closeAddDialog">
              {{ $t('common.cancel') }}
            </button>
            <button
              class="btn-primary"
              :disabled="pickIds.length === 0 || picking"
              @click="addProducts"
            >
              {{ picking ? $t('management.common.saving') : $t('common.confirm') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <ConfirmActionModal
      :show="Boolean(transitionTarget)"
      :title="$t('management.project.delivery_title')"
      :message="transitionTarget?.backward
        ? $t('management.project.transition_back_product_confirm', {
            product: transitionTarget.product.product_name || transitionTarget.product.product_id || '',
            from: transitionTarget ? lifecycleLabel(transitionTarget.product.delivery_status) : '',
            to: transitionTarget ? lifecycleLabel(transitionTarget.target) : '',
          })
        : $t('management.project.transition_product_confirm', {
            product: transitionTarget?.product.product_name || transitionTarget?.product.product_id || '',
            from: transitionTarget ? lifecycleLabel(transitionTarget.product.delivery_status) : '',
            to: transitionTarget ? lifecycleLabel(transitionTarget.target) : '',
          })"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('common.confirm')"
      tone="primary"
      :loading="transitionLoading"
      @cancel="transitionTarget = null"
      @confirm="confirmTransition"
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
.mgmt-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

.mgmt-section-head h3 {
  margin: 0;
}

.mgmt-section-head .btn-secondary {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}

.mgmt-code-cell {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.82rem;
  color: #475569;
}

.version-switch-select {
  width: 120px;
}

.product-pick-dialog {
  max-width: 620px;
  display: flex;
  flex-direction: column;
  max-height: 88vh;
}

.product-pick-dialog h3 {
  margin-bottom: 0.35rem;
}

.product-pick-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-top: 0.9rem;
  overflow-y: auto;
  flex: 1;
  min-height: 120px;
  padding: 0.25rem;
}

.product-pick-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.55rem 0.7rem;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: rgba(248, 250, 252, 0.6);
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}

.product-pick-row:hover {
  border-color: #bfdbfe;
}

.product-pick-row.checked {
  border-color: #0ea5e9;
  background: rgba(14, 165, 233, 0.06);
}

.product-pick-row.disabled {
  opacity: 0.6;
  cursor: not-allowed;
  background: rgba(241, 245, 249, 0.5);
}

.product-pick-row.disabled:hover {
  border-color: #e2e8f0;
}

.product-pick-conflict {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 0.76rem;
  color: #f59e0b;
}

.product-pick-name {
  font-weight: 600;
  font-size: 0.88rem;
  color: #334155;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.product-pick-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.76rem;
  color: #94a3b8;
  flex-shrink: 0;
}

.product-pick-version {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 0.78rem;
  color: #64748b;
}

.product-pick-version-select {
  margin-left: auto;
  flex-shrink: 0;
  width: 130px;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}
</style>
