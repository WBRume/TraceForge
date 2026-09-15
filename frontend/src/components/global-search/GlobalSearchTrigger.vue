<script setup lang="ts">
import { Search } from 'lucide-vue-next'
import { useGlobalSearchStore } from '@/stores/globalSearch'

withDefaults(
  defineProps<{
    compact?: boolean
  }>(),
  {
    compact: false,
  }
)

const searchStore = useGlobalSearchStore()
</script>

<template>
  <button
    v-if="searchStore.enabled"
    type="button"
    class="global-search-trigger-btn"
    :class="{ 'is-compact': compact }"
    title="搜索任务与历史消息（双击 Shift）"
    @click="searchStore.openSearch"
  >
    <Search class="search-icon" />
    <span v-if="!compact" class="search-label">搜索</span>
    <kbd v-if="!compact" class="search-kbd">Shift × 2</kbd>
  </button>
</template>

<style scoped>
.global-search-trigger-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  padding: 0.45rem 0.85rem;
  border-radius: 8px;
  color: #475569;
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  line-height: 1;
  flex-shrink: 0;
  user-select: none;
}

.global-search-trigger-btn:hover {
  background: #f8fafc;
  border-color: #0ea5e9;
  color: #0ea5e9;
}

.search-icon {
  width: 14px;
  height: 14px;
  color: #64748b;
  flex-shrink: 0;
  transition: color 0.2s;
}

.global-search-trigger-btn:hover .search-icon {
  color: #0ea5e9;
}

.search-label {
  font-size: 0.8125rem;
}

.search-kbd {
  font-size: 10.5px;
  font-family: inherit;
  font-weight: 500;
  color: #64748b;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  padding: 2px 5px;
  line-height: 1;
}

/* 紧凑模式：适配工具栏按钮组 */
.global-search-trigger-btn.is-compact {
  padding: 6px;
  width: 32px;
  height: 32px;
  justify-content: center;
  border-radius: 6px;
}

.global-search-trigger-btn.is-compact .search-icon {
  width: 15px;
  height: 15px;
}
</style>
