<script setup lang="ts">
import { computed } from 'vue'
import BaseSelect from '@/components/BaseSelect.vue'

const props = defineProps<{
  total: number
  page: number
  pageCount: number
  loading: boolean
  label: string
  pageSize?: number
}>()
const emit = defineEmits<{
  change: [page: number]
  'update:pageSize': [size: number]
}>()
const sizeOptions = computed(() => [20, 50, 100].map(value => ({ value, label: `${value} 条 / 页` })))
</script>

<template>
  <nav v-if="total > 0" class="library-pagination" :aria-label="label">
    <span>共 {{ total }} 条</span>
    <BaseSelect
      v-if="pageSize !== undefined"
      :model-value="pageSize"
      :options="sizeOptions"
      :disabled="loading"
      size="sm"
      drop-up
      class="page-size-select"
      aria-label="每页条数"
      @update:model-value="emit('update:pageSize', Number($event))"
    />
    <button type="button" class="btn-secondary" :disabled="loading || page <= 1" @click="emit('change', page - 1)">上一页</button>
    <span aria-live="polite">{{ page }} / {{ pageCount }}</span>
    <button type="button" class="btn-secondary" :disabled="loading || page >= pageCount" @click="emit('change', page + 1)">下一页</button>
  </nav>
</template>

<style scoped>
.library-pagination { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 12px; }
.page-size-select { width: 130px; }
</style>
