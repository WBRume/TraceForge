<script setup lang="ts">
import type { Component } from 'vue'
import { CircleCheckBig } from 'lucide-vue-next'

type WorkflowStageKey = 'task' | 'source' | 'browse' | 'build'

type WorkflowStageItem = {
  key: WorkflowStageKey
  icon: Component
  index: string
  label: string
  desc: string
  state: 'done' | 'active' | 'idle'
  locked: boolean
}

defineProps<{
  items: WorkflowStageItem[]
  currentStage: WorkflowStageKey
  tasksCount: number
  sourcesCount: number
  endpointsCount: number
  onlineCount: number
}>()

const emit = defineEmits<{
  (e: 'select-stage', value: WorkflowStageKey): void
  (e: 'open-shortcuts'): void
}>()
</script>

<template>
  <aside class="workflow-rail glass-panel">
    <span class="rail-kicker">{{ $t('api_mock.workflow_badge') }}</span>

    <div class="stage-list" role="tablist" :aria-label="$t('api_mock.title')">
      <button
        v-for="stage in items"
        :key="stage.key"
        type="button"
        class="stage-item"
        :class="[
          `state-${stage.state}`,
          { current: currentStage === stage.key, locked: stage.locked },
        ]"
        :disabled="stage.locked"
        :aria-selected="currentStage === stage.key"
        @click="emit('select-stage', stage.key)"
      >
        <span class="stage-main">
          <span class="stage-index">{{ stage.index }}</span>
          <span class="stage-icon">
            <component :is="stage.state === 'done' ? CircleCheckBig : stage.icon" class="w-4 h-4" />
          </span>
          <span class="stage-copy">
            <strong>{{ stage.label }}</strong>
            <small v-if="currentStage === stage.key">{{ stage.desc }}</small>
          </span>
        </span>
        <span class="stage-state" :class="`state-${stage.state}`">
          {{
            currentStage === stage.key
              ? $t('api_mock.stage_active')
              : stage.state === 'done'
                ? $t('api_mock.stage_done')
                : stage.locked
                  ? $t('api_mock.stage_locked')
                  : stage.index
          }}
        </span>
      </button>
    </div>
  </aside>
</template>

<style scoped>
.workflow-rail {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
  padding: 0.9rem;
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid #e2e8f0;
  box-shadow: 0 14px 28px rgba(14, 165, 233, 0.06);
}

.rail-kicker {
  display: inline-flex;
  align-items: center;
  align-self: flex-start;
  min-height: 1.9rem;
  padding: 0.25rem 0.7rem;
  border-radius: 999px;
  border: 1px solid #e2e8f0;
  background: #f0f9ff;
  color: #0369a1;
  font-size: 0.74rem;
  font-weight: 700;
}

.stage-list {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.stage-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  width: 100%;
  padding: 0.72rem 0.8rem;
  border-radius: 18px;
  border: 1px solid rgba(191, 219, 254, 0.95);
  background: #ffffff;
  text-align: left;
  transition: transform 0.24s ease, box-shadow 0.24s ease, border-color 0.24s ease;
}

.stage-item:hover:not(:disabled) {
  transform: translateX(2px);
  border-color: #7dd3fc;
  box-shadow: 0 14px 26px rgba(14, 165, 233, 0.1);
}

.stage-item.current {
  background: #ffffff;
  border-color: #7dd3fc;
  box-shadow: 0 14px 28px rgba(14, 165, 233, 0.13);
}

.stage-item.state-done {
  border-color: #86efac;
  background: #ffffff;
}

.stage-item.locked {
  opacity: 0.56;
  cursor: not-allowed;
}

.stage-main {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  min-width: 0;
}

.stage-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 2rem;
  font-family: 'Poppins', sans-serif;
  font-size: 0.72rem;
  font-weight: 700;
  color: #94a3b8;
}

.stage-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.92);
  color: #0284c7;
  flex-shrink: 0;
}

.stage-copy {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  min-width: 0;
}

.stage-copy strong {
  font-size: 0.92rem;
  color: #0f172a;
}

.stage-copy small {
  color: #64748b;
  font-size: 0.74rem;
  line-height: 1.45;
}

.stage-state {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 1.9rem;
  padding: 0.15rem 0.6rem;
  border-radius: 999px;
  border: 1px solid #e2e8f0;
  background: rgba(255, 255, 255, 0.78);
  color: #0369a1;
  font-size: 0.72rem;
  font-weight: 700;
}

.stage-state.state-done {
  border-color: #86efac;
  color: #15803d;
  background: rgba(240, 253, 244, 0.92);
}

.w-4 {
  width: 1rem;
  height: 1rem;
}

@media (max-width: 900px) {
  .workflow-rail {
    border-radius: 24px;
  }
}
</style>
