<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronLeft, ChevronRight, GitCommitHorizontal, OctagonPause, Play } from '@/components/icons'
import type { DioramaTimelineDay, DioramaWindowMode } from '@/types/dashboardDiorama'

const props = defineProps<{
  timeline: DioramaTimelineDay[]
  dayIndex: number
  windowMode: DioramaWindowMode
  playing: boolean
  speedLabel: string
}>()

const emit = defineEmits<{
  'toggle-play': []
  'step-day': [delta: number]
  'set-day': [index: number]
  'cycle-speed': []
  'update:window-mode': [mode: DioramaWindowMode]
}>()

const { t } = useI18n()

const currentDay = computed(() => props.timeline[props.dayIndex] ?? null)

const maxCommitCount = computed(() => {
  let maxVal = 1
  for (const d of props.timeline) {
    if (d.commit_count > maxVal) maxVal = d.commit_count
  }
  return maxVal
})

const latestCommit = computed(() => currentDay.value?.commits[0] ?? null)

function barHeightPct(day: DioramaTimelineDay): number {
  if (day.commit_count <= 0) return 10
  return Math.max(18, Math.round((day.commit_count / maxCommitCount.value) * 100))
}

function onRangeInput(e: Event) {
  const target = e.target as HTMLInputElement
  emit('set-day', Number(target.value))
}
</script>

<template>
  <div v-if="timeline.length" class="diorama-timeline">
    <div class="timeline-controls">
      <button
        type="button"
        class="play-btn"
        :class="{ 'is-playing': playing }"
        :disabled="timeline.length < 2"
        :title="playing ? t('dashboard.diorama.pause') : t('dashboard.diorama.play')"
        @click="emit('toggle-play')"
      >
        <OctagonPause v-if="playing" class="ctrl-icon" />
        <Play v-else class="ctrl-icon" />
      </button>

      <div class="step-group">
        <button
          type="button"
          class="step-btn"
          :disabled="dayIndex <= 0"
          :title="t('dashboard.diorama.prev_day')"
          @click="emit('step-day', -1)"
        >
          <ChevronLeft class="ctrl-icon" />
        </button>
        <button
          type="button"
          class="step-btn"
          :disabled="dayIndex >= timeline.length - 1"
          :title="t('dashboard.diorama.next_day')"
          @click="emit('step-day', 1)"
        >
          <ChevronRight class="ctrl-icon" />
        </button>
      </div>

      <button
        type="button"
        class="speed-btn"
        :title="t('dashboard.diorama.playback_speed')"
        @click="emit('cycle-speed')"
      >
        {{ speedLabel }}
      </button>

      <div class="mode-switch" role="group">
        <button
          type="button"
          class="mode-btn"
          :class="{ 'is-active': windowMode === 'cumulative' }"
          @click="emit('update:window-mode', 'cumulative')"
        >
          {{ t('dashboard.diorama.window_cumulative') }}
        </button>
        <button
          type="button"
          class="mode-btn"
          :class="{ 'is-active': windowMode === 'day' }"
          @click="emit('update:window-mode', 'day')"
        >
          {{ t('dashboard.diorama.window_day') }}
        </button>
      </div>
    </div>

    <div class="timeline-scrubber">
      <div class="scrubber-meta">
        <span class="current-date">{{ currentDay?.date ?? '-' }}</span>
        <span class="current-stats">
          {{ t('dashboard.diorama.day_commits_short', { count: currentDay?.commit_count ?? 0 }) }}
          ·
          {{ t('dashboard.diorama.day_churn_short', { count: currentDay?.total_churn ?? 0 }) }}
        </span>
      </div>

      <div class="sparkline-bars" role="list">
        <button
          v-for="(day, idx) in timeline"
          :key="day.date"
          type="button"
          class="spark-col"
          :class="{
            'is-active': idx === dayIndex,
            'is-in-window': windowMode === 'cumulative' && idx < dayIndex,
            'is-empty': day.commit_count === 0,
          }"
          :title="`${day.date} · ${day.commit_count} commits`"
          @click="emit('set-day', idx)"
        >
          <span class="spark-bar" :style="{ height: `${barHeightPct(day)}%` }" />
        </button>
      </div>

      <input
        v-if="timeline.length > 1"
        type="range"
        class="timeline-range"
        :min="0"
        :max="timeline.length - 1"
        :value="dayIndex"
        :aria-label="t('dashboard.diorama.timeline_slider')"
        @input="onRangeInput"
      >
    </div>

    <div class="timeline-ticker">
      <template v-if="latestCommit">
        <GitCommitHorizontal class="ticker-icon" />
        <code class="ticker-hash">{{ latestCommit.hash }}</code>
        <span class="ticker-subject" :title="latestCommit.subject">{{ latestCommit.subject }}</span>
      </template>
      <span v-else class="ticker-empty">{{ t('dashboard.diorama.no_commits_day') }}</span>
    </div>
  </div>
