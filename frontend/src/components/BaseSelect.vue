<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { ChevronDown, Search } from '@/components/icons'

interface Option {
  label: string
  value: any
  disabled?: boolean
}

const props = defineProps<{
  modelValue: any
  options: Option[]
  placeholder?: string
  disabled?: boolean
  size?: 'sm' | 'md' | 'lg'
  dropUp?: boolean
  searchable?: boolean
  searchPlaceholder?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: any): void
  (e: 'open'): void
}>()

const isOpen = ref(false)
const selectRef = ref<HTMLElement | null>(null)
const searchInputRef = ref<HTMLInputElement | null>(null)
const searchQuery = ref('')

const toggleDropdown = () => {
  if (props.disabled) return
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    searchQuery.value = ''
    emit('open')
    if (props.searchable) {
      void nextTick(() => {
        searchInputRef.value?.focus()
      })
    }
  }
}

const selectOption = (option: Option) => {
  if (option.disabled) return
  emit('update:modelValue', option.value)
  isOpen.value = false
  searchQuery.value = ''
}

const handleClickOutside = (event: MouseEvent) => {
  if (selectRef.value && !selectRef.value.contains(event.target as Node)) {
    isOpen.value = false
    searchQuery.value = ''
  }
}

const filteredOptions = computed(() => {
  if (!props.searchable || !searchQuery.value.trim()) return props.options || []
  const q = searchQuery.value.trim().toLowerCase()
  return (props.options || []).filter((opt) => (opt.label || '').toLowerCase().includes(q))
})

const selectedLabel = computed(() => {
  const selected = (props.options || []).find((opt) => opt.value === props.modelValue)
  return selected ? selected.label : (props.placeholder || '')
})

onMounted(() => {
  window.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  window.removeEventListener('click', handleClickOutside)
})
</script>

<template>
  <div
    ref="selectRef"
    class="base-select"
    :class="{ 
      'is-open': isOpen, 
      'is-disabled': disabled,
      'drop-up': dropUp,
      [`size-${size || 'md'}`]: true
    }"
  >
    <div class="select-trigger" @click="toggleDropdown">
      <span class="selected-text" :class="{ 'is-placeholder': !modelValue && placeholder }">
        {{ selectedLabel }}
      </span>
      <ChevronDown class="select-arrow" :class="{ 'is-rotated': isOpen }" />
    </div>

    <transition name="dropdown">
      <div v-if="isOpen" class="select-dropdown glass-panel">
        <div v-if="searchable" class="select-search-box" @click.stop>
          <Search class="search-box-icon" />
          <input
            ref="searchInputRef"
            v-model="searchQuery"
            type="text"
            class="search-box-input"
            :placeholder="searchPlaceholder || '搜索...'"
            @keydown.stop
          />
        </div>

        <ul class="options-list custom-scrollbar">
          <li
            v-for="option in filteredOptions"
            :key="option.value"
            class="option-item"
            :class="{ 'is-selected': option.value === modelValue, 'is-disabled': option.disabled }"
            :aria-disabled="option.disabled || undefined"
            :title="option.label"
            @click="selectOption(option)"
          >
            {{ option.label }}
          </li>
          <li v-if="filteredOptions.length === 0" class="no-options-item">
            暂无匹配选项
          </li>
        </ul>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.base-select {
  position: relative;
  width: 100%;
  user-select: none;
  box-sizing: border-box;
}

.select-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  height: 42px;
  padding: 0 0.875rem;
  background: var(--color-surface-layer);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid rgba(226, 232, 240, 0.8);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-sizing: border-box;
}

.base-select.is-open .select-trigger {
  border-color: #0ea5e9;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.1);
}

.base-select.is-disabled .select-trigger {
  background: rgba(248, 250, 252, 0.4);
  cursor: not-allowed;
  opacity: 0.6;
}

.selected-text {
  font-size: 0.89rem;
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
  flex: 1;
  margin-right: 0.5rem;
}

.is-placeholder {
  color: #94a3b8;
}

.select-arrow {
  width: 1.25rem;
  height: 1.25rem;
  color: #64748b;
  transition: transform 0.3s ease;
  flex-shrink: 0;
}

.select-arrow.is-rotated {
  transform: rotate(180deg);
}

.select-dropdown {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  right: 0;
  z-index: 1000;
  padding: 0.5rem;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 12px;
  box-shadow: var(--shadow-lg);
  transform-origin: top;
  box-sizing: border-box;
}

/* 搜索框 */
.select-search-box {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  margin-bottom: 6px;
  background: rgba(248, 250, 252, 0.9);
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 8px;
  box-sizing: border-box;
}

.search-box-icon {
  width: 14px;
  height: 14px;
  color: #94a3b8;
  flex-shrink: 0;
}

.search-box-input {
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  font-size: 0.8125rem;
  color: #0f172a;
  padding: 0;
}

.search-box-input::placeholder {
  color: #94a3b8;
}

.no-options-item {
  padding: 0.75rem 1rem;
  font-size: 0.8125rem;
  color: #94a3b8;
  text-align: center;
}

/* 向上展开（用于位于页面底部的表单，如下方输入区） */
.drop-up .select-dropdown {
  top: auto;
  bottom: calc(100% + 8px);
  transform-origin: bottom;
}

.options-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 240px;
  overflow-y: auto;
  overflow-x: hidden;
  box-sizing: border-box;
  scrollbar-gutter: stable;
}

.option-item {
  padding: 0.75rem 1rem;
  border-radius: 8px;
  font-size: 0.875rem;
  color: #475569;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  box-sizing: border-box;
}

.option-item:hover {
  background: rgba(14, 165, 233, 0.1);
  color: #0ea5e9;
}

.option-item.is-selected {
  background: var(--color-primary-500);
  color: white;
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.2);
}

.option-item.is-disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.option-item.is-disabled:hover {
  background: transparent;
  color: #475569;
}

/* Sizes */
.size-sm .select-trigger {
  height: 36px;
  padding: 0 0.75rem;
  font-size: 0.8125rem;
}

.size-sm .selected-text {
  font-size: 0.8125rem;
}

.size-sm .select-arrow {
  width: 1rem;
  height: 1rem;
}

/* Size LG */
.size-lg .select-trigger {
  height: 48px;
  padding: 0 1rem;
  border-radius: 10px;
  background: var(--color-surface-layer);
}

.size-lg .selected-text {
  font-size: 0.89rem;
}

.size-lg .select-arrow {
  width: 1.25rem;
  height: 1.25rem;
}

/* Animation */
.dropdown-enter-active,
.dropdown-leave-active {
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(-10px) scale(0.95);
}

.drop-up .dropdown-enter-from,
.drop-up .dropdown-leave-to {
  transform: translateY(10px) scale(0.95);
}
</style>
