<script setup lang="ts">
import { computed, ref } from 'vue'
import { Search } from 'lucide-vue-next'

type TaskOption = {
  id: string
  name: string
}

const props = withDefaults(defineProps<{
  tasks: TaskOption[]
  modelValue: string
  compact?: boolean
}>(), {
  compact: false,
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

const keyword = ref('')

const filteredTasks = computed(() => {
  const needle = keyword.value.trim().toLowerCase()
  if (!needle) return props.tasks
  return props.tasks.filter((task) => task.name.toLowerCase().includes(needle) || task.id.toLowerCase().includes(needle))
})
</script>

<template>
  <section class="task-picker" :class="{ compact }">
    <div class="picker-head">
      <div>
        <span>{{ $t('api_mock.task_picker_title') }}</span>
        <h3>{{ $t('api_mock.task_picker_title') }}</h3>
      </div>
      <strong>{{ tasks.length }}</strong>
    </div>

    <label class="search-field">
      <Search class="w-4 h-4" />
      <input
        v-model="keyword"
        class="input-field search-input"
        :placeholder="$t('api_mock.task_search_placeholder')"
      >
    </label>

    <div v-if="filteredTasks.length === 0" class="empty-line">{{ $t('api_mock.task_list_empty') }}</div>

    <div v-else class="task-list custom-scrollbar">
      <button
        v-for="task in filteredTasks"
        :key="task.id"
        type="button"
        class="task-item"
        :class="{ active: task.id === modelValue }"
        @click="emit('update:modelValue', task.id)"
      >
        <strong>{{ task.name }}</strong>
        <p>{{ task.id }}</p>
      </button>
    </div>
  </section>
</template>

<style scoped>
.task-picker {
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
  min-width: 0;
}

.picker-head {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  align-items: flex-start;
}

.picker-head span {
  color: #0369a1;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.picker-head h3 {
  margin: 0.32rem 0 0;
  font-size: 1.06rem;
}

.picker-head strong {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 2.4rem;
  min-height: 2.4rem;
  border-radius: 999px;
  background: #f1f5f9;
  color: #475569;
}

.search-field {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.65rem 0.8rem;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
}

.search-field :deep(svg) {
  color: #64748b;
}

.search-input {
  border: none;
  background: transparent;
  box-shadow: none;
  padding: 0;
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  max-height: 22rem;
  overflow: auto;
  padding-right: 0.18rem;
}

.task-item {
  width: 100%;
  text-align: left;
  padding: 0.82rem 0.9rem;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
}

.task-item.active {
  border-color: #cbd5e1;
  background: #ffffff;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05);
}

.task-item strong {
  display: block;
  color: #0f172a;
}

.task-item p,
.empty-line {
  margin: 0.28rem 0 0;
  color: #64748b;
  font-size: 0.78rem;
  line-height: 1.5;
}

.compact .task-list {
  max-height: 18rem;
}

.compact .picker-head span {
  display: none;
}

.compact .picker-head h3 {
  margin-top: 0;
  font-size: 0.98rem;
}

.compact .picker-head strong {
  min-width: 2.1rem;
  min-height: 2.1rem;
}
</style>
