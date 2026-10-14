<script setup lang="ts">
import type { TaskCreateMode } from './types'
defineProps<{ mode: TaskCreateMode; disabled: boolean }>()
const emit = defineEmits<{ change: [mode: TaskCreateMode] }>()
</script>

<template>
  <div class="create-mode-bar">
    <div class="create-mode-switch" role="group" :aria-label="$t('task_create.mode')">
      <button v-for="item in (['guided', 'quick'] as const)" :key="item" type="button" :data-mode="item" :aria-pressed="mode === item"
        :disabled="disabled" :class="{ active: mode === item }" @click="emit('change', item)">{{ $t(`task_create.${item}`) }}</button>
    </div>
    <span class="create-mode-hint">{{ $t(`task_create.${mode}_hint`) }}</span>
  </div>
</template>

<style scoped>
.create-mode-bar { display: flex; align-items: center; gap: 12px; padding: 12px 22px; border-bottom: 1px solid #f1f5f9; flex-wrap: wrap; }
.create-mode-switch { display: inline-flex; padding: 3px; border-radius: 8px; background: #f1f5f9; flex-shrink: 0; }
.create-mode-switch button { border: 0; padding: 6px 12px; border-radius: 6px; background: transparent; color: #64748b; cursor: pointer; font-size: 12px; font-weight: 600; }
.create-mode-switch button.active { background: white; color: #0369a1; box-shadow: 0 1px 3px #0f172a1a; }
.create-mode-hint { font-size: 12px; color: #64748b; }
@media (max-width: 560px) { .create-mode-bar { padding: 10px 12px; gap: 8px; } }
</style>
