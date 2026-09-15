<script setup lang="ts">
import { ref, shallowRef, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { Search, X, Loader2, Sparkles, AlertTriangle } from 'lucide-vue-next'
import { useGlobalSearch } from '@/composables/useGlobalSearch'
import BaseSelect from '@/components/BaseSelect.vue'
import GlobalSearchResultItem from './GlobalSearchResultItem.vue'
import type { SearchCapabilities, SearchItem } from '@/types/search'

const open = defineModel<boolean>({ required: true })
defineProps<{ capabilities: SearchCapabilities }>()

const router = useRouter()
const state = useGlobalSearch(open)
const { query, retrieval, kind, composing, loading, error, items, response } = state

const active = shallowRef(0)
const input = shallowRef<HTMLInputElement>()
const overlayCloseArmed = ref(false)

const retrievalOptions = [
  { value: 'hybrid', label: '混合检索' },
  { value: 'lexical', label: '关键词' },
]

const kindOptions = [
  { value: 'all', label: '全部' },
  { value: 'task', label: '任务' },
  { value: 'message', label: '消息' },
]

const choose = async (item?: SearchItem) => {
  if (!item) return
  open.value = false
  await router.push({
    name: item.target.route_name,
    params: item.target.params,
    query: item.target.query,
  })
}

watch(items, () => {
  active.value = 0
})

watch(open, (value) => {
  if (value) {
    void nextTick(() => input.value?.focus())
  } else {
    query.value = ''
  }
})

const move = (delta: number) => {
  if (!items.value.length) return
  active.value = (active.value + delta + items.value.length) % items.value.length
  void nextTick(() => {
    document.getElementById(`global-search-result-${active.value}`)?.scrollIntoView({ block: 'nearest' })
  })
}

const clearQuery = () => {
  query.value = ''
  input.value?.focus()
}

// 蒙层安全关闭判断
const armOverlayClose = (event: PointerEvent) => {
  if (event.button !== 0) return
  overlayCloseArmed.value = true
}

const cancelOverlayClose = () => {
  overlayCloseArmed.value = false
}

const finishOverlayClose = () => {
  if (!overlayCloseArmed.value) return
  overlayCloseArmed.value = false
  open.value = false
}

const handleGlobalKeyDown = (e: KeyboardEvent) => {
  if (!open.value) return
  if (e.key === 'Escape') {
    open.value = false
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleGlobalKeyDown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleGlobalKeyDown)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="search-fade">
      <div
        v-if="open"
        class="search-modal-overlay"
        @pointerdown.self="armOverlayClose"
        @pointerup.self="finishOverlayClose"
        @pointerleave.self="cancelOverlayClose"
        @pointercancel.self="cancelOverlayClose"
      >
        <div class="search-modal" role="dialog" aria-modal="true" aria-label="搜索任务与历史消息">
          <!-- 头部 Header：轻盈优雅 -->
          <header class="modal-header">
            <div class="header-title-group">
              <h3 class="header-title">搜索任务与历史消息</h3>
              <span class="header-subtitle">快速穿梭跨工作区的任务、会话与交流记录</span>
            </div>

            <div class="header-controls">
              <kbd class="shortcut-pill">Esc</kbd>
              <button
                type="button"
                class="modal-close-btn"
                title="关闭搜索 (Esc)"
                @click="open = false"
              >
                <X class="w-4 h-4" />
              </button>
            </div>
          </header>

          <!-- 搜索输入框容器 -->
          <div class="search-input-box">
            <Search class="input-search-icon" />
            <input
              ref="input"
              v-model="query"
              class="search-input"
              maxlength="200"
              placeholder="搜索中文、函数名或描述问题…"
              aria-label="搜索任务与历史消息"
              role="combobox"
              aria-controls="global-search-results"
              :aria-expanded="items.length > 0"
              :aria-activedescendant="items.length ? `global-search-result-${active}` : undefined"
              @compositionstart="composing = true"
              @compositionend="composing = false"
              @keydown.down.prevent="move(1)"
              @keydown.up.prevent="move(-1)"
              @keydown.enter="!composing && !$event.isComposing && choose(items[active])"
            />
            <button
              v-if="query"
              type="button"
              class="input-clear-btn"
              title="清空"
              @click="clearQuery"
            >
              <X class="w-3.5 h-3.5" />
            </button>
          </div>

          <!-- 过滤器栏：使用系统 BaseSelect 并提供按键说明 -->
          <div class="search-filters-bar">
            <div class="filters-select-group">
              <BaseSelect
                v-model="retrieval"
                :options="retrievalOptions"
                size="sm"
                class="filter-select"
                aria-label="检索模式"
              />
              <BaseSelect
                v-model="kind"
                :options="kindOptions"
                size="sm"
                class="filter-select"
                aria-label="结果类型"
              />
            </div>

            <div class="shortcuts-hint">
              <span class="hint-item">
                <kbd class="shortcut-pill">↑↓</kbd>
                <span>选择</span>
              </span>
              <span class="hint-item">
                <kbd class="shortcut-pill">↵</kbd>
                <span>打开</span>
              </span>
            </div>
          </div>

          <!-- 系统状态与降级提醒 -->
          <div v-if="!capabilities.ready" class="status-banner info" role="status">
            <Sparkles class="w-4 h-4 flex-shrink-0 text-sky-500" />
            <span>历史索引正在准备，搜索暂不可用。</span>
          </div>
          <div v-else-if="retrieval === 'hybrid' && !capabilities.hybrid_available" class="status-banner warning" role="status">
            <AlertTriangle class="w-4 h-4 flex-shrink-0 text-amber-500" />
            <span>混合检索尚不可用，可选择关键词模式。</span>
          </div>
          <div v-if="error" class="status-banner error" role="alert">
            <AlertTriangle class="w-4 h-4 flex-shrink-0 text-rose-500" />
            <span>{{ error }}</span>
            <button type="button" class="retry-action-btn" @click="state.execute()">重试</button>
          </div>
          <div v-if="response?.degraded_reason" class="status-banner warning" role="status">
            <AlertTriangle class="w-4 h-4 flex-shrink-0 text-amber-500" />
            <span>语义服务暂不可用，本次已自动使用关键词检索。</span>
          </div>
          <div v-if="response?.indexing_state === 'partial'" class="status-banner info" role="status">
            <Sparkles class="w-4 h-4 flex-shrink-0 text-sky-500" />
            <span>历史正在建立索引，当前结果可能不完整。</span>
          </div>

          <!-- 搜索结果列表区 -->
          <div
            id="global-search-results"
            class="search-results-area"
            role="listbox"
            aria-label="搜索结果"
            :aria-busy="loading"
          >
            <GlobalSearchResultItem
              v-for="(item, i) in items"
              :id="`global-search-result-${i}`"
              :key="item.entity_key"
              :item="item"
              :active="active === i"
              @select="choose(item)"
            />

            <!-- 加载中 -->
            <div v-if="loading" class="result-placeholder">
              <Loader2 class="w-5 h-5 spin text-sky-500" />
              <span>正在搜索…</span>
            </div>

            <!-- 空结果 -->
            <div v-else-if="response && !items.length" class="result-placeholder">
              <span>未找到可访问的匹配结果</span>
            </div>

            <!-- 初始引导 -->
            <div v-else-if="query.trim().length < 2" class="result-placeholder init-hint">
              <span>输入至少两个字符开始搜索任务或对话记录…</span>
            </div>

            <!-- 加载更多 -->
            <div v-if="response?.has_more" class="load-more-box">
              <button
                type="button"
                class="load-more-btn"
                :disabled="loading"
                @click="state.execute(true)"
              >
                <Loader2 v-if="loading" class="w-3.5 h-3.5 spin" />
                <span>加载更多</span>
              </button>
            </div>

            <p v-if="response?.result_window_exhausted" class="window-exhausted-hint">
              已到达本次结果窗口上限，请缩小搜索范围。
            </p>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* 全局模态遮罩层：轻透自然，避免深灰遮挡页面 */
.search-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.2);
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: min(10vh, 80px);
  z-index: 1200;
}

