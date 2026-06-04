<script setup lang="ts">
import type { ApiMockProject, ApiMockSourceVersion } from '@/types/apiMock'
import TaskSourcePanel from '@/components/api-mock/TaskSourcePanel.vue'

type TaskOption = {
  id: string
  name: string
}
type JobState = {
  id: string
  job_type: string
  status: 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED'
  progress: number
  message?: string | null
}

defineProps<{
  tasks: TaskOption[]
  selectedTaskId: string
  selectedTaskName: string
  project: ApiMockProject | null
  sourceVersions: ApiMockSourceVersion[]
  selectedSourceVersionId: string
  canManage: boolean
  canPublish: boolean
  syncBusy: boolean
  importBusy: boolean
  currentSourceLabel: string
  hasSources: boolean
  jobState: JobState | null
}>()

const emit = defineEmits<{
  (e: 'sync'): void
  (e: 'source-change', sourceVersionId: string): void
  (e: 'update-proxy', payload: { proxy_enabled: boolean; proxy_base_url: string }): void
  (e: 'import-swagger', payload: { source_name?: string; source_url?: string; raw_content?: string; file?: File | null }): void
  (e: 'back'): void
  (e: 'next'): void
}>()
</script>

<template>
  <section class="stage-view">
    <header class="stage-head">
      <div class="stage-copy">
        <span class="stage-kicker">02 / {{ $t('api_mock.stage_source') }}</span>
        <h2 class="stage-title">{{ $t('api_mock.stage_source') }}</h2>
        <p class="stage-subtitle">{{ $t('api_mock.source_intro') }}</p>
      </div>
      <div class="stage-summary-card">
        <span class="summary-label">{{ $t('api_mock.task_ready') }}</span>
        <strong>{{ selectedTaskName }}</strong>
        <p>{{ $t('api_mock.current_source_label') }}: {{ currentSourceLabel }}</p>
      </div>
    </header>

    <div class="status-row">
      <span class="status-chip">{{ sourceVersions.length }} {{ $t('api_mock.hero_metric_sources') }}</span>
      <span class="status-chip" :class="{ active: hasSources }">
        {{ hasSources ? $t('api_mock.source_ready_hint') : $t('api_mock.source_waiting') }}
      </span>
    </div>

    <TaskSourcePanel
      :tasks="tasks"
      :selected-task-id="selectedTaskId"
      :project="project"
      :source-versions="sourceVersions"
      :selected-source-version-id="selectedSourceVersionId"
      :can-manage="canManage"
      :can-publish="canPublish"
      :sync-busy="syncBusy"
      :import-busy="importBusy"
      :job-state="jobState"
      :show-task-picker="false"
      :show-source-version-picker="true"
      @sync="emit('sync')"
      @source-change="emit('source-change', $event)"
      @update-proxy="emit('update-proxy', $event)"
      @import-swagger="emit('import-swagger', $event)"
    />

    <footer class="stage-footer">
      <button type="button" class="btn-secondary stage-btn ghost" @click="emit('back')">
        {{ $t('api_mock.step_back') }}
      </button>
      <button type="button" class="btn-primary stage-btn" :disabled="!hasSources" @click="emit('next')">
        {{ $t('api_mock.step_continue') }}
      </button>
    </footer>
  </section>
</template>

<style scoped>
.stage-view {
  display: flex;
  flex-direction: column;
  gap: 1rem;
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
.summary-label {
  color: #0369a1;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.stage-title {
  margin: 0;
  font-family: 'Poppins', sans-serif;
  font-size: clamp(1.45rem, 2vw, 1.95rem);
  color: #1e3a8a;
}

.stage-subtitle {
  margin: 0;
  color: #64748b;
  font-size: 0.92rem;
  line-height: 1.72;
}

.stage-summary-card {
  min-width: 260px;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.95rem 1rem;
  border-radius: 22px;
  border: 1px solid rgba(191, 219, 254, 0.95);
  background: #ffffff;
}

.stage-summary-card strong {
  color: #0f172a;
  font-family: 'Poppins', sans-serif;
  font-size: 1rem;
}

.stage-summary-card p {
  margin: 0;
  color: #64748b;
  font-size: 0.82rem;
  line-height: 1.6;
}

.status-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  min-height: 2rem;
  padding: 0.28rem 0.72rem;
  border-radius: 999px;
  border: 1px solid #e2e8f0;
  background: rgba(255, 255, 255, 0.82);
  color: #0369a1;
  font-size: 0.77rem;
  font-weight: 700;
}

.status-chip.active {
  background: #f8fafc;
  border-color: #7dd3fc;
}

.stage-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.stage-btn {
  min-width: 8rem;
  min-height: 2.8rem;
  border-radius: 14px;
}

.btn-secondary.ghost {
  border: 1px solid #e2e8f0;
  background: rgba(255, 255, 255, 0.76);
  color: #0369a1;
  font-weight: 700;
}

@media (max-width: 960px) {
  .stage-head {
    flex-direction: column;
  }

  .stage-summary-card {
    min-width: 0;
    width: 100%;
  }
}
</style>
