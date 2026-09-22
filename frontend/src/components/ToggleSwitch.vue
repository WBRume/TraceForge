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
}>()

const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const onChange = (event: Event) => {
  emit('update:modelValue', (event.target as HTMLInputElement).checked)
}
</script>

<template>
  <label class="toggle-switch">
    <input
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
  display: inline-flex;
  align-items: center;
  width: 34px;
  height: 18px;
  padding: 2px;
  border-radius: 999px;
  background: #cbd5e1;
  box-sizing: border-box;
  transition: background 0.2s ease;
}

.toggle-thumb {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #ffffff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.3);
  transition: transform 0.2s ease;
}

.toggle-input:checked + .toggle-track {
  background: var(--toggle-active, #0ea5e9);
}

.toggle-input:checked + .toggle-track .toggle-thumb {
  transform: translateX(16px);
}

.toggle-input:disabled + .toggle-track {
  opacity: 0.45;
  cursor: default;
}

.toggle-input:not(:disabled) + .toggle-track:hover {
  background: #94a3b8;
}

.toggle-input:checked:not(:disabled) + .toggle-track:hover {
  background: var(--toggle-active, #0ea5e9);
  filter: brightness(1.08);
}

.toggle-input:focus-visible + .toggle-track {
  outline: 2px solid #7dd3fc;
  outline-offset: 1px;
}
</style>