</template>

<style scoped>
.diorama-timeline {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 16px;
  background: var(--color-surface-white);
  border-top: 1px solid #e2e8f0;
  flex-wrap: wrap;
}

.timeline-controls {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.play-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: var(--radius-full);
  border: 1px solid #bae6fd;
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  transition: all var(--transition-fast);
}

.play-btn:hover:not(:disabled) {
  background: var(--color-primary-500);
  border-color: var(--color-primary-500);
  color: #ffffff;
}

.play-btn.is-playing {
  background: var(--color-primary-600);
  border-color: var(--color-primary-600);
  color: #ffffff;
}

.play-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.step-group {
  display: inline-flex;
  border: 1px solid #e2e8f0;
  border-radius: var(--radius-md);
  overflow: hidden;
}

.step-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  background: var(--color-surface-white);
  color: #475569;
}

.step-btn:hover:not(:disabled) {
  background: var(--color-primary-50);
  color: var(--color-primary-700);
}

.step-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.speed-btn {
  height: 26px;
  padding: 0 8px;
  border: 1px solid #e2e8f0;
  border-radius: var(--radius-md);
  background: var(--color-surface-white);
  color: #475569;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
}

.speed-btn:hover {
  border-color: #bae6fd;
  color: var(--color-primary-700);
}

.mode-switch {
  display: inline-flex;
  padding: 2px;
  border-radius: var(--radius-md);
  background: #e2e8f0;
  gap: 2px;
}

.mode-btn {
  height: 22px;
  padding: 0 8px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: #475569;
  font-size: 11.5px;
  font-weight: 500;
}

.mode-btn.is-active {
  background: var(--color-surface-white);
  color: var(--color-primary-700);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
}

.ctrl-icon {
  width: 14px;
  height: 14px;
}

.timeline-scrubber {
  flex: 1;
  min-width: 220px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.scrubber-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 11.5px;
}

.current-date {
  font-family: var(--font-mono);
  font-weight: 600;
  color: var(--color-primary-900);
}

.current-stats {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-text-muted);
}

.sparkline-bars {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 22px;
}

.spark-col {
  flex: 1;
  height: 100%;
  padding: 0;
  border: none;
  background: transparent;
  display: flex;
  align-items: flex-end;
}

.spark-bar {
  width: 100%;
  border-radius: 2px 2px 0 0;
  background: #cbd5e1;
  transition: background var(--transition-fast), height var(--transition-fast);
}

.spark-col.is-empty .spark-bar {
  background: #e2e8f0;
}

.spark-col.is-in-window .spark-bar {
  background: #7dd3fc;
}

.spark-col.is-active .spark-bar {
  background: var(--color-primary-600);
}

.spark-col:hover .spark-bar {
  background: var(--color-primary-500);
}

.timeline-range {
  width: 100%;
  height: 4px;
  margin: 2px 0 0;
  accent-color: var(--color-primary-500);
  cursor: pointer;
}

.timeline-ticker {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 240px;
  max-width: 100%;
  padding: 5px 10px;
  border-radius: var(--radius-md);
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  font-size: 11.5px;
  min-width: 0;
}

.ticker-icon {
  width: 13px;
  height: 13px;
  color: var(--color-primary-500);
  flex-shrink: 0;
}

.ticker-hash {
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--color-primary-50);
  color: var(--color-primary-700);
  font-size: 10.5px;
  flex-shrink: 0;
}

.ticker-subject {
  color: var(--color-text-body);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ticker-empty {
  color: #94a3b8;
}
</style>
