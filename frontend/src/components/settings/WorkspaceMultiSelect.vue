<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDown, Search } from '@/components/icons'

type WorkspaceOption = {
  id: string
  name: string
}

const props = withDefaults(defineProps<{
  modelValue: string[]
  options: WorkspaceOption[]
  disabled?: boolean
  ariaLabel?: string
}>(), {
  disabled: false,
  ariaLabel: '',
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
}>()

const { t } = useI18n()
const root = ref<HTMLElement | null>(null)
const searchRef = ref<HTMLInputElement | null>(null)
const open = ref(false)
const query = ref('')

const selected = computed(() => new Set(props.modelValue))
const selectedOptions = computed(() => props.options.filter(option => selected.value.has(option.id)))
const filteredOptions = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return keyword
    ? props.options.filter(option => option.name.toLowerCase().includes(keyword))
    : props.options
})
const allActive = computed(() => props.modelValue.length === 0)
const triggerText = computed(() => {
  if (selectedOptions.value.length === 0) return t('settings.webhook.workspace_all')
  if (selectedOptions.value.length === 1) return selectedOptions.value[0].name
  return t('settings.webhook.workspace_selected_trigger', { count: selectedOptions.value.length })
})

const toggleOpen = () => {
  if (props.disabled) return
  open.value = !open.value
  if (open.value) {
    query.value = ''
    void nextTick(() => searchRef.value?.focus())
  }
}

const close = () => {
  open.value = false
}

const toggleOption = (workspaceId: string) => {
  if (props.disabled) return
  const next = new Set(props.modelValue)
  if (next.has(workspaceId)) {
    next.delete(workspaceId)
  } else {
    next.add(workspaceId)
  }
  emit('update:modelValue', [...next])
}

const clearSelection = () => {
  if (props.disabled) return
  emit('update:modelValue', [])
}

const onDocumentClick = (event: MouseEvent) => {
  if (!root.value?.contains(event.target as Node)) close()
}

const onKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape') close()
}

