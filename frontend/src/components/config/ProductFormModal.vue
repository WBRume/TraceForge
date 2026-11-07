<!--
ProductFormModal: create / edit product form. Products start without versions;
versions are created later from the product's base repository pool.
-->
<script setup lang="ts">
import { reactive, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { ElMessage } from 'element-plus';
import BaseSelect from '@/components/BaseSelect.vue';
import { createProduct, listProducts, updateProduct } from '@/services/managementApi';
import { formatApiError } from '@/utils/error';
import type { Product, ProductStatus, ProductType } from '@/types/management';

const props = defineProps<{
  show: boolean;
  product?: Product | null;
}>();

const emit = defineEmits<{
  (e: 'saved', product: Product): void;
  (e: 'cancel'): void;
}>();

const { t } = useI18n();

const isEdit = () => Boolean(props.product);

const form = reactive({
  name: '',
  code: '',
  description: '',
  status: 'ACTIVE' as ProductStatus,
  product_type: 'OOTB' as ProductType,
  baseline_product_id: null as string | null,
});

const loading = ref(false);
const baselineProducts = ref<Product[]>([]);

const typeOptions = (): { label: string; value: ProductType }[] => [
  { label: t('management.product.type_ootb'), value: 'OOTB' },
  { label: t('management.product.type_custom'), value: 'CUSTOM' },
];

const baselineOptions = (): { label: string; value: string }[] =>
  baselineProducts.value.map((p) => ({ label: p.name, value: p.id }));

const loadBaselineProducts = async () => {
  try {
    const res = await listProducts({ page_size: 100, status: 'ACTIVE' });
    baselineProducts.value = (res.items ?? []).filter((p) => p.product_type === 'OOTB');
  } catch {
    baselineProducts.value = [];
  }
};

const statusOptions = (): { label: string; value: ProductStatus }[] => [
  { label: t('management.product.status_active'), value: 'ACTIVE' },
  { label: t('management.product.status_archived'), value: 'ARCHIVED' },
];

watch(
  () => props.show,
  (visible) => {
    if (!visible) return;
    form.name = props.product?.name ?? '';
    form.code = props.product?.code ?? '';
    // 产品创建时不带版本；版本在研发/发布流程中另行创建。
    form.description = props.product?.description ?? '';
    form.status = props.product?.status ?? 'ACTIVE';
    form.product_type = props.product?.product_type ?? 'OOTB';
    form.baseline_product_id = props.product?.baseline_product_id ?? null;
    if (visible) {
      void loadBaselineProducts();
    }
  },
);

const submit = async () => {
  if (!form.name.trim()) {
    ElMessage.warning(t('management.common.required'));
    return;
  }
  if (!form.code.trim()) {
    ElMessage.warning(t('management.common.required'));
    return;
  }

  loading.value = true;
  try {
    const payload = {
      name: form.name.trim(),
      code: form.code.trim(),
      description: form.description.trim() || null,
      product_type: form.product_type,
      baseline_product_id: form.product_type === 'CUSTOM' ? form.baseline_product_id : null,
    };
    let saved: Product;
    if (props.product) {
      saved = await updateProduct(props.product.id, {
        name: payload.name,
        code: payload.code,
        description: payload.description,
        status: form.status,
        product_type: payload.product_type,
        baseline_product_id: payload.baseline_product_id,
      });
    } else {
      saved = await createProduct(payload);
    }
    emit('saved', saved);
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t));
  } finally {
    loading.value = false;
  }
};
</script>

<template>
  <div v-if="show" class="mgmt-modal-overlay" @pointerdown.self="emit('cancel')">
    <div class="mgmt-modal glass-panel">
      <h3>{{ isEdit() ? $t('management.product.edit') : $t('management.product.create') }}</h3>

      <div class="mgmt-form-grid">
        <div class="mgmt-field">
          <label>{{ $t('management.product.name') }}</label>
          <input v-model="form.name" class="mgmt-input" type="text" />
        </div>
        <div class="mgmt-field">
          <label>{{ $t('management.product.code') }}</label>
          <input v-model="form.code" class="mgmt-input" type="text" />
        </div>
        <div class="mgmt-field">
          <label>{{ $t('management.product.product_type') }}</label>
          <BaseSelect v-model="form.product_type" :options="typeOptions()" />
        </div>
        <div v-if="form.product_type === 'CUSTOM'" class="mgmt-field">
          <label>{{ $t('management.product.baseline_product') }}</label>
          <BaseSelect v-model="form.baseline_product_id" :options="baselineOptions()" :placeholder="$t('management.product.select_baseline_product')" />
        </div>
        <div v-if="isEdit()" class="mgmt-field">
          <label>{{ $t('management.common.status') }}</label>
          <BaseSelect v-model="form.status" :options="statusOptions()" />
        </div>
        <div class="mgmt-field full">
          <label>{{ $t('management.product.description') }}</label>
          <textarea v-model="form.description" class="mgmt-input" rows="3"></textarea>
        </div>
      </div>

      <div class="mgmt-modal-actions">
        <button class="btn-secondary" :disabled="loading" @click="emit('cancel')">
          {{ $t('common.cancel') }}
        </button>
        <button class="btn-primary" :disabled="loading" @click="submit">
          {{ loading ? $t('management.common.saving') : $t('management.common.save') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
