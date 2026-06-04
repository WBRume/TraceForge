<script setup lang="ts">
type TaskOption = {
  id: string
  name: string
}

defineProps<{
  tasks: TaskOption[]
  selectedTaskId: string
  selectedTask: TaskOption | null
  sourcesCount: number
  endpointsCount: number
}>()

const emit = defineEmits<{
  (e: 'update:task-id', value: string): void
  (e: 'next'): void
}>()
</script>

<template>
  <section class="stage-view">
    <header class="stage-head">
      <div class="stage-copy">
        <span class="stage-kicker">01 / {{ $t('api_mock.stage_task') }}</span>
        <h2 class="stage-title">{{ $t('api_mock.stage_task') }}</h2>
        <p class="stage-subtitle">{{ $t('api_mock.task_intro') }}</p>
      </div>
      <div class="step-pill">{{ $t('api_mock.stage_active') }}</div>
    </header>

    <div class="task-grid">
      <article class="content-panel primary-panel">
        <label class="field-block">
          <span>{{ $t('api_mock.task') }}</span>
          <select
            class="input-field task-select"
            :value="selectedTaskId"
            @change="emit('update:task-id', ($event.target as HTMLSelectElement).value)"
          >
            <option value="">{{ $t('api_mock.task_empty') }}</option>
            <option v-for="task in tasks" :key="task.id" :value="task.id">{{ task.name }}</option>
          </select>
        </label>

        <p class="helper-copy">
          {{ selectedTask ? $t('api_mock.task_selected') : $t('api_mock.task_help') }}
        </p>

        <div class="action-row">
          <button type="button" class="btn-primary stage-btn" :disabled="!selectedTaskId" @click="emit('next')">
            {{ $t('api_mock.step_continue') }}
          </button>
        </div>
      </article>

      <article class="content-panel summary-panel">
        <span class="summary-kicker">
          {{ selectedTask ? $t('api_mock.task_ready') : $t('api_mock.workflow_badge') }}
        </span>
        <strong class="summary-title">
          {{ selectedTask?.name || $t('api_mock.task_empty') }}
        </strong>
        <p class="summary-description">
          {{ selectedTask?.id || $t('api_mock.task_help') }}
        </p>
        <div class="summary-metrics">
          <span class="metric-chip">{{ sourcesCount }} {{ $t('api_mock.hero_metric_sources') }}</span>
          <span class="metric-chip">{{ endpointsCount }} {{ $t('api_mock.hero_metric_endpoints') }}</span>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.stage-view {
  display: flex;
  flex-direction: column;
  gap: 1.15rem;
}

.stage-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.stage-copy {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.stage-kicker,
.summary-kicker {
  color: #0369a1;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.stage-title {
  margin: 0;
  font-family: 'Poppins', sans-serif;
  font-size: clamp(1.5rem, 2vw, 2.05rem);
  color: #1e3a8a;
}

.stage-subtitle,
.summary-description {
  margin: 0;
  color: #64748b;
  line-height: 1.72;
  font-size: 0.92rem;
}

.step-pill {
  display: inline-flex;
  align-items: center;
  min-height: 2rem;
  padding: 0.25rem 0.8rem;
  border-radius: 999px;
  background: #f8fafc;
  border: 1px solid #7dd3fc;
  color: #0369a1;
  font-size: 0.76rem;
  font-weight: 700;
}

.task-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(280px, 0.9fr);
  gap: 1rem;
}

.content-panel {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-height: 19rem;
  padding: 1.2rem;
  border-radius: 26px;
  border: 1px solid rgba(191, 219, 254, 0.95);
  background: #ffffff;
}

.primary-panel {
  justify-content: flex-start;
}

.summary-panel {
  justify-content: center;
  background:
    radial-gradient(circle at top right, #f1f5f9, transparent 34%),
    #ffffff;
}

.field-block {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.field-block span {
  color: #475569;
  font-size: 0.83rem;
  font-weight: 700;
}

.task-select {
  min-height: 3.25rem;
  border-radius: 18px;
}

.helper-copy {
  margin: 0;
  color: #475569;
  line-height: 1.8;
  font-size: 0.94rem;
}

.action-row {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  margin-top: auto;
}

.stage-btn {
  min-width: 8.5rem;
  min-height: 2.85rem;
  border-radius: 14px;
}

.summary-title {
  font-family: 'Poppins', sans-serif;
  font-size: 1.7rem;
  line-height: 1.15;
  color: #0f172a;
}

.summary-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
}

.metric-chip {
  display: inline-flex;
  align-items: center;
  min-height: 2rem;
  padding: 0.25rem 0.75rem;
  border-radius: 999px;
  border: 1px solid #e2e8f0;
  background: rgba(255, 255, 255, 0.78);
  color: #0369a1;
  font-size: 0.78rem;
  font-weight: 700;
}

@media (max-width: 960px) {
  .task-grid {
    grid-template-columns: 1fr;
  }

  .content-panel {
    min-height: auto;
  }

  .stage-head {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
