<script setup lang="ts">
import { shallowRef, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElDialog, ElSelect, ElOption, ElButton } from 'element-plus'
import { useGlobalSearch } from '@/composables/useGlobalSearch'
import GlobalSearchResultItem from './GlobalSearchResultItem.vue'
import type { SearchCapabilities, SearchItem } from '@/types/search'
const open = defineModel<boolean>({ required: true })
defineProps<{ capabilities: SearchCapabilities }>()
const router = useRouter()
const state = useGlobalSearch(open)
const { query, retrieval, kind, composing, loading, error, items, response } = state
const active = shallowRef(0)
const input = shallowRef<HTMLInputElement>()
const choose = async (item?: SearchItem) => {
  if (!item) return
  open.value = false
  await router.push({ name: item.target.route_name, params: item.target.params, query: item.target.query })
}
watch(items, () => { active.value = 0 })
watch(open, value => { if (!value) query.value = '' })
const move = (delta: number) => {
  if (!items.value.length) return
  active.value = (active.value + delta + items.value.length) % items.value.length
  void nextTick(() => document.getElementById(`global-search-result-${active.value}`)?.scrollIntoView({ block: 'nearest' }))
}
</script>
<template>
  <ElDialog v-model="open" title="搜索任务与历史消息" width="min(720px, 94vw)" append-to-body destroy-on-close @opened="input?.focus()">
    <div>
      <input ref="input" v-model="query" class="search-query" maxlength="200" placeholder="搜索中文、函数名或描述问题…" aria-label="搜索任务与历史消息" role="combobox" aria-controls="global-search-results" :aria-expanded="items.length > 0" :aria-activedescendant="items.length ? `global-search-result-${active}` : undefined" @compositionstart="composing = true" @compositionend="composing = false" @keydown.down.prevent="move(1)" @keydown.up.prevent="move(-1)" @keydown.enter="!composing && !$event.isComposing && choose(items[active])" />
      <div class="search-filters">
        <ElSelect v-model="retrieval" aria-label="检索模式" style="width: 130px"><ElOption value="hybrid" label="混合检索" /><ElOption value="lexical" label="关键词" /></ElSelect>
        <ElSelect v-model="kind" aria-label="结果类型" style="width: 110px"><ElOption value="all" label="全部" /><ElOption value="task" label="任务" /><ElOption value="message" label="消息" /></ElSelect>
        <small>↑ ↓ 选择 · Enter 打开</small>
      </div>
      <p v-if="!capabilities.ready" role="status">历史索引正在准备，搜索暂不可用。</p>
      <p v-else-if="retrieval === 'hybrid' && !capabilities.hybrid_available" role="status">混合检索尚不可用，可选择关键词模式。</p>
      <p v-if="error" role="alert">{{ error }} <ElButton link @click="state.execute()">重试</ElButton></p>
      <p v-if="response?.degraded_reason" role="status">语义服务暂不可用，本次已使用关键词检索。</p>
      <p v-if="response?.indexing_state === 'partial'" role="status">历史正在建立索引，当前结果可能不完整。</p>
      <div id="global-search-results" class="search-results" role="listbox" aria-label="搜索结果" :aria-busy="loading">
        <GlobalSearchResultItem v-for="(item, i) in items" :id="`global-search-result-${i}`" :key="item.entity_key" :item="item" :active="active === i" @select="choose(item)" />
      </div>
      <p v-if="loading" role="status">正在搜索…</p>
      <p v-else-if="response && !items.length">未找到可访问的结果。</p>
      <p v-else-if="query.trim().length < 2">输入至少两个字符开始搜索。</p>
      <ElButton v-if="response?.has_more" :loading="loading" @click="state.execute(true)">加载更多</ElButton>
      <p v-if="response?.result_window_exhausted">已到达本次结果窗口上限，请缩小搜索范围。</p>
    </div>
  </ElDialog>
</template>
<style scoped>
.search-filters { display: flex; align-items: center; gap: 10px; margin: 14px 0; flex-wrap: wrap; }
.search-filters small { margin-left: auto; color: var(--el-text-color-secondary); }
.search-results { max-height: 52vh; overflow-y: auto; }
.search-query { box-sizing: border-box; width: 100%; padding: 9px 12px; border: 1px solid var(--el-border-color); border-radius: 5px; background: var(--el-bg-color); color: var(--el-text-color-primary); font: inherit; }
.search-query:focus { outline: 2px solid var(--el-color-primary-light-5); border-color: var(--el-color-primary); }
p { font-size: 13px; color: var(--el-text-color-secondary); }
</style>
