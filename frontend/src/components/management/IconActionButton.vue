<!-- Unified icon action button for management tables/detail headers. -->
<script setup lang="ts">
import { Loader2 } from 'lucide-vue-next'
import type { Component } from 'vue'

withDefaults(defineProps<{
  icon: Component
  title: string
  disabled?: boolean
  loading?: boolean
  tone?: 'default' | 'danger' | 'primary'
}>(), {
  disabled: false,
  loading: false,
  tone: 'default',
})

defineEmits<{
  (e: 'click', event: MouseEvent): void
}>()
</script>

<template>
  <button
    type="button"
    class="mgmt-icon-btn"
    :class="[tone, { 'is-disabled': disabled }]"
    :title="title"
    :disabled="disabled || loading"
    @click.stop="$emit('click', $event)"
  >
    <Loader2 v-if="loading" class="w-4 h-4 spin" />
    <component :is="icon" v-else class="w-4 h-4" />
  </button>
</template>

<style scoped>
.mgmt-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: rgba(255, 255, 255, 0.85);
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
}

.mgmt-icon-btn:hover:not(:disabled) {
  border-color: #0ea5e9;
  color: #0ea5e9;
  background: #f0f9ff;
}

.mgmt-icon-btn.danger:hover:not(:disabled) {
  border-color: #f87171;
  color: #dc2626;
  background: #fef2f2;
}

.mgmt-icon-btn.primary {
  border-color: #bfdbfe;
  color: #1d4ed8;
  background: #eff6ff;
}

.mgmt-icon-btn.primary:hover:not(:disabled) {
  border-color: #0ea5e9;
  color: #0ea5e9;
}

.mgmt-icon-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
