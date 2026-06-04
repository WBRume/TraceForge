<script setup lang="ts">
import { nextTick, ref } from 'vue'

const props = defineProps<{
  modelValue: string
  disabled: boolean
  busy: boolean
  placeholder: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'submit'): void
  (e: 'tab-complete'): void
  (e: 'history-prev'): void
  (e: 'history-next'): void
}>()

const inputEl = ref<HTMLInputElement | null>(null)

const onInput = (event: Event) => {
  const target = event.target as HTMLInputElement
  emit('update:modelValue', target.value)
}

const focusInput = async () => {
  await nextTick()
  if (props.disabled || props.busy) return
  inputEl.value?.focus()
}

defineExpose({
  focusInput,
})
</script>

<template>
  <div class="cli-input-shell" :class="{ 'is-disabled': props.disabled }">
    <span class="cli-prompt">$</span>
    <input
      ref="inputEl"
      :value="props.modelValue"
      type="text"
      class="cli-input"
      :disabled="props.disabled || props.busy"
      :placeholder="props.placeholder"
      @input="onInput"
      @keydown.enter.prevent="emit('submit')"
      @keydown.tab.prevent="emit('tab-complete')"
      @keydown.up.prevent="emit('history-prev')"
      @keydown.down.prevent="emit('history-next')"
    >
    <button
      class="cli-send-btn"
      :disabled="props.disabled || props.busy || !props.modelValue.trim()"
      @click="emit('submit')"
    >
      Run
    </button>
  </div>
</template>

<style scoped>
.cli-input-shell {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid #243044;
  background: #09101d;
  border-radius: 10px;
  padding: 8px 10px;
}

.cli-input-shell.is-disabled {
  opacity: 0.65;
}

.cli-prompt {
  color: #39d98a;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
}

.cli-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  color: #d4deea;
  font-size: 13px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
}

.cli-input::placeholder {
  color: #6f8098;
}

.cli-send-btn {
  border: 1px solid #2a3a53;
  background: #111b2c;
  color: #d4deea;
  border-radius: 8px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
}

.cli-send-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
</style>
