<script setup lang="ts">
import { ChevronLeft, ChevronRight } from '@/components/icons'

defineProps<{ total: number; previousLabel: string; nextLabel: string }>()
const page = defineModel<number>({ required: true })
</script>

<template>
  <div v-if="total > 0" class="preview-pager">
    <button type="button" :aria-label="previousLabel" :title="previousLabel" :disabled="page <= 1" @click="page--">
      <ChevronLeft :size="16" />
    </button>
    <span aria-live="polite">{{ page }} / {{ total }}</span>
    <button type="button" :aria-label="nextLabel" :title="nextLabel" :disabled="page >= total" @click="page++">
      <ChevronRight :size="16" />
    </button>
  </div>
</template>

<style scoped>
.preview-pager { display: inline-flex; align-items: center; gap: 4px; font-variant-numeric: tabular-nums; }
.preview-pager span { min-width: 48px; text-align: center; }
.preview-pager button { display: grid; place-items: center; width: 28px; height: 28px; background: #fff; border: 1px solid #e2e8f0; border-radius: 6px; color: #475569; cursor: pointer; }
.preview-pager button:hover:not(:disabled) { color: #0284c7; background: #f0f9ff; }
.preview-pager button:disabled { opacity: .45; cursor: default; }
</style>
