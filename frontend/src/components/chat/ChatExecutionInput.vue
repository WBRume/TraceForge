<script setup lang="ts">
import { Loader2, Send, Square, UsersRound } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps<{
  modelValue: string
  disabled: boolean
  running: boolean
  canInterrupt: boolean
  interrupting: boolean
  placeholder: string
  sendTitle: string
  interruptTitle: string
  canStartPreInput?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'submit'): void
  (e: 'interrupt'): void
  (e: 'pre-input'): void
}>()

const onInput = (event: Event) => {
  const target = event.target as HTMLInputElement
  emit('update:modelValue', target.value)
}
</script>

<template>
  <div class="chat-execution-row" :class="{ 'is-running': props.running }">
    <div class="chat-input-area" :class="{ 'is-disabled': props.disabled, 'is-running': props.running }">
      <div v-if="props.running" class="execution-activity" aria-hidden="true">
        <span></span>
        <span></span>
        <span></span>
      </div>
      <input
        :value="props.modelValue"
        type="text"
        class="chat-input"
        :placeholder="props.placeholder"
        :disabled="props.disabled"
        @input="onInput"
        @keyup.enter="emit('submit')"
      >
      <button
        v-if="props.canStartPreInput !== false"
        class="preinput-btn"
        :disabled="props.disabled"
        :title="t('preInput.toggle_title')"
        @click="emit('pre-input')"
      >
        <UsersRound class="w-4 h-4" />
      </button>
      <button class="send-btn" :disabled="props.disabled || !props.modelValue.trim()" :title="props.sendTitle" @click="emit('submit')">
        <Send class="w-5 h-5" />
      </button>
    </div>
    <button
      v-if="props.running"
      class="interrupt-square-btn"
      :disabled="!props.canInterrupt || props.interrupting"
      :title="props.interruptTitle"
      @click="emit('interrupt')"
    >
      <Loader2 v-if="props.interrupting" class="w-4 h-4 spin" />
      <Square v-else class="w-4 h-4" />
    </button>
  </div>
</template>

<style scoped>
.chat-execution-row {
  margin: var(--space-4) var(--space-6);
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.chat-input-area {
  padding: 8px 10px 8px 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  background-color: white;
  border-radius: 24px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.05);
  flex: 1;
  min-width: 0;
}

.chat-input-area.is-disabled {
  opacity: 0.65;
}

.chat-input-area.is-running {
  box-shadow: 0 8px 22px rgba(37, 99, 235, 0.12);
}

.execution-activity {
  width: 34px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.execution-activity span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--color-primary-500);
  animation: execution-bounce 0.9s ease-in-out infinite;
}

.execution-activity span:nth-child(2) {
  animation-delay: 0.12s;
}

.execution-activity span:nth-child(3) {
  animation-delay: 0.24s;
}

.chat-input {
  flex: 1;
  min-width: 0;
  border: none;
  background: transparent;
  font-size: 1rem;
  padding: 8px 0;
  outline: none;
}

.interrupt-square-btn,
.send-btn {
  border: none;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: transform 0.2s, background-color 0.2s, color 0.2s;
}

.interrupt-square-btn {
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
  border-radius: 8px;
  background: #fee2e2;
  color: #991b1b;
  box-shadow: 0 4px 12px rgba(153, 27, 27, 0.12);
}

.interrupt-square-btn:hover:not(:disabled) {
  transform: scale(1.04);
  background: #fecaca;
}

.send-btn {
  border-radius: 50%;
  background: var(--color-primary-500);
  color: white;
}

.preinput-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  border-radius: var(--radius-md, 8px);
  border: 1px solid #E2E8F0;
  background: #F8FAFC;
  color: #64748B;
  transition: background-color 0.2s, color 0.2s, border-color 0.2s;
}

.preinput-btn:hover:not(:disabled) {
  background: var(--color-primary-50, #F0F9FF);
  border-color: #BAE6FD;
  color: var(--color-primary-600, #0284C7);
}

.send-btn:hover:not(:disabled) {
  transform: scale(1.05);
  background: var(--color-primary-600);
}

.interrupt-square-btn:disabled,
.send-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  transform: none;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes execution-bounce {
  0%, 80%, 100% {
    transform: translateY(0);
    opacity: 0.45;
  }
  40% {
    transform: translateY(-5px);
    opacity: 1;
  }
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
