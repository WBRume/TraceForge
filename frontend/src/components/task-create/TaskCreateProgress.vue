<script setup lang="ts">
import type { TaskCreateStep } from './types'

defineProps<{ step: TaskCreateStep; disabled: boolean }>()
const emit = defineEmits<{ navigate: [step: TaskCreateStep] }>()
const steps: TaskCreateStep[] = ['content', 'environment', 'options', 'review']
</script>

<template>
  <nav class="create-progress" :aria-label="$t('task_create.progress')">
    <ol class="progress-list">
      <li v-for="(item, index) in steps" :key="item">
        <button type="button" class="progress-step" :class="{ current: item === step, previous: index < steps.indexOf(step) }"
          :aria-current="item === step ? 'step' : undefined" :disabled="disabled || index > steps.indexOf(step)"
          @click="emit('navigate', item)">
          <span class="step-number">{{ index + 1 }}</span>
          <span>{{ $t(`task_create.steps.${item}.title`) }}</span>
        </button>
      </li>
    </ol>
  </nav>
</template>

<style scoped>
.create-progress { padding: 14px 22px; border-bottom: 1px solid #e2e8f0; background: #f8fafc; }
.progress-list { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 0; padding: 0; list-style: none; }
.progress-step { display: flex; align-items: center; gap: 8px; padding: 0; border: 0; background: transparent; color: #64748b; font-size: 12px; text-align: left; cursor: pointer; }
.progress-step:disabled { cursor: default; }
.step-number { display: grid; place-items: center; width: 24px; height: 24px; flex-shrink: 0; border: 1px solid #cbd5e1; border-radius: 50%; }
.current { color: #0369a1; font-weight: 700; }
.current .step-number { border-color: #0284c7; background: #0284c7; color: white; }
.previous .step-number { background: #e0f2fe; border-color: #7dd3fc; color: #0369a1; }
@media (max-width: 560px) {
  .create-progress { padding: 12px; }
  .progress-step { flex-direction: column; align-items: flex-start; gap: 5px; font-size: 11px; }
}
</style>
