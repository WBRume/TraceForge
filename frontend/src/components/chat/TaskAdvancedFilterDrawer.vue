<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

export type TaskRelationFilter =
  | 'created_by_me'
  | 'mentioned_me'
  | 'messaged_by_me'
  | 'followed_by_me'

const props = defineProps<{
  modelValue: boolean
  relations: TaskRelationFilter[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  apply: [value: TaskRelationFilter[]]
  reset: []
}>()

const { t } = useI18n()
const draftRelations = ref<TaskRelationFilter[]>([...props.relations])
const popoverRef = useTemplateRef<HTMLElement>('popover')
const open = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

watch(
  () => [props.modelValue, props.relations] as const,
  ([visible, relations]) => {
    if (visible) draftRelations.value = [...relations]
  },
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
  emit('apply', [...draftRelations.value])
  emit('update:modelValue', false)
}

const reset = () => {
  draftRelations.value = []
  emit('reset')
  emit('update:modelValue', false)
}

const handlePointerDown = (event: PointerEvent) => {
  const target = event.target as Node | null
  if (target && popoverRef.value?.contains(target)) return
  emit('update:modelValue', false)
}

const handleKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape') emit('update:modelValue', false)
}

watch(open, (visible) => {
  if (visible) {
    document.addEventListener('pointerdown', handlePointerDown, true)
    document.addEventListener('keydown', handleKeydown, true)
  } else {
    document.removeEventListener('pointerdown', handlePointerDown, true)
    document.removeEventListener('keydown', handleKeydown, true)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handlePointerDown, true)
  document.removeEventListener('keydown', handleKeydown, true)
})
</script>

<template>
  <Transition name="task-filter-pop">
    <section ref="popover" v-if="open" class="task-filter-popover" role="dialog" :aria-label="t('chat.task_advanced_filter_title')">
      <header class="task-filter-popover-header">
        <div>
          <h4>{{ t('chat.task_advanced_filter_title') }}</h4>
          <p>{{ t('chat.task_advanced_filter_hint') }}</p>
        </div>
        <button type="button" class="task-filter-close" :aria-label="t('common.close')" @click="open = false">×</button>
      </header>
      <div class="task-filter-popover-body">
        <div class="task-relation-heading">
          <span>{{ t('chat.task_relation_label') }}</span>
          <span class="task-relation-count">{{ draftRelations.length }}</span>
        </div>
        <p class="task-relation-empty-hint" v-if="draftRelations.length === 0">{{ t('chat.task_relation_all_desc') }}</p>
        <div class="task-relation-options">
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
        </div>
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
  width: min(328px, calc(100vw - 28px));
  max-height: min(520px, calc(100vh - 28px));
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
  padding: 12px 14px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
}

.task-filter-popover-header h4 {
  margin: 0;
  color: var(--color-text-title);
  font-size: 0.86rem;
}

.task-filter-popover-header p {
  margin: 4px 0 0;
  color: var(--color-text-muted);
  font-size: 0.7rem;
  line-height: 1.4;
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
  gap: 18px;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 14px;
}

.task-relation-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--color-text-title);
  font-size: 0.82rem;
  font-weight: 700;
}

.task-relation-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 5px;
  border-radius: var(--radius-full);
  color: var(--color-primary-700);
  background: var(--color-primary-50);
  font-size: 0.68rem;
}

.task-relation-empty-hint {
  margin: 0;
  color: var(--color-text-muted);
  font-size: 0.72rem;
  line-height: 1.6;
}

.task-relation-options {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.task-relation-option {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px;
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
  padding: 10px 14px 12px;
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
