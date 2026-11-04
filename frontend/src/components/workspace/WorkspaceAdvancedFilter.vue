<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, shallowRef, useId, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseSelect from '@/components/BaseSelect.vue'
import { Funnel, X } from '@/components/icons'
import type { WorkspaceCreatedWithin, WorkspaceFilterOption, WorkspaceFilterState } from '@/composables/useWorkspaceFilters'

/**
 * 工作区搜索栏最右侧的「高级过滤」入口：按钮 + 浮层面板。
 * 过滤条件由父级持有（useWorkspaceFilters），本组件只负责把改动以 patch 事件回传。
 */
const props = defineProps<{
  filters: WorkspaceFilterState
  projectOptions: WorkspaceFilterOption[]
  productOptions: WorkspaceFilterOption[]
  repositoryOptions: WorkspaceFilterOption[]
  ownerOptions: WorkspaceFilterOption[]
  activeCount: number
  matchedCount: number
}>()

const emit = defineEmits<{
  patch: [patch: Partial<WorkspaceFilterState>]
  reset: []
}>()

const { t } = useI18n()
const open = shallowRef(false)
const triggerRef = useTemplateRef<HTMLButtonElement>('trigger')
const panelRef = useTemplateRef<HTMLElement>('panel')
const panelRightShift = shallowRef(0)
const panelId = `workspace-filters-${useId()}`

const withAllOption = (options: WorkspaceFilterOption[], allLabel: string) => [{ value: '', label: allLabel }, ...options]

const projectSelectOptions = computed(() => withAllOption(props.projectOptions, t('workspaces.filters.project_all')))
const productSelectOptions = computed(() => withAllOption(props.productOptions, t('workspaces.filters.product_all')))
const ownerSelectOptions = computed(() => withAllOption(props.ownerOptions, t('workspaces.filters.owner_all')))
const createdOptions = computed(() => [
  { value: 'ALL', label: t('workspaces.filters.created_all') },
  { value: '7D', label: t('workspaces.filters.created_7d') },
  { value: '30D', label: t('workspaces.filters.created_30d') },
  { value: '90D', label: t('workspaces.filters.created_90d') },
])

const triggerLabel = computed(() => (props.activeCount
  ? t('workspaces.filters.button_active', { count: props.activeCount })
  : t('workspaces.filters.button')))

const repositorySelectionText = (count: number) => t('workspaces.filters.repository_selected', { count })

const close = (restoreFocus = false) => {
  open.value = false
  if (restoreFocus) triggerRef.value?.focus()
}

const toggle = () => {
  open.value = !open.value
}

const patch = (value: Partial<WorkspaceFilterState>) => emit('patch', value)

const handleToggleOnlyMine = (event: Event) => {
  patch({ onlyMine: (event.target as HTMLInputElement).checked })
}

const handlePointerDown = (event: PointerEvent) => {
  const target = event.target as Node | null
  if (!target) return
  if (panelRef.value?.contains(target) || triggerRef.value?.contains(target)) return
  open.value = false
}

const handleKeydown = (event: KeyboardEvent) => {
  if (event.key !== 'Escape' || !open.value) return
  event.preventDefault()
  event.stopPropagation()
  close(true)
}

/** 面板右对齐触发按钮；窗口过窄时整体右移，避免溢出到视口左侧之外。 */
const updatePanelPosition = () => {
  const trigger = triggerRef.value
  const panel = panelRef.value
  if (!trigger || !panel) return
  const margin = 12
  const rect = trigger.getBoundingClientRect()
  const width = panel.offsetWidth || 340
  panelRightShift.value = Math.max(0, Math.round(margin - (rect.right - width)))
}

watch(open, async (visible) => {
  if (visible) {
    document.addEventListener('pointerdown', handlePointerDown, true)
    document.addEventListener('keydown', handleKeydown)
    window.addEventListener('resize', updatePanelPosition)
    await nextTick()
    updatePanelPosition()
    panelRef.value?.focus()
    return
  }
  document.removeEventListener('pointerdown', handlePointerDown, true)
  document.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('resize', updatePanelPosition)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handlePointerDown, true)
  document.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('resize', updatePanelPosition)
})

const createdValue = computed({
  get: () => props.filters.createdWithin,
  set: (value: WorkspaceCreatedWithin) => patch({ createdWithin: value }),
})
</script>

