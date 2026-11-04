<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, useId, watch } from 'vue'
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
  ariaLabel?: string
  /** 多选：modelValue 为数组，选项以复选方式切换且不关闭下拉。 */
  multiple?: boolean
  /** 多选时超过一项的摘要文案，默认「已选 N 项」。 */
  selectionText?: (count: number) => string
  /** 多选面板底部的清空按钮文案。 */
  clearText?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: any): void
  (e: 'open'): void
}>()

const isOpen = ref(false)
const selectRef = ref<HTMLElement | null>(null)
const triggerRef = ref<HTMLElement | null>(null)
const searchInputRef = ref<HTMLInputElement | null>(null)
const searchQuery = ref('')
const activeIndex = ref(-1)
const keyboardNavigating = ref(false)
const listId = `select-${useId()}`
const flippedUp = ref(false)
const isMultiple = computed(() => props.multiple === true)
const selectedValues = computed<any[]>(() => (Array.isArray(props.modelValue) ? props.modelValue : []))
const effectiveDropUp = computed(() => props.dropUp || flippedUp.value)

const closeDropdown = (restoreFocus = false) => {
  isOpen.value = false
  searchQuery.value = ''
  window.removeEventListener('resize', updateDirection)
  if (restoreFocus) triggerRef.value?.focus()
}

/** 触发器下方空间不足时向上展开，避免长列表被视口裁切。 */
const updateDirection = () => {
  const trigger = triggerRef.value
  if (!trigger) return
  const rect = trigger.getBoundingClientRect()
  const spaceBelow = window.innerHeight - rect.bottom
  flippedUp.value = spaceBelow < 260 && rect.top > spaceBelow
}

const toggleDropdown = () => {
  if (props.disabled) return
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    searchQuery.value = ''
    keyboardNavigating.value = false
    updateDirection()
    window.addEventListener('resize', updateDirection)
    const current = isMultiple.value ? selectedValues.value[0] : props.modelValue
    const selectedIndex = filteredOptions.value.findIndex(option => option.value === current && !option.disabled)
    activeIndex.value = selectedIndex >= 0 ? selectedIndex : filteredOptions.value.findIndex(option => !option.disabled)
    emit('open')
    if (props.searchable) {
      void nextTick(() => {
        searchInputRef.value?.focus()
      })
    }
    return
  }
  window.removeEventListener('resize', updateDirection)
}

const isOptionSelected = (value: any) => (isMultiple.value
  ? selectedValues.value.includes(value)
  : value === props.modelValue)

const selectOption = (option: Option) => {
  if (option.disabled) return
  if (isMultiple.value) {
    const next = selectedValues.value.includes(option.value)
      ? selectedValues.value.filter((value) => value !== option.value)
      : [...selectedValues.value, option.value]
    emit('update:modelValue', next)
    return
  }
  emit('update:modelValue', option.value)
  closeDropdown(true)
}

/** 多选时按住选项不抢焦点，保证搜索框可以连续输入与勾选。 */
const handleOptionMousedown = (event: MouseEvent) => {
  if (isMultiple.value) event.preventDefault()
}

const clearSelection = () => emit('update:modelValue', [])

const handleClickOutside = (event: MouseEvent) => {
  if (selectRef.value && !selectRef.value.contains(event.target as Node)) {
    closeDropdown()
  }
}

const filteredOptions = computed(() => {
  if (!props.searchable || !searchQuery.value.trim()) return props.options || []
  const q = searchQuery.value.trim().toLowerCase()
  return (props.options || []).filter((opt) => (opt.label || '').toLowerCase().includes(q))
})

const selectedLabel = computed(() => {
  if (isMultiple.value) {
    const values = selectedValues.value
    if (values.length === 0) return props.placeholder || ''
    if (values.length === 1) {
      const first = values[0]
      return (props.options || []).find((opt) => opt.value === first)?.label || String(first)
    }
    return props.selectionText ? props.selectionText(values.length) : `已选 ${values.length} 项`
  }
  const selected = (props.options || []).find((opt) => opt.value === props.modelValue)
  return selected ? selected.label : (props.placeholder || '')
})

const isPlaceholder = computed(() => (isMultiple.value
  ? selectedValues.value.length === 0 && Boolean(props.placeholder)
  : !props.modelValue && Boolean(props.placeholder)))

watch(filteredOptions, options => {
  if (!options[activeIndex.value] || options[activeIndex.value]?.disabled) activeIndex.value = options.findIndex(option => !option.disabled)
})
watch(() => props.disabled, disabled => { if (disabled) closeDropdown() })

function moveActive(direction: number) {
  const options = filteredOptions.value
  if (!options.some(option => !option.disabled)) return
  keyboardNavigating.value = true
  let index = activeIndex.value
  do { index = (index + direction + options.length) % options.length } while (options[index]?.disabled)
  activeIndex.value = index
  void nextTick(() => document.getElementById(`${listId}-${index}`)?.scrollIntoView?.({ block: 'nearest' }))
}

function handleKeydown(event: KeyboardEvent) {
  if (props.disabled) return
  const isSearch = event.target === searchInputRef.value
  if (event.key === 'Escape' && isOpen.value) {
    event.preventDefault(); event.stopPropagation(); closeDropdown(true)
  } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault(); event.stopPropagation()
    if (!isOpen.value) toggleDropdown()
    else moveActive(event.key === 'ArrowDown' ? 1 : -1)
  } else if (event.key === 'Enter' || (event.key === ' ' && !isSearch)) {
    event.preventDefault(); event.stopPropagation()
    if (!isOpen.value) toggleDropdown()
    else if (filteredOptions.value[activeIndex.value]) selectOption(filteredOptions.value[activeIndex.value]!)
  } else if (isOpen.value && !isSearch && (event.key === 'Home' || event.key === 'End')) {
    event.preventDefault(); event.stopPropagation()
    keyboardNavigating.value = true
    const indexes = filteredOptions.value.flatMap((option, index) => option.disabled ? [] : [index])
    activeIndex.value = (event.key === 'Home' ? indexes[0] : indexes.at(-1)) ?? -1
  } else if (event.key === 'Tab' && !isSearch) closeDropdown()
}

