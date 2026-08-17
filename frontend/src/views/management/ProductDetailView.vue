<!--
ProductDetailView: thin shell over product header + info card + repo bindings.
-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
import { ElMessage } from 'element-plus';
import { ArrowLeft } from 'lucide-vue-next';
import AdminGuard from '@/components/management/AdminGuard.vue';
import ProductBaseReposPanel from '@/components/management/ProductBaseReposPanel.vue';
import ProductFormModal from '@/components/management/ProductFormModal.vue';
import ProductVersionsPanel from '@/components/management/ProductVersionsPanel.vue';
import { getProduct } from '@/services/managementApi';
import { formatApiError } from '@/utils/error';
import { useAuthStore } from '@/stores/auth';
import type { ProductDetail } from '@/types/management';

const route = useRoute();
const router = useRouter();
const { t } = useI18n();
const authStore = useAuthStore();

const productId = computed(() => String(route.params.productId ?? ''));
const focusVersionId = computed(() => String(route.query.version ?? '') || null);

const isAdmin = computed(() => Boolean(authStore.user?.is_admin));

// 查看（默认 / ?mode=view）为只读；编辑（?mode=edit）开放完整编辑能力（含仓库绑定等）
const editMode = computed(() => route.query.mode === 'edit');
const canManage = computed(() => editMode.value && isAdmin.value);

const detail = ref<ProductDetail | null>(null);
const loading = ref(false);

const showEdit = ref(false);
const baseReposVisible = ref(false);
const customProductsVisible = ref(false);

const load = async () => {
  loading.value = true;
  try {
    detail.value = await getProduct(productId.value);
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t));
  } finally {
    loading.value = false;
  }
};

onMounted(() => {
  void load();
});

const goBack = () => {
  router.push('/management/products');
};

const openProduct = (productId: string) => {
  router.push({ path: '/management/products/' + productId, query: { mode: 'view' } });
};

const onProductSaved = () => {
  showEdit.value = false;
  void load();
};

const onBindingsChanged = () => {
  void load();
};
</script>

