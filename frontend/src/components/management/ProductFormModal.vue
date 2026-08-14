<!--
ProductFormModal: create / edit product form. Product carries its own
version_no / release_date and is bound to repositories directly.
-->
<script setup lang="ts">
import { reactive, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { ElMessage } from 'element-plus';
import BaseSelect from '@/components/BaseSelect.vue';
import { createProduct, updateProduct } from '@/services/managementApi';
import { formatApiError } from '@/utils/error';
import type { Product, ProductStatus } from '@/types/management';

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
  product_line: '',
  version_no: '',
  release_date: '',
  description: '',
  status: 'ACTIVE' as ProductStatus,
});

const loading = ref(false);

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
    form.product_line = props.product?.product_line ?? '';
    form.version_no = props.product?.version_no ?? '';
    form.release_date = props.product?.release_date?.slice(0, 10) ?? '';
    form.description = props.product?.description ?? '';
    form.status = props.product?.status ?? 'ACTIVE';
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
      product_line: form.product_line.trim() || null,
      version_no: form.version_no.trim() || undefined,
      release_date: form.release_date || null,
      description: form.description.trim() || null,
    };
    let saved: Product;
    if (props.product) {
      saved = await updateProduct(props.product.id, { ...payload, version_no: form.version_no.trim(), status: form.status });
    } else {
      saved = await createProduct({ ...payload, version_no: form.version_no.trim(), status: form.status });
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
          <label>{{ $t('management.product.product_line') }}</label>
          <input v-model="form.product_line" class="mgmt-input" type="text" />
        </div>
        <div class="mgmt-field">
          <label>{{ $t('management.product.version_no') }}</label>
          <input v-model="form.version_no" class="mgmt-input" type="text" />
        </div>
        <div class="mgmt-field">
          <label>{{ $t('management.product.release_date') }}</label>
          <input v-model="form.release_date" class="mgmt-input" type="date" />
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
