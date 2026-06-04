<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { AlertTriangle, Loader2 } from 'lucide-vue-next'

type Tone = 'danger' | 'primary' | 'success'

const props = withDefaults(defineProps<{
  show: boolean
  title: string
  message: string
  description?: string
  emphasisLabel?: string
  emphasisValue?: string
  cancelText: string
  confirmText: string
  tone?: Tone
  loading?: boolean
}>(), {
  description: '',
  emphasisLabel: '',
  emphasisValue: '',
  tone: 'danger',
  loading: false,
})

const emit = defineEmits<{
  (e: 'cancel'): void
  (e: 'confirm'): void
}>()

const toneClass = computed(() => `is-${props.tone}`)
const overlayCloseArmed = ref(false)

const handleCancel = () => {
  if (props.loading) return
  emit('cancel')
}

const handleConfirm = () => {
  if (props.loading) return
  emit('confirm')
}

const armOverlayClose = (event: PointerEvent) => {
  if (props.loading || event.button !== 0) return
  overlayCloseArmed.value = true
}

const cancelOverlayClose = () => {
  overlayCloseArmed.value = false
}

const finishOverlayClose = () => {
  if (!overlayCloseArmed.value) return
  overlayCloseArmed.value = false
  handleCancel()
}

onMounted(() => {
  window.addEventListener('blur', cancelOverlayClose)
})

onBeforeUnmount(() => {
  window.removeEventListener('blur', cancelOverlayClose)
})
</script>

<template>
  <div
    v-if="show"
    class="modal-overlay"
    @pointerdown.self="armOverlayClose"
    @pointerup.self="finishOverlayClose"
    @pointerleave.self="cancelOverlayClose"
    @pointercancel.self="cancelOverlayClose"
  >
    <div class="modal glass-panel" :class="toneClass">
      <div class="modal-header" :class="toneClass">
        <slot name="icon">
          <AlertTriangle class="w-6 h-6 flex-shrink-0" />
        </slot>
        <span class="modal-title">{{ title }}</span>
      </div>

      <p class="modal-message">{{ message }}</p>
      <div v-if="emphasisValue" class="modal-emphasis" :class="toneClass">
        <p v-if="emphasisLabel" class="modal-emphasis-label">{{ emphasisLabel }}</p>
        <p class="modal-emphasis-value">{{ emphasisValue }}</p>
      </div>
      <p v-if="description" class="modal-desc">{{ description }}</p>
      <div v-if="$slots.content" class="modal-content">
        <slot name="content" />
      </div>

      <div class="modal-actions">
        <button class="btn-secondary" :disabled="loading" @click="handleCancel">
          {{ cancelText }}
        </button>
        <button class="confirm-btn" :class="toneClass" :disabled="loading" @click="handleConfirm">
          <Loader2 v-if="loading" class="w-4 h-4 spin" />
          <span>{{ confirmText }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 120;
}

.modal {
  width: 90%;
  max-width: 500px;
  padding: var(--space-8);
  background-color: var(--color-surface-white);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-2xl);
  border-top: 4px solid #f43f5e;
}

.modal.is-primary {
  border-top-color: var(--color-primary-500);
}

.modal.is-success {
  border-top-color: var(--color-accent-emerald);
}

.modal-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
  color: #e11d48;
}

.modal-header.is-primary {
  color: var(--color-primary-600);
}

.modal-header.is-success {
  color: var(--color-accent-emerald);
}

.modal-title {
  font-size: 1.25rem;
  font-weight: 700;
  line-height: 1;
}

.modal-message {
  margin: 0;
  font-size: 0.875rem;
  color: #475569;
  line-height: 1.6;
}

.modal-desc {
  margin: var(--space-4) 0 0;
  font-size: 0.875rem;
  color: #475569;
  line-height: 1.6;
}

.modal-emphasis {
  margin-top: var(--space-4);
  padding: 10px 12px;
  border-radius: var(--radius-md);
  border: 1px solid #fecdd3;
  background: #fff1f2;
}

.modal-emphasis.is-primary {
  border-color: #bfdbfe;
  background: #eff6ff;
}

.modal-emphasis.is-success {
  border-color: #a7f3d0;
  background: #ecfdf5;
}

.modal-emphasis-label {
  margin: 0 0 4px;
  font-size: 0.75rem;
  font-weight: 700;
  color: #9f1239;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.modal-emphasis.is-primary .modal-emphasis-label {
  color: #1d4ed8;
}

.modal-emphasis.is-success .modal-emphasis-label {
  color: #047857;
}

.modal-emphasis-value {
  margin: 0;
  color: #9f1239;
  font-size: 0.8125rem;
  font-family: 'Consolas', 'Courier New', monospace;
  line-height: 1.5;
  word-break: break-all;
}

.modal-emphasis.is-primary .modal-emphasis-value {
  color: #1d4ed8;
}

.modal-emphasis.is-success .modal-emphasis-value {
  color: #047857;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  margin-top: var(--space-6);
}

.modal-content {
  margin-top: var(--space-4);
}

.confirm-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  border: none;
  border-radius: 8px;
  padding: 0.5rem 1rem;
  color: #fff;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.confirm-btn.is-danger {
  background: #ef4444;
}

.confirm-btn.is-danger:hover {
  background: #dc2626;
}

.confirm-btn.is-primary {
  background: var(--color-primary-500);
}

.confirm-btn.is-primary:hover {
  background: var(--color-primary-600);
}

.confirm-btn.is-success {
  background: var(--color-accent-emerald);
}

.confirm-btn.is-success:hover {
  background: #059669;
}

.confirm-btn:disabled,
.btn-secondary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}

.w-6 {
  width: 1.5rem;
  height: 1.5rem;
}

.spin {
  animation: spin 1s linear infinite;
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
