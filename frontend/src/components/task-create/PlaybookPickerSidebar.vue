<script setup lang="ts">
import { watch } from 'vue'
import { BookOpen, Loader2, RefreshCw, Search } from 'lucide-vue-next'
import SidebarPanel from './SidebarPanel.vue'
import { useTaskPlaybookPicker } from './composables/useTaskPlaybookPicker'
import type { PlaybookSpec } from '@/types/diagnosisPlaybook'

const props = defineProps<{
  workspaceId: string; open: boolean; name: string; description: string
  taskType: 'DEVELOPMENT' | 'DIAGNOSIS'; disabled?: boolean
}>()
const emit = defineEmits<{ close: [] }>()
const model = defineModel<PlaybookSpec | null>({ default: null })
const { items, keyword, page, total, totalPages, loading, error, refresh } = useTaskPlaybookPicker({
  open: () => props.open, workspaceId: () => props.workspaceId, name: () => props.name,
  description: () => props.description, taskType: () => props.taskType,
})
watch(() => props.workspaceId, () => { model.value = null })

const prevPage = () => {
  if (page.value > 1 && !loading.value) {
    page.value--
  }
}

const nextPage = () => {
  if (page.value < totalPages.value && !loading.value) {
    page.value++
  }
}
</script>

<template>
  <SidebarPanel :open="open" :badge="model ? '已选 1 项' : '未选择'" :badge-active="!!model"
    subtitle="根据任务标题和描述推荐，复用案例中的调用链与排查经验。" @close="emit('close')">
    <template #title><div class="skills-sidebar-title"><BookOpen class="w-4 h-4 text-primary" /><h3>诊断规程</h3></div></template>
    <template #tools>
      <div class="skills-sidebar-tools">
        <div class="skills-search-wrapper"><Search class="w-4 h-4 skills-search-icon" />
          <input v-model="keyword" type="search" class="skills-search-input" placeholder="搜索名称、症状、调用链" aria-label="搜索诊断规程" />
        </div>
        <button type="button" class="tool-icon-btn" :disabled="loading" title="刷新规程" @click="refresh"><RefreshCw class="w-3.5 h-3.5" :class="{ spin: loading }" /></button>
      </div>
    </template>
    <template v-if="model" #notice>
      <div class="selection-note">已选：{{ model.title }} <button type="button" class="tool-text-btn" :disabled="disabled" @click="model = null">取消选择</button></div>
    </template>
    <p v-if="error" role="alert">{{ error }} <button type="button" class="tool-text-btn" @click="refresh">重试</button></p>
    <div v-else-if="loading" class="skills-state center" role="status"><Loader2 class="w-5 h-5 spin" />正在匹配规程…</div>
    <p v-else-if="!items.length" class="skills-state center">{{ keyword ? '没有匹配的规程，请调整搜索条件。' : '暂无规程，可从案例库多选晋升；也可不选直接创建任务。' }}</p>
    <ul v-else class="guide-list">
      <li v-for="item in items" :key="item.id" class="guide-item" :class="{ selected: model?.id === item.id }">
        <label><input type="radio" :checked="model?.id === item.id" :disabled="disabled" name="diagnosis-playbook" @change="model = item" /><strong>{{ item.title }}</strong><span v-if="item.score > 0" class="recommend-badge">推荐</span></label>
        <p class="version">{{ item.version }}</p>
        <p v-if="item.reasons.length">匹配：{{ item.reasons.join('、') }}</p>
        <p v-else>可作为本次任务的分析参考</p>
        <a v-for="id in item.source_case_refs" :key="id" :href="`/workspaces/${workspaceId}/cases/${id}`" target="_blank" rel="noopener">查看来源案例</a>
      </li>
    </ul>
    <!-- 服务端分页底部栏（与 skills 配置侧栏风格完全一致） -->
    <template #footer>
      <button
        type="button"
        class="btn-secondary mini page-nav-btn"
        :disabled="page <= 1 || loading"
        @click="prevPage"
      >
        {{ $t('skills.list.prev_page') }}
      </button>
      <div class="pagination-info">
        <span class="skills-page-info">
          {{ $t('skills.list.page_info', { page, total: totalPages }) }}
        </span>
        <span class="pagination-badge">{{ total }}</span>
      </div>
      <button
        type="button"
        class="btn-secondary mini page-nav-btn"
        :disabled="page >= totalPages || loading"
        @click="nextPage"
      >
        {{ $t('skills.list.next_page') }}
      </button>
    </template>
  </SidebarPanel>
</template>

<style scoped src="@/styles/task-create/task-create-shared.css"></style>
<style scoped>
.guide-list { padding:0; margin:0; list-style:none; display:flex; flex-direction:column; gap:8px }
.guide-item { border:1px solid #e2e8f0; border-radius:10px; background:white; padding:10px; font-size:13px }
.guide-item.selected { border-color:#0ea5e9; background:#f0f9ff }
label { display:flex; align-items:baseline; gap:8px; cursor:pointer } strong { flex:1; overflow-wrap:anywhere }
p { color:#64748b; font-size:12px; margin:6px 0; overflow-wrap:anywhere }
a { color:#0284c7; font-size:12px } .selection-note { font-size:12px; padding:10px 16px; overflow-wrap:anywhere }
.recommend-badge { color:#0284c7; font-size:11px; flex-shrink:0 } .version { overflow-wrap:anywhere }
</style>
