<script setup lang="ts">
import { computed } from 'vue'
import { CheckCircle2, X, XCircle } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import CompleteCloseoutForm from './CompleteCloseoutForm.vue'
import FailCloseoutForm from './FailCloseoutForm.vue'
import { useTaskCloseout } from '@/composables/useTaskCloseout'
import type { CompleteCloseoutPayload, FailCloseoutPayload } from '@/types/taskCloseout'

const props = defineProps<{
  show: boolean
  mode: 'complete' | 'fail'
  workspaceId: string
  taskId: string
  taskName?: string
}>()

const emit = defineEmits<{
  close: []
  success: [status: string]
}>()

const { t } = useI18n()
const closeout = useTaskCloseout()

const title = computed(() => props.mode === 'complete'
  ? t('chat.closeout.complete_title')
  : t('chat.closeout.failure_title'))

const description = computed(() => props.mode === 'complete'
  ? t('chat.closeout.complete_desc')
  : t('chat.closeout.failure_desc'))

async function submitComplete(payload: Omit<CompleteCloseoutPayload, 'evidence_attachments'>, files: File[]) {
  const result = await closeout.completeTask(props.workspaceId, props.taskId, payload, files)
  if (result) emit('success', result.status)
}

async function submitFailure(payload: Omit<FailCloseoutPayload, 'evidence_attachments'>, files: File[]) {
  const result = await closeout.failTask(props.workspaceId, props.taskId, payload, files)
  if (result) emit('success', result.status)
}
</script>

<template>
  <Teleport to="body">
    <div v-if="show" class="modal-overlay" @pointerdown.self="emit('close')">
      <section
        class="modal glass-panel closeout-modal"
        :class="mode === 'complete' ? 'complete-modal' : 'fail-modal'"
        role="dialog"
        aria-modal="true"
      >
        <header class="modal-header">
          <div class="header-pattern" />
          <div class="header-icon" :class="mode === 'complete' ? 'success' : 'fail'">
            <div class="icon-ring" />
            <CheckCircle2 v-if="mode === 'complete'" :size="24" />
            <XCircle v-else :size="24" />
          </div>
          
          <div class="header-text">
            <span class="eyebrow" :class="mode === 'complete' ? 'text-success' : 'text-fail'">
              {{ t('chat.closeout.eyebrow') }}
            </span>
            <h2>{{ title }}</h2>
            <p class="description">{{ description }}</p>
            <div v-if="taskName" class="task-badge">
              <span class="label">Task</span>
              <span class="dot" />
              <span class="value">{{ taskName }}</span>
            </div>
          </div>

          <button type="button" class="close-btn" :disabled="closeout.saving.value" @click="emit('close')">
            <X :size="20" />
          </button>
        </header>

        <div class="modal-content">
          <CompleteCloseoutForm
            v-if="mode === 'complete'"
            :saving="closeout.saving.value"
            @cancel="emit('close')"
            @submit="submitComplete"
          />
          <FailCloseoutForm
            v-else
            :saving="closeout.saving.value"
            @cancel="emit('close')"
            @submit="submitFailure"
          />

          <Transition name="fade">
            <div v-if="closeout.error.value" class="server-error">
              <div class="error-indicator" />
              <span>{{ closeout.error.value }}</span>
            </div>
          </Transition>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(8px);
  animation: fade-in 0.3s ease-out;
}

@keyframes fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

.modal {
  width: min(860px, 100%);
  max-height: min(900px, 92vh);
  background: #ffffff;
  border-radius: 1.5rem;
  box-shadow: 
    0 10px 15px -3px rgba(0, 0, 0, 0.1),
    0 25px 50px -12px rgba(0, 0, 0, 0.25);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.2);
  animation: modal-enter 0.4s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes modal-enter {
  from { 
    opacity: 0; 
    transform: scale(0.95) translateY(15px); 
  }
  to { 
    opacity: 1; 
    transform: scale(1) translateY(0); 
  }
}

.modal-header {
  position: relative;
  display: flex;
  align-items: center;
  gap: 1.25rem;
  padding: 1.5rem 2rem;
  border-bottom: 1px solid #f1f5f9;
  background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
  overflow: hidden;
}

.header-pattern {
  position: absolute;
  inset: 0;
  opacity: 0.03;
  pointer-events: none;
  background-image: radial-gradient(#0f172a 1px, transparent 0);
  background-size: 20px 20px;
}

.header-icon {
  position: relative;
  width: 2.75rem;
  height: 2.75rem;
  border-radius: 0.875rem;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  z-index: 1;
}

.icon-ring {
  position: absolute;
  inset: -3px;
  border: 2px solid currentColor;
  border-radius: 1rem;
  opacity: 0.1;
}

.header-icon.success {
  background: #f0fdf4;
  color: #10b981;
}

.header-icon.fail {
  background: #fef2f2;
  color: #ef4444;
}

.header-text {
  flex: 1;
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.eyebrow {
  font-size: 0.65rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  display: block;
}

.text-success { color: #10b981; }
.text-fail { color: #ef4444; }

h2 {
  font-family: 'Poppins', sans-serif;
  font-size: 1.25rem;
  font-weight: 700;
  margin: 0;
  color: #0f172a;
  letter-spacing: -0.01em;
}

.description {
  margin: 2px 0 0;
  color: #64748b;
  font-size: 0.875rem;
  line-height: 1.4;
}

.task-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  padding: 2px 8px;
  background: rgba(241, 245, 249, 0.8);
  backdrop-filter: blur(4px);
  border-radius: 0.5rem;
  border: 1px solid #e2e8f0;
  font-size: 11px;
  width: fit-content;
}

.task-badge .label {
  color: #94a3b8;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.task-badge .dot {
  width: 2px;
  height: 2px;
  border-radius: 50%;
  background: #cbd5e1;
}

.task-badge .value {
  color: #334155;
  font-weight: 600;
}

.close-btn {
  position: relative;
  width: 2.5rem;
  height: 2.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 0.875rem;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  z-index: 1;
}

.close-btn:hover {
  background: #f8fafc;
  color: #0f172a;
  border-color: #cbd5e1;
  transform: translateY(-1px);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}

.modal-content {
  flex: 1;
  overflow-y: auto;
  padding: 2.25rem;
}

.server-error {
  margin-top: 1.5rem;
  padding: 1rem 1.25rem;
  background: #fff1f2;
  border: 1px solid #fecdd3;
  border-radius: 0.75rem;
  color: #be123c;
  font-size: 0.875rem;
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.error-indicator {
  width: 4px;
  height: 1rem;
  background: #e11d48;
  border-radius: 2px;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@media (max-width: 640px) {
  .modal-header {
    padding: 1.5rem;
    gap: 1rem;
  }
  .header-icon {
    width: 2.75rem;
    height: 2.75rem;
  }
  h2 {
    font-size: 1.375rem;
  }
  .modal-content {
    padding: 1.5rem;
  }
}
</style>


