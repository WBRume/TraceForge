<script setup lang="ts">
/**
 * ToggleSwitch: 拨动开关（视觉替代原生多选框）。
 * 保留原生 checkbox 语义（role="switch" + 原生 change），
 * 轨道颜色通过 CSS 变量 --toggle-active 覆盖（默认主题蓝）。
 */
defineProps<{
  modelValue?: boolean
  disabled?: boolean
  ariaLabel?: string
  id?: string
}>()

const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const onChange = (event: Event) => {
  emit('update:modelValue', (event.target as HTMLInputElement).checked)
}
</script>

<template>
  <label class="toggle-switch">
    <input
      :id="id"
      type="checkbox"
      role="switch"
      class="toggle-input"
      :aria-label="ariaLabel"
      :checked="!!modelValue"
      :disabled="disabled"
      @change="onChange"
    />
    <span class="toggle-track" aria-hidden="true"><span class="toggle-thumb" /></span>
  </label>
</template>

<style scoped>
.toggle-switch {
  display: inline-flex;
  align-items: center;
  cursor: pointer;
  flex-shrink: 0;
}

.toggle-input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  margin: 0;
}

.toggle-track {
  position: relative;
  display: inline-flex;
  align-items: center;
  width: 40px;
  height: 22px;
  padding: 2px;
  border-radius: 999px;
  background: #e2e8f0;
  box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.06), inset 0 1px 2px rgba(15, 23, 42, 0.1);
  box-sizing: border-box;
  transition: background 0.25s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.25s ease;
}

.toggle-thumb {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #ffffff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.25), 0 0 0 1px rgba(15, 23, 42, 0.04);
  transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.toggle-input:checked + .toggle-track {
  background: var(--toggle-active, #0ea5e9);
  box-shadow: inset 0 0 0 1px rgba(2, 132, 199, 0.15), inset 0 1px 2px rgba(2, 132, 199, 0.25), 0 2px 6px rgba(14, 165, 233, 0.28);
}

.toggle-input:checked + .toggle-track .toggle-thumb {
  transform: translateX(18px);
}

.toggle-input:disabled + .toggle-track {
  opacity: 0.5;
  cursor: default;
}

.toggle-input:not(:disabled) + .toggle-track:hover {
  background: #cbd5e1;
}

.toggle-input:checked:not(:disabled) + .toggle-track:hover {
  background: var(--toggle-active, #0ea5e9);
  filter: brightness(1.06);
}

.toggle-input:focus-visible + .toggle-track {
  outline: 2px solid rgba(14, 165, 233, 0.5);
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  .toggle-track,
  .toggle-thumb {
    transition: none;
  }
}
</style>