<template>
  <div>
    <div class="mgmt-page-header">
      <div>
        <button class="btn-secondary mgmt-back" @click="goBack">
          <ArrowLeft class="w-4 h-4" />
          {{ $t('management.product.back_to_list') }}
        </button>
        <h2 v-if="detail" class="mgmt-detail-title">
          {{ detail.name }}
          <span
            class="mgmt-status-pill"
            :class="detail.status === 'ACTIVE' ? 'green' : 'gray'"
          >
            {{ detail.status === 'ACTIVE'
              ? $t('management.product.status_active')
              : $t('management.product.status_archived') }}
          </span>
        </h2>
        <p v-if="detail" class="mgmt-subtitle">
          {{ detail.code }}
          <span class="mgmt-mode-badge" :class="editMode ? 'edit' : 'view'">
            {{ editMode ? $t('management.common.edit_mode') : $t('management.common.view_mode') }}
          </span>
        </p>
      </div>
      <AdminGuard>
        <button v-if="detail && editMode" class="btn-secondary" @click="showEdit = true">
          {{ $t('management.common.edit') }}
        </button>
      </AdminGuard>
    </div>

    <div v-if="loading" class="mgmt-empty">{{ $t('management.common.loading') }}</div>

    <template v-else-if="detail">
      <div class="mgmt-card">
        <h3>{{ $t('management.product.title') }}</h3>
        <dl class="mgmt-info-grid">
          <div class="mgmt-info-item">
            <dt>{{ $t('management.common.code') }}</dt>
            <dd>{{ detail.code }}</dd>
          </div>
          <div class="mgmt-info-item">
            <dt>{{ $t('management.product.product_type') }}</dt>
            <dd>{{ detail.product_type === 'CUSTOM'
              ? $t('management.product.type_custom')
              : $t('management.product.type_ootb') }}</dd>
          </div>
          <div v-if="detail.product_type === 'CUSTOM'" class="mgmt-info-item full">
            <dt>{{ $t('management.product.baseline_product') }}</dt>
            <dd>
              <a
                v-if="detail.baseline_product_id"
                class="mgmt-link"
                href="javascript:void(0)"
                @click="openProduct(detail.baseline_product_id)"
              >{{ detail.baseline_product_name || '-' }}</a>
              <template v-else>{{ detail.baseline_product_name || '-' }}</template>
            </dd>
          </div>
          <div class="mgmt-info-item full">
            <dt>{{ $t('management.product.description') }}</dt>
            <dd>{{ detail.description || '-' }}</dd>
          </div>
        </dl>
      </div>

      <div v-if="detail.custom_products && detail.custom_products.length > 0" class="mgmt-card mgmt-compact-card">
        <div class="mgmt-compact-head">
          <div>
            <h3>{{ $t('management.product.custom_products_title') }}</h3>
            <p class="mgmt-hint">{{ $t('management.product.custom_products_hint') }}</p>
          </div>
          <button class="btn-secondary" @click="customProductsVisible = true">
            {{ $t('management.product.view_custom_products', { count: detail.custom_products.length }) }}
          </button>
        </div>
      </div>

      <div class="mgmt-card mgmt-compact-card">
        <div class="mgmt-compact-head">
          <div>
            <h3>{{ $t('management.product.base_repos_title') }}</h3>
            <p class="mgmt-hint">
              {{ $t('management.product.base_repos_count', { count: detail.base_repos.length }) }}
            </p>
          </div>
          <button class="btn-secondary" @click="baseReposVisible = true">
            {{ $t('management.product.view_base_repos') }}
          </button>
        </div>
      </div>

      <ProductVersionsPanel
        :product="detail"
        :can-manage="canManage"
        :focus-version-id="focusVersionId"
        @changed="onBindingsChanged"
      />

      <ProductFormModal
        :show="showEdit"
        :product="detail"
        @saved="onProductSaved"
        @cancel="showEdit = false"
      />
    </template>

    <Teleport to="body">
      <div v-if="baseReposVisible" class="mgmt-modal-overlay" @pointerdown.self="baseReposVisible = false">
        <div class="mgmt-modal mgmt-modal-wide glass-panel">
          <ProductBaseReposPanel
            :product="detail"
            :can-manage="canManage"
            @changed="onBindingsChanged"
          />
          <div class="mgmt-modal-actions">
            <button class="btn-secondary" @click="baseReposVisible = false">
              {{ $t('common.close') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="customProductsVisible && detail" class="mgmt-modal-overlay" @pointerdown.self="customProductsVisible = false">
        <div class="mgmt-modal mgmt-modal-wide glass-panel">
          <h3>{{ $t('management.product.custom_products_title') }}</h3>
          <p class="mgmt-hint">{{ $t('management.product.custom_products_hint') }}</p>
          <div class="mgmt-modal-list">
            <a
              v-for="cp in detail.custom_products ?? []"
              :key="cp.id"
              class="mgmt-modal-list-item"
              href="javascript:void(0)"
              @click="openProduct(cp.id)"
            >
              <span class="mgmt-modal-list-name">{{ cp.name }}</span>
              <span class="mgmt-modal-list-sub">{{ cp.code }} {{ cp.version_no ? '· ' + cp.version_no : '' }}</span>
            </a>
            <div v-if="!(detail.custom_products ?? []).length" class="mgmt-empty">
              {{ $t('management.common.empty') }}
            </div>
          </div>
          <div class="mgmt-modal-actions">
            <button class="btn-secondary" @click="customProductsVisible = false">
              {{ $t('common.close') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.mgmt-back {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.5rem;
  padding: 0.4rem 0.9rem;
  font-size: 0.82rem;
  font-weight: 500;
  color: var(--color-primary-600);
  background: var(--color-surface-white);
  border: 1px solid var(--color-primary-100);
  border-radius: 8px;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.mgmt-back:hover {
  background: var(--color-primary-50);
  border-color: var(--color-primary-100);
}

.mgmt-detail-title {
  margin-top: 0.25rem;
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
}

/* h2 渐变文字（background-clip: text）会把 -webkit-text-fill-color: transparent
   继承给内部徽标/气泡，覆盖其自身 color，导致文字不可见；此处恢复为 currentColor */
.mgmt-detail-title .mgmt-status-pill {
  -webkit-text-fill-color: currentColor;
}

.mgmt-mode-badge {
  display: inline-block;
  font-size: 0.72rem;
  font-weight: 600;
  border-radius: 6px;
  padding: 0.1rem 0.5rem;
  margin-left: 0.5rem;
  vertical-align: middle;
}

.mgmt-mode-badge.view {
  color: #64748b;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
}

.mgmt-mode-badge.edit {
  color: #b45309;
  background: #fffbeb;
  border: 1px solid #fde68a;
}

.mgmt-info-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem 1.5rem;
  margin: 0;
}

.mgmt-info-item.full {
  grid-column: 1 / -1;
}

.mgmt-info-item dt {
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 0.2rem;
}

.mgmt-info-item dd {
  margin: 0;
  color: #334155;
  font-size: 0.92rem;
  word-break: break-word;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}

.mgmt-compact-card {
  margin-bottom: 1rem;
}

.mgmt-compact-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.mgmt-compact-head h3 {
  margin: 0 0 0.25rem;
}

.mgmt-modal-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-top: 0.75rem;
  max-height: 50vh;
  overflow-y: auto;
}

.mgmt-modal-list-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.55rem 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  color: #334155;
  cursor: pointer;
  text-decoration: none;
  transition: border-color var(--transition-fast), background var(--transition-fast);
}

.mgmt-modal-list-item:hover {
  border-color: #93c5fd;
  background: #eff6ff;
}

.mgmt-modal-list-name {
  font-weight: 600;
  color: #1d4ed8;
}

.mgmt-modal-list-sub {
  font-size: 0.78rem;
  color: #64748b;
}

.mgmt-modal-wide {
  max-width: 760px;
  max-height: 88vh;
  overflow-y: auto;
}
</style>
