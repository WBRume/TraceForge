<script setup lang="ts">
import { watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { MicrophoneIcon } from '@heroicons/vue/24/outline'
import { Loader2, Square, X } from '@/components/icons'
import { useSpeechInput } from '@/composables/useSpeechInput'

const props = defineProps<{ disabled: boolean; contextKey: string }>()
const emit = defineEmits<{ transcript: [text: string]; busy: [value: boolean] }>()
const { t } = useI18n()
const { mode, ready, state, error, connecting, seconds, level, busy, visible, start, stop, cancel } = useSpeechInput({
  disabled: () => props.disabled, contextKey: () => props.contextKey,
  onTranscript: text => emit('transcript', text),
})
const buttonLabel = () => t(state.value === 'recording' ? 'speech.stop' : `speech.start_${mode}`)
watch(busy, value => emit('busy', value), { flush: 'sync' })
defineExpose({ cancel })
</script>

<template>
  <div v-if="visible" class="speech-input" :class="{ 'is-busy': busy, recording: state === 'recording' }">
    <button
      type="button"
      class="speech-button"
      :class="{ recording: state === 'recording' }"
      :disabled="disabled || !ready || state === 'starting' || state === 'transcribing'"
      :title="!ready ? t('speech.missing_assets') : buttonLabel()"
      :aria-label="buttonLabel()"
      :aria-pressed="state === 'recording'"
      @click="state === 'recording' ? stop() : start()"
    >
      <Square v-if="state === 'recording'" :size="10" class="stop-icon" />
      <Loader2 v-else-if="busy" :size="16" class="spin" />
      <MicrophoneIcon v-else class="mic-icon" />
    </button>
    <template v-if="state === 'recording'">
      <span class="speech-level" aria-hidden="true">
        <i
          v-for="(scale, idx) in [0.55, 0.95, 1.25, 0.85, 0.5]"
          :key="idx"
          class="wave-bar"
          :style="{ transform: `scaleY(${Math.min(1, Math.max(0.2, 0.2 + level * scale * 0.8))})` }"
        />
      </span>
      <span class="speech-timer">{{ seconds }}s</span>
    </template>
    <span v-if="busy" class="capsule-divider" aria-hidden="true" />
    <button
      v-if="busy"
      type="button"
      class="speech-cancel-button"
      :aria-label="t('speech.cancel')"
      :title="t('speech.cancel')"
      @click="cancel"
    >
      <X :size="12" :stroke-width="2.5" />
    </button>
    <span
      v-if="busy || error"
      class="speech-message"
      :class="{ error: error }"
      role="status"
      aria-live="polite"
    >
      {{ error ? t(`speech.${error}`) : t(`speech.${state === 'recording' && connecting ? 'recording_connecting' : state}`) }}
    </span>
  </div>
</template>

<style scoped>
.speech-input {
  position: relative;
  display: inline-flex;
  align-items: center;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

/* 录音/忙碌时的纯白极简灰胶囊外壳 */
.speech-input.is-busy {
  height: 32px;
  padding: 0 6px 0 5px;
  background: var(--color-surface-white, #ffffff);
  border: 1px solid #cbd5e1;
  border-radius: 9999px;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.06), inset 0 1px 0 rgba(255, 255, 255, 0.9);
  gap: 8px;
  animation: spring-pop 0.32s cubic-bezier(0.34, 1.56, 0.64, 1);
  user-select: none;
}

@keyframes spring-pop {
  0% { transform: scale(0.72) translateY(2px); opacity: 0; }
  70% { transform: scale(1.04) translateY(-1px); }
  100% { transform: scale(1) translateY(0); opacity: 1; }
}

/* 主操作按钮（空闲时为普通图标按钮，录音时为珊瑚红圆钮） */
.speech-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 30px;
  min-width: 30px;
  padding: 0;
  border: 0;
  border-radius: 8px;
  color: var(--color-text-muted, #64748b);
  background: transparent;
  cursor: pointer;
  transition: all 0.2s ease;
}

.speech-button:hover:not(:disabled) {
  background: var(--color-primary-50, #f0f9ff);
  color: var(--color-primary, #0ea5e9);
}

.speech-button:disabled {
  opacity: 0.5;
  cursor: default;
}

/* 录音中的哑光珊瑚红圆钮 */
.speech-button.recording {
  width: 22px;
  height: 22px;
  min-width: 22px;
  border-radius: 50%;
  background: #f43f5e;
  color: #ffffff;
  box-shadow: 0 2px 6px rgba(244, 63, 94, 0.35);
  flex-shrink: 0;
}

.speech-button.recording:hover:not(:disabled) {
  background: #e11d48;
  transform: scale(1.08);
}

.stop-icon {
  fill: currentColor;
}

.mic-icon {
  width: 18px;
  height: 18px;
}

/* 5 柱彩虹渐变音波跳动 */
.speech-level {
  display: flex;
  align-items: center;
  gap: 3px;
  height: 16px;
}

.speech-level .wave-bar {
  width: 3px;
  height: 16px;
  border-radius: 3px;
  transform: scaleY(0.25);
  transform-origin: center;
  transition: transform 80ms linear;
}

.speech-level .wave-bar:nth-child(1) { background: linear-gradient(180deg, #38bdf8, #818cf8); }
.speech-level .wave-bar:nth-child(2) { background: linear-gradient(180deg, #818cf8, #c084fc); }
.speech-level .wave-bar:nth-child(3) { background: linear-gradient(180deg, #c084fc, #f472b6); }
.speech-level .wave-bar:nth-child(4) { background: linear-gradient(180deg, #f472b6, #fb7185); }
.speech-level .wave-bar:nth-child(5) { background: linear-gradient(180deg, #38bdf8, #34d399); }

@media (prefers-reduced-motion: reduce) {
  .speech-level .wave-bar { transition: none; }
}

/* 秒数计时 */
.speech-timer {
  font-size: 12px;
  font-weight: 700;
  color: #0f172a;
  min-width: 20px;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

/* 分割线 */
.capsule-divider {
  width: 1px;
  height: 14px;
  background: #e2e8f0;
  flex-shrink: 0;
}

/* 取消按钮 */
.speech-cancel-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  padding: 0;
  transition: all 0.15s ease;
  flex-shrink: 0;
}

.speech-cancel-button:hover {
  color: #f43f5e;
  background: #ffe4e6;
}

/* 精致半透明毛玻璃微提示气泡 */
.speech-message {
  position: absolute;
  bottom: calc(100% + 10px);
  right: 0;
  width: max-content;
  max-width: 280px;
  padding: 5px 11px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(10px);
  color: #334155;
  font-size: 11.5px;
  font-weight: 500;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  white-space: nowrap;
  pointer-events: none;
  animation: float-tooltip 2s ease-in-out infinite alternate, fade-tooltip 0.25s ease;
  z-index: 40;
}

.speech-message::after {
  content: '';
  position: absolute;
  bottom: -5px;
  right: 14px;
  width: 8px;
  height: 8px;
  background: #ffffff;
  border-right: 1px solid #e2e8f0;
  border-bottom: 1px solid #e2e8f0;
  transform: rotate(45deg);
}

.speech-message.error {
  color: #b91c1c;
  border-color: #fecaca;
  background: #fff5f5;
}

.speech-message.error::after {
  background: #fff5f5;
  border-color: #fecaca;
}

@keyframes float-tooltip {
  from { transform: translateY(0); }
  to { transform: translateY(-3px); }
}

@keyframes fade-tooltip {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
