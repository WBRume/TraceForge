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
import ProductFormModal from '@/components/management/ProductFormModal.vue';
import ProductRepoBindingPanel from '@/components/management/ProductRepoBindingPanel.vue';
import { getProduct } from '@/services/managementApi';
import { formatApiError } from '@/utils/error';
import { useAuthStore } from '@/stores/auth';
import type { ProductDetail } from '@/types/management';

const route = useRoute();
const router = useRouter();
const { t } = useI18n();
const authStore = useAuthStore();

const productId = computed(() => String(route.params.productId ?? ''));

const isAdmin = computed(() => Boolean(authStore.user?.is_admin));

const detail = ref<ProductDetail | null>(null);
const loading = ref(false);

const showEdit = ref(false);

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
          <span class="mgmt-version-badge">{{ detail.version_no }}</span>
          <span
            class="mgmt-status-pill"
            :class="detail.status === 'ACTIVE' ? 'green' : 'gray'"
          >
            {{ detail.status === 'ACTIVE'
              ? $t('management.product.status_active')
              : $t('management.product.status_archived') }}
          </span>
        </h2>
        <p v-if="detail" class="mgmt-subtitle">{{ detail.code }}</p>
      </div>
      <AdminGuard>
        <button v-if="detail" class="btn-secondary" @click="showEdit = true">
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
            <dt>{{ $t('management.product.product_line') }}</dt>
            <dd>{{ detail.product_line || '-' }}</dd>
          </div>
          <div class="mgmt-info-item">
            <dt>{{ $t('management.product.version_no') }}</dt>
            <dd>{{ detail.version_no || '-' }}</dd>
          </div>
          <div class="mgmt-info-item">
            <dt>{{ $t('management.product.release_date') }}</dt>
            <dd>{{ detail.release_date ? detail.release_date.slice(0, 10) : '-' }}</dd>
          </div>
          <div class="mgmt-info-item full">
            <dt>{{ $t('management.product.description') }}</dt>
            <dd>{{ detail.description || '-' }}</dd>
          </div>
        </dl>
      </div>

      <ProductRepoBindingPanel
        :product="detail"
        :can-manage="isAdmin"
        @changed="onBindingsChanged"
      />

      <ProductFormModal
        :show="showEdit"
        :product="detail"
        @saved="onProductSaved"
        @cancel="showEdit = false"
      />
    </template>
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
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
}

.mgmt-version-badge {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.8rem;
  font-weight: 700;
  color: #1d4ed8;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 6px;
  padding: 0.1rem 0.5rem;
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
</style>