/* 弹窗面板本体：100% 纯白实心材质，绝不变透明 */
.search-modal {
  width: min(720px, 94vw);
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  padding: 18px 20px;
  background: #ffffff !important;
  background-color: #ffffff !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  box-shadow: 0 25px 60px -15px rgba(15, 23, 42, 0.25), 0 0 1px rgba(0, 0, 0, 0.08);
}

.search-modal:hover {
  background: #ffffff !important;
  background-color: #ffffff !important;
}

/* 头部 Header */
.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.header-title-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.header-title {
  font-size: 1.05rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
}

.header-subtitle {
  font-size: 11.5px;
  color: #64748b;
}

.header-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.shortcut-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 7px;
  font-size: 11px;
  font-family: inherit;
  color: #64748b;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}

.modal-close-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  transition: all 0.15s ease;
}

.modal-close-btn:hover {
  background: rgba(241, 245, 249, 0.9);
  color: #0f172a;
  border-color: #e2e8f0;
}

/* 搜索输入框：默认纯白，绝不置灰 */
.search-input-box {
  position: relative;
  display: flex;
  align-items: center;
  width: 100%;
  margin-bottom: 12px;
}

.input-search-icon {
  position: absolute;
  left: 14px;
  width: 17px;
  height: 17px;
  color: #64748b;
  pointer-events: none;
}