onMounted(() => {
  document.addEventListener('click', onDocumentClick)
  document.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div ref="root" class="workspace-multi" :class="{ open, disabled }">
    <button
      type="button"
      class="workspace-multi-trigger"
      :disabled="disabled"
      :aria-label="ariaLabel"
      :aria-expanded="open"
      aria-haspopup="listbox"
      @click="toggleOpen"
    >
      <span class="workspace-multi-trigger-text">{{ triggerText }}</span>
      <span class="workspace-multi-trigger-meta">
        <span v-if="selectedOptions.length" class="workspace-multi-count">{{ selectedOptions.length }}</span>
        <ChevronDown class="workspace-multi-chevron" />
      </span>
    </button>

    <Transition name="workspace-multi-pop">
      <div v-if="open" class="workspace-multi-panel" @click.stop>
        <div class="workspace-multi-search">
          <Search class="workspace-multi-search-icon" />
          <input
            ref="searchRef"
            v-model="query"
            type="search"
            :placeholder="$t('settings.webhook.workspace_search_placeholder')"
            @keydown.esc.stop="close"
          />
        </div>

        <div class="workspace-multi-list" role="listbox" aria-multiselectable="true">
          <button
            type="button"
            class="workspace-multi-option all"
            :class="{ active: allActive }"
            role="option"
            :aria-selected="allActive"
            @click="clearSelection"
          >
            <span class="workspace-multi-all-dot"></span>
            <span class="workspace-multi-option-name">{{ $t('settings.webhook.workspace_all') }}</span>
          </button>

          <div class="workspace-multi-divider"></div>

          <label
            v-for="workspace in filteredOptions"
            :key="workspace.id"
            class="workspace-multi-option"
            :class="{ active: selected.has(workspace.id) }"
          >
            <input
              type="checkbox"
              class="workspace-multi-checkbox"
              :checked="selected.has(workspace.id)"
              :disabled="disabled"
              @change="toggleOption(workspace.id)"
            />
            <span class="workspace-multi-option-name">{{ workspace.name }}</span>
          </label>

          <p v-if="filteredOptions.length === 0" class="workspace-multi-empty">
            {{ options.length === 0 ? $t('settings.webhook.workspace_filter_empty') : $t('settings.webhook.workspace_no_match') }}
          </p>
        </div>

        <div class="workspace-multi-footer">
          <span>{{ allActive ? $t('settings.webhook.workspace_all') : $t('settings.webhook.workspace_selected_footer', { count: selectedOptions.length }) }}</span>
          <button
            v-if="selectedOptions.length"
            type="button"
            class="workspace-multi-clear"
            :disabled="disabled"
            @click="clearSelection"
          >
            {{ $t('settings.webhook.workspace_clear') }}
          </button>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.workspace-multi {
  position: relative;
  width: 100%;
}

.workspace-multi-trigger {
  width: 100%;
  min-height: 42px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 9px;
  background: #ffffff;
  color: #0f172a;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s ease, box-shadow 0.16s ease;
}

.workspace-multi-trigger:hover:not(:disabled),
.workspace-multi.open .workspace-multi-trigger {
  border-color: #38bdf8;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.12);
}

.workspace-multi-trigger:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.workspace-multi-trigger-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workspace-multi-trigger-meta {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.workspace-multi-count {
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 999px;
  background: #e0f2fe;
  color: #0369a1;
  font-size: 11px;
  font-weight: 700;
  line-height: 20px;
  text-align: center;
}

.workspace-multi-chevron {
  width: 16px;
  height: 16px;
  color: #64748b;
  transition: transform 0.18s ease;
}

.workspace-multi.open .workspace-multi-chevron {
  transform: rotate(180deg);
}

.workspace-multi-panel {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  right: 0;
  z-index: 80;
  padding: 10px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #ffffff;
  box-shadow: 0 18px 38px -14px rgba(15, 23, 42, 0.28);
}

.workspace-multi-search {
  position: relative;
  display: flex;
  align-items: center;
  margin-bottom: 8px;
}

.workspace-multi-search-icon {
  position: absolute;
  left: 10px;
  width: 15px;
  height: 15px;
  color: #94a3b8;
  pointer-events: none;
}

.workspace-multi-search input {
  width: 100%;
  height: 34px;
  padding: 0 10px 0 32px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  color: #0f172a;
  font-size: 13px;
  outline: none;
}

.workspace-multi-search input:focus {
  border-color: #38bdf8;
  background: #ffffff;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.12);
}

.workspace-multi-list {
  max-height: 260px;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 2px;
}

.workspace-multi-option {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 8px 9px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #334155;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  content-visibility: auto;
  contain-intrinsic-size: 36px;
}

.workspace-multi-option:hover {
  background: #f0f9ff;
  color: #0369a1;
}

.workspace-multi-option.active {
  background: #f0f9ff;
  color: #0369a1;
  font-weight: 600;
}

.workspace-multi-option-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workspace-multi-checkbox {
  appearance: none;
  -webkit-appearance: none;
  width: 17px;
  height: 17px;
  margin: 0;
  border: 1.5px solid #cbd5e1;
  border-radius: 5px;
  background-color: #ffffff;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.14s ease;
}

.workspace-multi-checkbox:checked {
  border-color: #0ea5e9;
  background-color: #0ea5e9;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 14 14' fill='none'%3E%3Cpath d='M2.5 7L5.5 10L11.5 4' stroke='%23ffffff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: center;
  background-size: 10px 10px;
}

.workspace-multi-checkbox:focus-visible {
  outline: 2px solid #7dd3fc;
  outline-offset: 1px;
}

.workspace-multi-all-dot {
  width: 17px;
  height: 17px;
  border-radius: 50%;
  border: 1.5px solid #cbd5e1;
  background: #ffffff;
  flex-shrink: 0;
}

.workspace-multi-option.active .workspace-multi-all-dot {
  border-color: #0ea5e9;
  background: #0ea5e9;
  box-shadow: inset 0 0 0 4px #ffffff;
}

.workspace-multi-divider {
  height: 1px;
  margin: 6px 4px;
  background: #f1f5f9;
}

.workspace-multi-empty {
  margin: 8px 6px;
  color: #94a3b8;
  font-size: 12px;
  text-align: center;
}

.workspace-multi-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 8px;
  padding: 8px 4px 0;
  border-top: 1px solid #f1f5f9;
  color: #64748b;
  font-size: 12px;
}

.workspace-multi-clear {
  border: none;
  background: transparent;
  color: #0284c7;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.workspace-multi-clear:hover:not(:disabled) {
  color: #0369a1;
}

.workspace-multi-pop-enter-active,
.workspace-multi-pop-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.workspace-multi-pop-enter-from,
.workspace-multi-pop-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.99);
}

@media (prefers-reduced-motion: reduce) {
  .workspace-multi-chevron,
  .workspace-multi-pop-enter-active,
  .workspace-multi-pop-leave-active {
    transition: none;
  }
}
</style>
