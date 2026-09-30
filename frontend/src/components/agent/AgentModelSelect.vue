<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { Check, ChevronDown, Loader2, Search, X } from '@/components/icons'
import type { AgentModelOption } from '@/composables/useAgentModels'

const props = defineProps<{
  modelValue: string
  options: AgentModelOption[]
  loading?: boolean
  error?: string
  disabled?: boolean
  compact?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  retry: []
  refresh: []
}>()

// 展开状态与搜索
const isOpen = ref(false)
const searchQuery = ref('')
const containerRef = ref<HTMLElement | null>(null)
const searchInputRef = ref<HTMLInputElement | null>(null)

// 切换下拉弹窗（或失败状态下点击直接重试）
const toggleOpen = () => {
  if (props.disabled || props.loading) return
  if (props.error) {
    emit('retry')
    return
  }
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    searchQuery.value = ''
    emit('refresh')
    void nextTick(() => {
      searchInputRef.value?.focus()
    })
  }
}

const close = () => {
  isOpen.value = false
  searchQuery.value = ''
}

// 点击外部关闭
const handleClickOutside = (e: MouseEvent) => {
  const target = e.target as Node | null
  if (!target) return
  // 若目标节点已从 DOM 树中脱落（例如动态重新渲染被移除的子节点），不触发外部关闭
  if (!document.contains(target)) return
  if (containerRef.value && !containerRef.value.contains(target)) {
    close()
  }
}

// 键盘 Esc 关闭
const handleKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Escape' && isOpen.value) {
    e.stopPropagation()
    close()
  }
}

onMounted(() => {
  window.addEventListener('click', handleClickOutside)
  window.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('click', handleClickOutside)
  window.removeEventListener('keydown', handleKeydown)
})

import {
  parseModelOption,
  type BrandPatternRule,
  type ParsedModel,
} from './modelBrandRules'

export type { BrandPatternRule, ParsedModel }

// 解析所有选项
const parsedOptions = computed(() => (props.options || []).map(parseModelOption))

// 过滤后的选项
const filteredOptions = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return parsedOptions.value
  return parsedOptions.value.filter(opt =>
    opt.modelName.toLowerCase().includes(query) ||
    opt.provider.toLowerCase().includes(query) ||
    opt.value.toLowerCase().includes(query) ||
    opt.groupName.toLowerCase().includes(query)
  )
})

// 分组聚合
const groupedOptions = computed(() => {
  const groups: { name: string; items: ParsedModel[] }[] = []
  const groupMap = new Map<string, ParsedModel[]>()

  for (const opt of filteredOptions.value) {
    if (!groupMap.has(opt.groupName)) {
      groupMap.set(opt.groupName, [])
    }
    groupMap.get(opt.groupName)!.push(opt)
  }

  for (const [name, items] of groupMap.entries()) {
    groups.push({ name, items })
  }
  return groups
})

// 当前选中的选项详情
const selectedItem = computed(() => {
  return parsedOptions.value.find(o => o.value === props.modelValue) || null
})

// 触发器中展示的文本：失败时直接提示加载失败（点击可重试），平时优先展示已选中模型
const triggerLabel = computed(() => {
  if (props.error) return '加载失败'
  if (selectedItem.value) {
    return props.compact ? selectedItem.value.modelName : selectedItem.value.label
  }
  if (props.loading) return '加载中…'
  if (props.options?.length) return '选择模型'
  return '暂无可选模型'
})

// 选择模型
const selectOption = (opt: ParsedModel) => {
  emit('update:modelValue', opt.value)
  close()
}
</script>

