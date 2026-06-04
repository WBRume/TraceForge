<script setup lang="ts">
import { Loader2, Trash2 } from 'lucide-vue-next'

type Mode = 'icon' | 'mini'

withDefaults(defineProps<{
  mode?: Mode
  label?: string
  title?: string
  disabled?: boolean
  loading?: boolean
}>(), {
  mode: 'icon',
  label: '',
  title: '',
  disabled: false,
  loading: false,
})

const emit = defineEmits<{
  (e: 'click', event: MouseEvent): void
}>()

const handleClick = (event: MouseEvent) => {
  emit('click', event)
}
</script>

<template>
  <button
    class="delete-action-btn"
    :class="[`is-${mode}`]"
    :title="title || undefined"
    :disabled="disabled || loading"
    @click="handleClick"
  >
    <Loader2 v-if="loading" class="icon spin" />
    <Trash2 v-else class="icon" />
    <span v-if="mode === 'mini'">{{ label }}</span>
  </button>
</template>

<style scoped>
.delete-action-btn {
  border: none;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.delete-action-btn.is-icon {
  background: #f1f5f9;
  color: #94a3b8;
  padding: 6px;
  border-radius: 8px;
}

.delete-action-btn.is-icon:hover:not(:disabled) {
  background: #ef4444;
  color: #fff;
  box-shadow: 0 4px 12px rgba(239, 68, 68, 0.3);
  transform: translateY(-1px);
}

.delete-action-btn.is-mini {
  gap: 0.35rem;
  padding: 0.3rem 0.6rem;
  font-size: 0.75rem;
  border-radius: 8px;
  border: 1px solid #fecaca;
  background: #fff1f2;
  color: #be123c;
}

.delete-action-btn.is-mini:hover:not(:disabled) {
  background: #ffe4e6;
  border-color: #fda4af;
}

.delete-action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.icon {
  width: 0.85rem;
  height: 0.85rem;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