<template>
  <div class="ws-filter">
    <button
      ref="trigger"
      type="button"
      class="ws-filter-trigger"
      :class="{ 'is-active': activeCount > 0, 'is-open': open }"
      :title="triggerLabel"
      :aria-label="triggerLabel"
      :aria-expanded="open"
      :aria-controls="panelId"
      aria-haspopup="dialog"
      @click="toggle"
    >
      <Funnel class="ws-filter-icon" />
      <span v-if="activeCount" class="ws-filter-badge" aria-hidden="true">{{ activeCount }}</span>
    </button>

    <Transition name="ws-filter-pop">
      <section
        v-if="open"
        :id="panelId"
        ref="panel"
        class="ws-filter-popover"
        role="dialog"
        :aria-label="t('workspaces.filters.title')"
        tabindex="-1"
        :style="{ right: `${-panelRightShift}px` }"
      >
        <header class="ws-filter-header">
          <h4 class="ws-filter-title">{{ t('workspaces.filters.title') }}</h4>
          <button type="button" class="ws-filter-close" :aria-label="t('common.close')" @click="close(true)">
            <X class="ws-filter-close-icon" />
          </button>
        </header>

        <div class="ws-filter-body">
          <div class="ws-filter-grid">
            <div class="ws-filter-field">
              <span class="ws-filter-label">{{ t('workspaces.filters.project') }}</span>
              <BaseSelect
                :model-value="filters.project"
                :options="projectSelectOptions"
                size="sm"
                searchable
                :aria-label="t('workspaces.filters.project')"
                :search-placeholder="t('workspaces.filters.search_project')"
                class="ws-filter-select"
                @update:model-value="patch({ project: $event })"
              />
            </div>
            <div class="ws-filter-field">
              <span class="ws-filter-label">{{ t('workspaces.filters.product') }}</span>
              <BaseSelect
                :model-value="filters.product"
                :options="productSelectOptions"
                size="sm"
                searchable
                :aria-label="t('workspaces.filters.product')"
                :search-placeholder="t('workspaces.filters.search_product')"
                class="ws-filter-select"
                @update:model-value="patch({ product: $event })"
              />
            </div>
            <div class="ws-filter-field">
              <span class="ws-filter-label">{{ t('workspaces.filters.owner') }}</span>
              <BaseSelect
                :model-value="filters.owner"
                :options="ownerSelectOptions"
                size="sm"
                searchable
                :aria-label="t('workspaces.filters.owner')"
                :search-placeholder="t('workspaces.filters.search_owner')"
                class="ws-filter-select"
                @update:model-value="patch({ owner: $event })"
              />
            </div>
            <div class="ws-filter-field">
              <span class="ws-filter-label">{{ t('workspaces.filters.created') }}</span>
              <BaseSelect
                v-model="createdValue"
                :options="createdOptions"
                size="sm"
                :aria-label="t('workspaces.filters.created')"
                class="ws-filter-select"
              />
            </div>
            <div class="ws-filter-field">
              <span class="ws-filter-label">{{ t('workspaces.filters.repository') }}</span>
              <BaseSelect
                :model-value="filters.repositories"
                :options="repositoryOptions"
                size="sm"
                searchable
                multiple
                :placeholder="t('workspaces.filters.repository_all')"
                :aria-label="t('workspaces.filters.repository')"
                :search-placeholder="t('workspaces.filters.repository_search')"
                :selection-text="repositorySelectionText"
                :clear-text="t('workspaces.filters.repository_clear')"
                class="ws-filter-select"
                @update:model-value="patch({ repositories: $event })"
              />
            </div>
          </div>

          <label class="ws-filter-toggle">
            <input type="checkbox" :checked="filters.onlyMine" @change="handleToggleOnlyMine" />
            <span>{{ t('workspaces.filters.only_mine') }}</span>
          </label>
        </div>

        <footer class="ws-filter-footer">
          <span class="ws-filter-matched">{{ t('workspaces.filters.matched', { count: matchedCount }) }}</span>
          <div class="ws-filter-actions">
            <button type="button" class="ws-filter-text-btn" :disabled="activeCount === 0" @click="emit('reset')">
              {{ t('workspaces.filters.reset') }}
            </button>
            <button type="button" class="ws-filter-done-btn" @click="close(true)">
              {{ t('workspaces.filters.done') }}
            </button>
          </div>
        </footer>
      </section>
    </Transition>
  </div>
</template>

<style scoped>
.ws-filter {
  position: relative;
  display: flex;
  align-items: center;
  height: 100%;
  flex-shrink: 0;
}