.search-input {
  box-sizing: border-box;
  width: 100%;
  height: 44px;
  padding: 0 38px 0 42px;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  background: #ffffff;
  color: #0f172a;
  font-size: 0.95rem;
  font-family: inherit;
  transition: all 0.2s ease;
}

.search-input:focus {
  outline: none;
  background: #ffffff;
  border-color: #0ea5e9;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15);
}

.input-clear-btn {
  position: absolute;
  right: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: 50%;
  background: #e2e8f0;
  color: #64748b;
  cursor: pointer;
  transition: all 0.15s;
}

.input-clear-btn:hover {
  background: #cbd5e1;
  color: #0f172a;
}

/* 过滤器与按键提示条 */
.search-filters-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  gap: 12px;
  flex-wrap: wrap;
  position: relative;
  z-index: 10;
}

.filters-select-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.filter-select {
  width: 120px;
}

.shortcuts-hint {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 11.5px;
  color: #64748b;
}

.hint-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* 状态 Banner */
.status-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 12px;
  margin-bottom: 10px;
}

.status-banner.info {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1d4ed8;
}

.status-banner.warning {
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #b45309;
}

.status-banner.error {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #b91c1c;
}

.retry-action-btn {
  margin-left: auto;
  font-size: 12px;
  color: #0284c7;
  background: none;
  border: none;
  cursor: pointer;
  text-decoration: underline;
}

/* 结果列表区 */
.search-results-area {
  flex: 1;
  min-height: 120px;
  max-height: 50vh;
  overflow-y: auto;
  padding-right: 4px;
}

.result-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px 16px;
  color: #94a3b8;
  font-size: 13px;
}

.result-placeholder.init-hint {
  color: #64748b;
}

.load-more-box {
  display: flex;
  justify-content: center;
  padding: 10px 0 4px;
}

.load-more-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 16px;
  font-size: 12.5px;
  font-weight: 500;
  color: #0284c7;
  background: #ffffff;
  border: 1px solid #bae6fd;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.load-more-btn:hover:not(:disabled) {
  background: #f0f9ff;
  border-color: #38bdf8;
}

.load-more-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.window-exhausted-hint {
  text-align: center;
  font-size: 11.5px;
  color: #94a3b8;
  margin-top: 6px;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 动画效果 */
.search-fade-enter-active,
.search-fade-leave-active {
  transition: opacity 0.2s ease;
}

.search-fade-enter-active .search-modal,
.search-fade-leave-active .search-modal {
  transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.2s ease;
}

.search-fade-enter-from,
.search-fade-leave-to {
  opacity: 0;
}

.search-fade-enter-from .search-modal,
.search-fade-leave-to .search-modal {
  opacity: 0;
  transform: translateY(-8px) scale(0.98);
}
</style>
