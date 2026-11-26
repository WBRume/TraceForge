<script setup lang="ts">
import { useTemplateRef } from 'vue'
import { ElTooltip, type TooltipInstance } from 'element-plus'

defineProps<{
  label: string
  shortcuts?: readonly string[]
  placement?: 'top' | 'bottom'
}>()

const tooltip = useTemplateRef<TooltipInstance>('tooltip')
const displayKey = (keys: string) => keys.replace(/^Control\+/, 'Ctrl+').replace(/^Meta\+/, '⌘')
</script>

<template>
  <ElTooltip ref="tooltip" :placement="placement ?? 'bottom'" :show-after="120" :hide-after="0"
    :enterable="false" :trigger-keys="[]">
    <span class="hint-trigger" @focusin="tooltip?.onOpen($event)" @focusout="tooltip?.onClose($event)"
      @click="tooltip?.onClose($event)" @keydown.esc="tooltip?.onClose($event)">
      <slot />
    </span>
    <template #content>
      <span class="hint-content">
        <span>{{ label }}</span>
        <template v-for="(shortcut, index) in shortcuts" :key="shortcut">
          <span v-if="index">/</span>
          <kbd>{{ displayKey(shortcut) }}</kbd>
        </template>
      </span>
    </template>
  </ElTooltip>
</template>

<style scoped>
.hint-trigger { display: inline-flex; align-items: center; }
.hint-trigger :deep(button:disabled) { pointer-events: none; }
.hint-content { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.hint-content kbd { padding: 1px 4px; border-radius: var(--radius-sm); background: rgb(255 255 255 / 14%); font: 500 11px var(--font-mono); }
</style>