function handleFocusOut(event: FocusEvent) {
  if (!selectRef.value?.contains(event.relatedTarget as Node | null)) closeDropdown()
}

onMounted(() => {
  window.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  window.removeEventListener('click', handleClickOutside)
  window.removeEventListener('resize', updateDirection)
})
</script>

<template>
  <div
    ref="selectRef"
    class="base-select"
    @focusout="handleFocusOut"
    :class="{ 
      'is-open': isOpen, 
      'is-disabled': disabled,
      'is-multiple': isMultiple,
      'drop-up': effectiveDropUp,
      [`size-${size || 'md'}`]: true
    }"
  >
    <div ref="triggerRef" class="select-trigger" role="combobox" :tabindex="disabled ? -1 : 0" :aria-disabled="disabled || undefined" :aria-label="ariaLabel || placeholder || selectedLabel" :aria-expanded="isOpen" :aria-controls="listId" :aria-activedescendant="isOpen && activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined" aria-haspopup="listbox" @click="toggleDropdown" @keydown="handleKeydown">
      <span class="selected-text" :class="{ 'is-placeholder': isPlaceholder }">
        {{ selectedLabel }}
      </span>
      <ChevronDown class="select-arrow" :class="{ 'is-rotated': isOpen }" />
    </div>

    <transition name="dropdown">
      <div v-if="isOpen" class="select-dropdown glass-panel" @pointermove="keyboardNavigating = false">
        <div v-if="searchable" class="select-search-box" @click.stop>
          <Search class="search-box-icon" />
          <input
            ref="searchInputRef"
            v-model="searchQuery"
            type="text"
            class="search-box-input"
            role="combobox"
            :aria-label="searchPlaceholder || ariaLabel || placeholder || selectedLabel"
            aria-expanded="true"
            :aria-controls="listId"
            :aria-activedescendant="activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined"
            :placeholder="searchPlaceholder || '搜索...'"
            @keydown="handleKeydown"
          />
        </div>

        <ul :id="listId" class="options-list custom-scrollbar" role="listbox" :aria-multiselectable="isMultiple || undefined" :aria-label="ariaLabel || placeholder || selectedLabel">
          <li
            v-for="(option, index) in filteredOptions"
            :key="option.value"
            :id="`${listId}-${index}`"
            class="option-item"
            role="option"
            :aria-selected="isOptionSelected(option.value)"
            :class="{ 'is-selected': isOptionSelected(option.value), 'is-active': index === activeIndex && keyboardNavigating, 'is-disabled': option.disabled }"
            :aria-disabled="option.disabled || undefined"
            :title="option.label"
            @mousedown="handleOptionMousedown"
            @click="selectOption(option)"
          >
            <span v-if="isMultiple" class="option-check" :class="{ 'is-checked': isOptionSelected(option.value) }" aria-hidden="true" />
            <span class="option-label">{{ option.label }}</span>
          </li>
          <li v-if="filteredOptions.length === 0" class="no-options-item">
            暂无匹配选项
          </li>
        </ul>

        <div v-if="isMultiple && selectedValues.length > 0" class="select-footer">
          <button type="button" class="select-clear-all" @click.stop="clearSelection">
            {{ clearText || '清除选择' }}
          </button>
        </div>
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

.select-trigger:focus-visible { outline: 2px solid #0ea5e9; outline-offset: 2px; }

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

/* 键盘导航高亮：仅按下方向键后出现，鼠标操作只依赖 hover */
.option-item.is-active {
  background: rgba(14, 165, 233, 0.08);
  box-shadow: inset 0 0 0 1px rgba(2, 132, 199, 0.45);
}

.option-item.is-selected.is-active {
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.65), 0 4px 12px rgba(14, 165, 233, 0.2);
}

.option-item.is-disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.option-item.is-disabled:hover {
  background: transparent;
  color: #475569;
}

/* 多选：行样式与单选完全一致，只多一个复选标记 */
.is-multiple .option-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 多选可同时高亮多行，行间留 3px 让连续选中的蓝底不会粘成一整块 */
.is-multiple .option-item + .option-item {
  margin-top: 3px;
}

.option-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.option-check {
  flex-shrink: 0;
  position: relative;
  width: 15px;
  height: 15px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  background: #ffffff;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}

.option-check.is-checked {
  border-color: var(--color-primary-600, #0284c7);
  background: var(--color-primary-600, #0284c7);
}

.option-check.is-checked::after {
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

/* 选中行沿用单选的蓝底白字，仅让复选标记在蓝底上反色 */
.is-multiple .option-item.is-selected .option-check {
  border-color: #ffffff;
  background: #ffffff;
}

.is-multiple .option-item.is-selected .option-check.is-checked::after {
  border-color: var(--color-primary-600, #0284c7);
}

.select-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 4px;
  padding-top: 6px;
  border-top: 1px solid rgba(148, 163, 184, 0.18);
}

.select-clear-all {
  padding: 4px 8px;
  border: 0;
  border-radius: 6px;
  color: var(--color-primary-600, #0284c7);
  background: transparent;
  font-size: 0.75rem;
  cursor: pointer;
}

.select-clear-all:hover {
  background: rgba(14, 165, 233, 0.1);
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
