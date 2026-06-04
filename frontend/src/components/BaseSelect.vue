<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { ChevronDown } from 'lucide-vue-next'

interface Option {
  label: string
  value: any
}

const props = defineProps<{
  modelValue: any
  options: Option[]
  placeholder?: string
  disabled?: boolean
  size?: 'sm' | 'md' | 'lg'
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: any): void
}>()

const isOpen = ref(false)
const selectRef = ref<HTMLElement | null>(null)

const toggleDropdown = () => {
  if (props.disabled) return
  isOpen.value = !isOpen.value
}

const selectOption = (option: Option) => {
  emit('update:modelValue', option.value)
  isOpen.value = false
}

const handleClickOutside = (event: MouseEvent) => {
  if (selectRef.value && !selectRef.value.contains(event.target as Node)) {
    isOpen.value = false
  }
}

const selectedLabel = ref('')

const updateLabel = () => {
  const selected = (props.options || []).find(opt => opt.value === props.modelValue)
  selectedLabel.value = selected ? selected.label : (props.placeholder || '')
}

watch(() => props.modelValue, updateLabel, { immediate: true })
watch(() => props.options, updateLabel)

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
        <ul class="options-list">
          <li
            v-for="option in options"
            :key="option.value"
            class="option-item"
            :class="{ 'is-selected': option.value === modelValue }"
            @click="selectOption(option)"
          >
            {{ option.label }}
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
}

.is-placeholder {
  color: #94a3b8;
}

.select-arrow {
  width: 1.25rem;
  height: 1.25rem;
  color: #64748b;
  transition: transform 0.3s ease;
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
  background: rgba(255, 255, 255, 0.75);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 12px;
  box-shadow: var(--shadow-lg);
  transform-origin: top;
}

.options-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 240px;
  overflow-y: auto;
}

.option-item {
  padding: 0.75rem 1rem;
  border-radius: 8px;
  font-size: 0.875rem;
  color: #475569;
  cursor: pointer;
  transition: all 0.2s;
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

</style>
