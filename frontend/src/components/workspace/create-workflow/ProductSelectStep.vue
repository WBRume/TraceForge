<!-- Workspace creation workflow: step 3 product selection. -->
<script setup lang="ts">
import { Package } from 'lucide-vue-next'
import type { ProjectProduct } from '@/types/management'

const props = defineProps<{
  modelValue: string | null
  products: ProjectProduct[]
  loading: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string | null): void
}>()

const toggle = (productId: string) => {
  emit('update:modelValue', props.modelValue === productId ? null : productId)
}
</script>

<template>
  <div class="wf-step">
    <p class="mgmt-hint">{{ $t('workspace_create.products_hint') }}</p>

    <div v-if="loading" class="mgmt-empty">{{ $t('management.common.loading') }}</div>

    <div v-else-if="products.length === 0" class="mgmt-empty">
      {{ $t('workspace_create.no_products_hint') }}
    </div>

    <div v-else class="wf-product-grid">
      <label v-for="product in products" :key="product.id" class="wf-product-card" :class="{ selected: modelValue === product.product_id }">
        <input
          type="radio"
          name="workspace-product"
          class="wf-checkbox"
          :checked="modelValue === product.product_id"
          @change="toggle(product.product_id)"
        />
        <div class="wf-product-title-row">
          <Package class="w-4 h-4 text-primary" />
          <span class="wf-product-title">{{ product.product_name }}</span>
        </div>
        <div class="wf-product-meta">{{ product.product_code }}</div>
        <div class="wf-product-meta">
          {{ $t('management.project.product_version_label') }}: {{ product.product_version_no || '-' }}
        </div>
      </label>
    </div>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
<style scoped>
.wf-step {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}

.wf-product-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
  max-height: 300px;
  overflow-y: auto;
}

.wf-product-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  border: 1.5px solid #e2e8f0;
  background: rgba(255, 255, 255, 0.85);
  border-radius: 12px;
  padding: 0.9rem 1rem 0.9rem 2.2rem;
  cursor: pointer;
  transition: all 0.2s;
}

.wf-product-card:hover {
  border-color: #7dd3fc;
  background: #f0f9ff;
}

.wf-product-card.selected {
  border-color: #0ea5e9;
  background: #f0f9ff;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.12);
}

.wf-checkbox {
  position: absolute;
  left: 0.8rem;
  top: 1rem;
  width: 1rem;
  height: 1rem;
  accent-color: #0ea5e9;
}

.wf-product-title-row {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}

.wf-product-title {
  font-weight: 600;
  color: #0f172a;
  font-size: 0.92rem;
}

.wf-product-meta {
  font-size: 0.78rem;
  color: #64748b;
}

.text-primary {
  color: var(--color-primary-600);
}
</style>
