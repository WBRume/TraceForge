<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseSelect from '@/components/BaseSelect.vue'
import type { TaskListFilters, TaskRelationFilter, TaskSessionFilter, TaskTypeFilterValue } from '@/composables/chat/types'

const props = defineProps<{
  modelValue: boolean
  status: TaskSessionFilter
  taskType: TaskTypeFilterValue
  relations: TaskRelationFilter[]
  trigger: HTMLElement | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  apply: [value: TaskListFilters]
  reset: []
}>()

const { t } = useI18n()
const draftRelations = ref<TaskRelationFilter[]>([...props.relations])
const draftStatus = shallowRef(props.status)
const draftTaskType = shallowRef(props.taskType)
const popoverRef = useTemplateRef<HTMLElement>('popover')
const closeButton = useTemplateRef<HTMLButtonElement>('closeButton')
const popoverMaxWidth = shallowRef('calc(100vw - 24px)')
const updatePopoverWidth = () => {
  const left = popoverRef.value?.getBoundingClientRect().left
  if (left !== undefined) popoverMaxWidth.value = `${Math.max(0, document.documentElement.clientWidth - left - 12)}px`
}
const open = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

watch(
  () => props.modelValue,
  (visible) => {
    if (!visible) return
    draftRelations.value = [...props.relations]
    draftStatus.value = props.status
    draftTaskType.value = props.taskType
    void nextTick(() => {
      updatePopoverWidth()
      closeButton.value?.focus()
    })
  },
  { immediate: true },
)

const relationOptions = computed(() => [
  { value: 'created_by_me' as const, label: t('chat.task_relation_created_by_me'), description: t('chat.task_relation_created_by_me_desc') },
  { value: 'mentioned_me' as const, label: t('chat.task_relation_mentioned_me'), description: t('chat.task_relation_mentioned_me_desc') },
  { value: 'messaged_by_me' as const, label: t('chat.task_relation_messaged_by_me'), description: t('chat.task_relation_messaged_by_me_desc') },
  { value: 'followed_by_me' as const, label: t('chat.task_relation_followed_by_me'), description: t('chat.task_relation_followed_by_me_desc') },
])

const isSelected = (value: TaskRelationFilter) => draftRelations.value.includes(value)

const toggleRelation = (value: TaskRelationFilter) => {
  draftRelations.value = isSelected(value)
    ? draftRelations.value.filter((item) => item !== value)
    : [...draftRelations.value, value]
}

const apply = () => {
  emit('apply', { status: draftStatus.value, taskType: draftTaskType.value, relations: [...draftRelations.value] })
  close()
}

const reset = () => {
  emit('reset')
  close()
}

const close = () => {
  emit('update:modelValue', false)
  props.trigger?.focus()
}

const handlePointerDown = (event: PointerEvent) => {
  const target = event.target as Node | null
  if (target && (popoverRef.value?.contains(target) || props.trigger?.contains(target))) return
  emit('update:modelValue', false)
}

const handleKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
  }
}

watch(open, (visible) => {
  if (visible) {
    document.addEventListener('pointerdown', handlePointerDown, true)
    document.addEventListener('keydown', handleKeydown)
    window.addEventListener('resize', updatePopoverWidth)
  } else {
    document.removeEventListener('pointerdown', handlePointerDown, true)
    document.removeEventListener('keydown', handleKeydown)
    window.removeEventListener('resize', updatePopoverWidth)
  }
}, { immediate: true })

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handlePointerDown, true)
  document.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('resize', updatePopoverWidth)
})
</script>