.ws-filter-trigger {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 26px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 6px;
  color: var(--color-primary-600, #0284c7);
  background: var(--color-primary-50, #f0f9ff);
  cursor: pointer;
  transition: background-color 0.2s ease, border-color 0.2s ease;
}

.ws-filter-trigger:hover,
.ws-filter-trigger.is-open,
.ws-filter-trigger.is-active {
  border-color: rgba(2, 132, 199, 0.25);
  background: rgba(14, 165, 233, 0.14);
}

.ws-filter-trigger:focus-visible {
  outline: 2px solid var(--color-primary-500, #0ea5e9);
  outline-offset: 2px;
}

.ws-filter-icon {
  width: 14px;
  height: 14px;
}

.ws-filter-badge {
  position: absolute;
  top: -4px;
  right: -4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 14px;
  height: 14px;
  padding: 0 3px;
  border-radius: 7px;
  color: #ffffff;
  background: var(--color-primary-600, #0284c7);
  box-shadow: 0 0 0 1.5px #ffffff;
  font-size: 0.6rem;
  font-weight: 700;
  line-height: 1;
}

.ws-filter-popover {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  z-index: 40;
  display: flex;
  flex-direction: column;
  width: 340px;
  max-width: calc(100vw - 32px);
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  background: #ffffff;
  box-shadow: 0 18px 40px -12px rgba(15, 23, 42, 0.18), 0 4px 10px -4px rgba(15, 23, 42, 0.08);
  outline: none;
}

.ws-filter-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid #f1f5f9;
}

.ws-filter-title {
  margin: 0;
  font-size: 0.86rem;
  font-weight: 600;
  color: #1e293b;
}

.ws-filter-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 0;
  border-radius: 6px;
  color: #94a3b8;
  background: transparent;
  cursor: pointer;
}

.ws-filter-close:hover {
  color: #475569;
  background: #f1f5f9;
}

.ws-filter-close-icon {
  width: 14px;
  height: 14px;
}

.ws-filter-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 14px;
}

.ws-filter-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 9px;
}

.ws-filter-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.ws-filter-label {
  color: #64748b;
  font-size: 0.72rem;
  line-height: 1.2;
}

/* 下拉层完全沿用 BaseSelect 自带样式，仅约束宽度 */
.ws-filter-select {
  min-width: 0;
}

.ws-filter-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.78rem;
  color: #475569;
  cursor: pointer;
}

.ws-filter-toggle input {
  position: relative;
  appearance: none;
  -webkit-appearance: none;
  width: 15px;
  height: 15px;
  margin: 0;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  background: #ffffff;
  cursor: pointer;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}

.ws-filter-toggle input:checked {
  border-color: var(--color-primary-600, #0284c7);
  background: var(--color-primary-600, #0284c7);
}

.ws-filter-toggle input:checked::after {
  content: '';
  position: absolute;
  inset: 0;
  width: 4px;
  height: 8px;
  margin: auto;
  border: solid #ffffff;
  border-width: 0 2px 2px 0;
  transform: translateY(-1px) rotate(45deg);
}

.ws-filter-toggle input:focus-visible {
  outline: 2px solid var(--color-primary-500, #0ea5e9);
  outline-offset: 2px;
}

.ws-filter-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-top: 1px solid #f1f5f9;
}

.ws-filter-matched {
  color: #94a3b8;
  font-size: 0.72rem;
}

.ws-filter-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.ws-filter-text-btn,
.ws-filter-done-btn {
  padding: 5px 10px;
  border-radius: 7px;
  font-size: 0.75rem;
  cursor: pointer;
}

.ws-filter-text-btn {
  border: 1px solid transparent;
  color: #64748b;
  background: transparent;
}

.ws-filter-text-btn:hover:not(:disabled) {
  background: #f1f5f9;
  color: #334155;
}

.ws-filter-text-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.ws-filter-done-btn {
  border: 1px solid var(--color-primary-600, #0284c7);
  color: #ffffff;
  background: var(--color-primary-600, #0284c7);
}

.ws-filter-done-btn:hover {
  background: var(--color-primary-700, #0369a1);
}

.ws-filter-pop-enter-active,
.ws-filter-pop-leave-active {
  transition: opacity 0.16s ease, transform 0.16s ease;
}

.ws-filter-pop-enter-from,
.ws-filter-pop-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
</style>
