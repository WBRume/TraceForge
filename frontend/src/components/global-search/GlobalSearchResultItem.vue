<script setup lang="ts">
import type { SearchItem } from '@/types/search'
defineProps<{ item: SearchItem; active: boolean }>()
defineEmits<{ select: [] }>()
</script>
<template>
  <button class="search-result" :class="{ active }" role="option" :aria-selected="active" tabindex="-1" @click="$emit('select')">
    <span class="result-location">{{ item.workspace_name }} / {{ item.task_name }} <small>{{ item.kind === 'task' ? '任务' : item.role === 'user' ? '用户' : 'AI' }}</small></span>
    <span class="result-snippet"><template v-for="(segment, i) in item.snippet" :key="i"><mark v-if="segment.match">{{ segment.text }}</mark><span v-else>{{ segment.text }}</span></template></span>
    <small v-if="item.snippet_basis === 'semantic'">语义相关</small>
  </button>
</template>
<style scoped>
.search-result { display: flex; flex-direction: column; gap: 7px; width: 100%; padding: 14px; text-align: left; border: 1px solid transparent; background: transparent; color: var(--el-text-color-primary); border-radius: 8px; cursor: pointer; }
.search-result.active, .search-result:hover { background: var(--el-fill-color-light); border-color: var(--el-color-primary); }
.result-location { font-weight: 600; font-size: 13px; }
.result-location small { margin-left: 8px; font-weight: 400; }
.result-snippet { font-size: 13px; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; }
mark { background: var(--el-color-warning-light-5); color: inherit; }
</style>