<template>
  <div
    ref="containerRef"
    class="agent-model-select"
    :class="{
      compact,
      'is-open': isOpen,
      'is-disabled': disabled || loading,
      'is-error': !!error,
    }"
  >
    <!-- 触发器按钮 -->
    <button
      type="button"
      class="model-trigger select-trigger"
      :disabled="disabled || loading || (!options.length && !error)"
      :title="error ? `${error} (点击下拉框重试)` : (selectedItem ? `${selectedItem.modelName} (${selectedItem.provider || '默认'})` : '模型选择')"
      aria-haspopup="listbox"
      :aria-expanded="isOpen"
      @click="toggleOpen"
    >
      <!-- 状态图标：加载中显示转圈，失败显示红点，选中显示品牌色圆点 -->
      <span class="trigger-indicator">
        <Loader2 v-if="loading" class="spin-icon" :size="12" />
        <span v-else-if="error" class="status-dot error-dot"></span>
        <span
          v-else-if="selectedItem"
          class="status-dot"
          :style="{ backgroundColor: selectedItem.dotColor }"
        ></span>
        <span v-else class="status-dot empty-dot"></span>
      </span>

      <!-- 模型核心名 -->
      <span class="trigger-model-name selected-text">
        {{ triggerLabel }}
      </span>

      <!-- 厂商微标标签（compact 且有厂商时展示原始 provider，没有则不展示） -->
      <span
        v-if="compact && selectedItem?.provider && !error"
        class="trigger-provider-tag"
      >
        {{ selectedItem.provider }}
      </span>

      <!-- 箭头图标 -->
      <ChevronDown class="trigger-arrow" :class="{ 'is-rotated': isOpen }" :size="12" />
    </button>

    <!-- 弹窗面板 (Popover) -->
    <Transition name="model-popover-anim">
      <div
        v-if="isOpen"
        class="model-popover select-dropdown"
        :class="{ 'drop-up': compact, 'drop-down': !compact }"
        @click.stop
      >
        <!-- 顶部搜索栏（当有 2 个以上模型时提供） -->
        <div v-if="parsedOptions.length > 2" class="popover-search-box">
          <Search class="search-icon" :size="13" />
          <input
            ref="searchInputRef"
            v-model="searchQuery"
            type="text"
            class="search-input"
            placeholder="搜索模型名称或厂商…"
          />
          <button
            v-if="searchQuery"
            type="button"
            class="search-clear-btn"
            title="清空搜索"
            @click="searchQuery = ''"
          >
            <X :size="12" />
          </button>
        </div>

        <!-- 选项列表（按厂商分组） -->
        <div class="popover-list-area custom-scroll">
          <div v-if="!groupedOptions.length" class="empty-hint">
            未找到匹配的模型
          </div>

          <div
            v-for="group in groupedOptions"
            :key="group.name || 'unassigned'"
            class="model-group-section"
          >
            <!-- 分组标题：有 provider 时直接显示原始 provider，没有则不显示 -->
            <div v-if="group.name" class="group-header">
              <span class="group-title">{{ group.name }}</span>
              <span class="group-count">{{ group.items.length }}</span>
            </div>

            <!-- 分组内的模型卡片 -->
            <div class="group-items">
              <div
                v-for="item in group.items"
                :key="item.value"
                class="model-item-card option-item"
                :class="{ 'is-active': item.value === modelValue, 'is-selected': item.value === modelValue }"
                @click="selectOption(item)"
              >
                <!-- 左侧微型 Logo 头像 -->
                <div
                  class="item-avatar"
                  :style="{
                    backgroundColor: item.avatarBg,
                    color: item.avatarColor,
                    border: item.avatarBg === '#FFFFFF' ? '1px solid rgba(226, 232, 240, 0.9)' : undefined,
                  }"
                >
                  {{ item.avatarText }}
                </div>

                <!-- 中间模型名与厂商微标 -->
                <div class="item-content">
                  <span class="item-model-name" :title="item.modelName">{{ item.modelName }}</span>
                  <span v-if="item.provider" class="item-provider-pill">{{ item.provider }}</span>
                </div>

                <!-- 右侧选中对勾 -->
                <div v-if="item.value === modelValue" class="item-check">
                  <Check :size="14" />
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 底部轻量信息栏 -->
        <div class="popover-footer">
          <div class="footer-info">
            <span class="footer-count">共 {{ parsedOptions.length }} 个可用模型</span>
          </div>
          <div class="footer-actions">
            <button
              v-if="error"
              type="button"
              class="footer-action-btn error"
              :disabled="loading"
              @click="$emit('retry')"
            >
              重试
            </button>
            <button
              type="button"
              class="footer-action-btn"
              :disabled="loading"
              title="刷新模型列表"
              @click="$emit('refresh')"
            >
              <Loader2 v-if="loading" class="spin-icon" :size="11" />
              <span>刷新</span>
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.agent-model-select {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  user-select: none;
  font-family: var(--font-body, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif);
}