<template>
  <Transition name="task-filter-pop">
    <section ref="popover" v-if="open" class="task-filter-popover" :style="{ maxWidth: popoverMaxWidth }" role="dialog" :aria-label="t('chat.task_advanced_filter_title')">
      <header class="task-filter-popover-header">
        <h4>{{ t('chat.task_advanced_filter_title') }}</h4>
        <button ref="closeButton" type="button" class="task-filter-close" :aria-label="t('common.close')" @click="close">×</button>
      </header>
      <div class="task-filter-popover-body">
        <div class="task-filter-basics">
          <div class="task-filter-field">
            <span class="task-filter-label">{{ t('chat.session_filter_label') }}</span>
            <BaseSelect
              v-model="draftStatus"
              :aria-label="t('chat.session_filter_label')"
              :options="[
                { label: t('chat.session_filter_all'), value: 'ALL' },
                { label: t('chat.session_filter_success'), value: 'DONE' },
                { label: t('chat.session_filter_failed'), value: 'FAILED' },
              ]"
              size="sm"
              class="task-filter-select"
            />
          </div>
          <div class="task-filter-field">
            <span class="task-filter-label">{{ t('chat.session_type_label') }}</span>
            <BaseSelect
              v-model="draftTaskType"
              :aria-label="t('chat.session_type_label')"
              :options="[
                { label: t('chat.session_type_all'), value: 'ALL' },
                { label: t('task_types.development'), value: 'DEVELOPMENT' },
                { label: t('task_types.diagnosis'), value: 'DIAGNOSIS' },
              ]"
              size="sm"
              class="task-filter-select"
            />
          </div>
        </div>
        <fieldset class="task-relation-options">
          <legend class="task-filter-label">{{ t('chat.task_relation_label') }}</legend>
          <label
            v-for="option in relationOptions"
            :key="option.value"
            class="task-relation-option"
            :class="{ active: isSelected(option.value) }"
          >
            <input
              type="checkbox"
              :checked="isSelected(option.value)"
              @change="toggleRelation(option.value)"
            />
            <span class="task-relation-copy">
              <span class="task-relation-label">{{ option.label }}</span>
              <span class="task-relation-description">{{ option.description }}</span>
            </span>
          </label>
        </fieldset>
      </div>
      <footer class="task-filter-popover-actions">
        <button type="button" class="task-filter-text-btn" @click="reset">{{ t('chat.task_filter_reset') }}</button>
        <button type="button" class="task-filter-apply-btn" @click="apply">{{ t('chat.task_filter_apply') }}</button>
      </footer>
    </section>
  </Transition>
</template>

<style scoped>
.task-filter-popover {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  z-index: 30;
  display: flex;
  flex-direction: column;
  width: 360px;
  max-height: min(520px, calc(100dvh - 124px));
  overflow: hidden;
  border: 1px solid #e2e8f0;
  border-radius: var(--radius-lg);
  background: var(--color-surface-white);
  box-shadow: var(--shadow-lg);
}

.task-filter-popover-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
}

.task-filter-popover-header h4 {
  margin: 0;
  color: var(--color-text-title);
  font-size: 0.86rem;
}

.task-filter-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  color: #94a3b8;
  background: transparent;
  cursor: pointer;
  font-size: 1.1rem;
  line-height: 1;
}

.task-filter-close:hover {
  color: var(--color-text-body);
  background: #f1f5f9;
}

.task-filter-popover-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 0;
  overflow-y: auto;
  padding: 16px;
}

.task-filter-basics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.task-filter-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.task-filter-label {
  flex-shrink: 0;
  color: var(--color-text-muted);
  font-size: 0.75rem;
}

.task-filter-select { min-width: 0; }
.task-filter-select:deep(.select-trigger) { height: 32px; padding: 0 8px; }
.task-filter-select:deep(.selected-text) { font-size: 0.8rem; }
.task-filter-select:deep(.select-dropdown) { z-index: 2; }

.task-relation-options legend {
  margin-bottom: 8px;
  padding: 0;
}

.task-relation-options {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  margin: 0;
  padding: 0;
  border: 0;
}

.task-relation-option {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 10px;
  background: var(--color-surface-white, #fff);
  cursor: pointer;
  transition: border-color var(--transition-fast), background-color var(--transition-fast);
}

.task-relation-option:hover,
.task-relation-option.active {
  border-color: rgba(37, 99, 235, 0.45);
  background: var(--color-primary-50);
}

.task-relation-option input {
  width: 15px;
  height: 15px;
  margin: 3px 0 0;
  accent-color: var(--color-primary-600);
}

.task-relation-copy {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.task-relation-label {
  color: var(--color-text-body);
  font-size: 0.86rem;
  font-weight: 600;
}

.task-relation-description {
  color: var(--color-text-muted);
  font-size: 0.72rem;
  line-height: 1.4;
}

.task-filter-popover-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid rgba(148, 163, 184, 0.18);
}

.task-filter-text-btn,
.task-filter-apply-btn {
  padding: 6px 10px;
  border-radius: 7px;
  font-size: 0.75rem;
  cursor: pointer;
}

.task-filter-text-btn {
  border: 1px solid transparent;
  color: var(--color-text-muted);
  background: transparent;
}

.task-filter-text-btn:hover {
  background: #f1f5f9;
  color: var(--color-text-body);
}

.task-filter-apply-btn {
  border: 1px solid var(--color-primary-600);
  color: #fff;
  background: var(--color-primary-600);
}

.task-filter-apply-btn:hover {
  background: var(--color-primary-700);
}

@media (max-width: 375px) {
  .task-filter-basics { grid-template-columns: minmax(0, 1fr); }
  .task-filter-field { flex-direction: row; align-items: center; gap: 10px; }
  .task-filter-select { flex: 1; }
}

.task-filter-pop-enter-active,
.task-filter-pop-leave-active {
  transition: opacity 0.16s ease, transform 0.16s ease;
}

.task-filter-pop-enter-from,
.task-filter-pop-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
</style>