.agent-model-select.compact {
  flex-shrink: 1;
  max-width: 260px;
}

/* ── 触发器按钮 ── */
.model-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  outline: none;
  font-family: inherit;
  transition: all var(--transition-fast, 150ms cubic-bezier(0.4, 0, 0.2, 1));
  box-sizing: border-box;
  background: var(--color-surface-layer, rgba(255, 255, 255, 0.75));
  border: 1px solid rgba(226, 232, 240, 0.85);
  color: var(--color-text-body, #334155);
}

/* 确保触发器内所有子元素（圆点、文本、厂商标签、箭头）点击事件统一穿透至 button 本身 */
.model-trigger > * {
  pointer-events: none;
}

/* compact 紧凑模式（聊天底栏） */
.agent-model-select.compact .model-trigger {
  height: 28px;
  padding: 0 8px;
  border-radius: 8px;
  font-size: 0.75rem;
  max-width: 100%;
}

/* 非 compact 模式（表单创建模式） */
.agent-model-select:not(.compact) {
  width: 100%;
}
.agent-model-select:not(.compact) .model-trigger {
  width: 100%;
  height: 38px;
  padding: 0 12px;
  border-radius: 8px;
  font-size: 0.84rem;
}

.model-trigger:hover:not(:disabled) {
  border-color: #BAE6FD;
  background: var(--color-primary-50, #F0F9FF);
  color: var(--color-primary-700, #0369A1);
}

.agent-model-select.is-open .model-trigger {
  border-color: var(--color-primary-500, #0EA5E9);
  background: #FFFFFF;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.15);
}

.model-trigger:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 状态圆点与指示器 */
.trigger-indicator {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.8);
}

.status-dot.error-dot {
  background-color: #EF4444;
}

.status-dot.empty-dot {
  background-color: #94A3B8;
}

.spin-icon {
  animation: spin 1s linear infinite;
  color: var(--color-primary-500, #0EA5E9);
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 模型名称：统一使用项目正文字体 */
.trigger-model-name {
  font-weight: 500;
  color: var(--color-text-title, #0F172A);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: inherit;
  font-size: 0.76rem;
}

.agent-model-select.compact .trigger-model-name {
  max-width: 110px;
}

/* 厂商微标 */
.trigger-provider-tag {
  font-size: 0.62rem;
  font-family: inherit;
  color: var(--color-text-muted, #64748B);
  background: rgba(241, 245, 249, 0.9);
  padding: 1px 4px;
  border-radius: 4px;
  line-height: 1.2;
  border: 1px solid rgba(226, 232, 240, 0.7);
  flex-shrink: 0;
}

/* 箭头 */
.trigger-arrow {
  color: #94A3B8;
  transition: transform var(--transition-fast, 150ms ease);
  flex-shrink: 0;
}

.trigger-arrow.is-rotated {
  transform: rotate(180deg);
}


/* ── 弹窗面板 (Popover) ── */
.model-popover {
  position: absolute;
  z-index: 1000;
  width: 288px;
  max-width: min(340px, 92vw);
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid rgba(226, 232, 240, 0.95);
  border-radius: 12px;
  box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.05);
  padding: 8px;
  box-sizing: border-box;
  overflow: hidden;
}

/* 向上展开（聊天底栏 compact） */
.model-popover.drop-up {
  bottom: calc(100% + 8px);
  right: 0;
  left: auto;
  transform-origin: bottom right;
}

/* 向下展开（表单） */
.model-popover.drop-down {
  top: calc(100% + 8px);
  left: 0;
  right: auto;
  transform-origin: top left;
}

/* 搜索栏 */
.popover-search-box {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: #F8FAFC;
  border: 1px solid #E2E8F0;
  border-radius: 8px;
  margin-bottom: 6px;
}

.search-icon {
  color: #94A3B8;
  flex-shrink: 0;
}

.search-input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  font-size: 0.75rem;
  color: var(--color-text-body, #334155);
}

.search-input::placeholder {
  color: #94A3B8;
}

.search-clear-btn {
  border: none;
  background: transparent;
  color: #94A3B8;
  cursor: pointer;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.search-clear-btn:hover {
  color: #475569;
}

/* 列表可滚动区域 */
.popover-list-area {
  max-height: 240px;
  overflow-y: auto;
  padding-right: 2px;
}

.empty-hint {
  padding: 16px 8px;
  text-align: center;
  font-size: 0.75rem;
  color: var(--color-text-muted, #94A3B8);
}

/* 分组块 */
.model-group-section {
  margin-bottom: 6px;
}

.model-group-section:last-child {
  margin-bottom: 0;
}

.group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 6px 3px;
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #94A3B8;
}

.group-count {
  font-size: 0.62rem;
  font-mono: monospace;
  background: #F1F5F9;
  padding: 0 4px;
  border-radius: 999px;
  color: #64748B;
}

.group-items {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

/* 单个模型卡片 */
.model-item-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s ease;
  border: 1px solid transparent;
  box-sizing: border-box;
}

.model-item-card:hover {
  background: #F1F5F9;
}

.model-item-card.is-active {
  background: var(--color-primary-50, #F0F9FF);
  border-color: #BAE6FD;
}

.item-avatar {
  width: 22px;
  height: 22px;
  min-width: 22px;
  border-radius: 6px;
  color: #FFFFFF;
  font-size: 0.62rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
  font-family: var(--font-heading, sans-serif);
}

.item-content {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 6px;
}

.item-model-name {
  font-size: 0.76rem;
  font-weight: 500;
  color: var(--color-text-title, #0F172A);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: inherit;
}

.model-item-card.is-active .item-model-name {
  color: var(--color-primary-700, #0369A1);
  font-weight: 600;
}

.item-provider-pill {
  font-size: 0.62rem;
  font-family: inherit;
  color: var(--color-text-muted, #64748B);
  background: #F1F5F9;
  padding: 1px 4px;
  border-radius: 4px;
  white-space: nowrap;
}

.model-item-card.is-active .item-provider-pill {
  background: #E0F2FE;
  color: var(--color-primary-700, #0369A1);
}

.item-check {
  color: var(--color-primary-600, #0284C7);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 底部栏 */
.popover-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 6px;
  margin-top: 4px;
  border-top: 1px solid #F1F5F9;
  font-size: 0.68rem;
  color: #94A3B8;
}

.footer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.footer-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: transparent;
  color: var(--color-primary-600, #0284C7);
  cursor: pointer;
  padding: 0;
  font-size: 0.68rem;
  transition: opacity 0.15s;
}

.footer-action-btn.error {
  color: #EF4444;
}

.footer-action-btn:hover:not(:disabled) {
  text-decoration: underline;
}

.footer-action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 滚动条 */
.custom-scroll::-webkit-scrollbar {
  width: 4px;
}

.custom-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.custom-scroll::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.3);
  border-radius: 999px;
}

.custom-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(148, 163, 184, 0.5);
}

/* 弹窗过渡动画 */
.model-popover-anim-enter-active,
.model-popover-anim-leave-active {
  transition: opacity 0.18s ease, transform 0.18s cubic-bezier(0.4, 0, 0.2, 1);
}

.model-popover-anim-enter-from,
.model-popover-anim-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.97);
}

.model-popover.drop-up.model-popover-anim-enter-from,
.model-popover.drop-up.model-popover-anim-leave-to {
  transform: translateY(-6px) scale(0.97);
}
</style>
