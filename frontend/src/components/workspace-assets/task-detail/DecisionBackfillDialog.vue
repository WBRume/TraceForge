<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { ClipboardList, X } from 'lucide-vue-next'
import { useTaskDetailAssets } from '@/composables/useTaskDetailAssets'
import DecisionBackfillForm from './DecisionBackfillForm.vue'
import type {
  DecisionMutationPayload,
  TaskRequirementLink,
  HumanDeltaLight,
  EvidenceLight,
} from '@/types/workspaceAssets'

const props = defineProps<{
  visible: boolean
  workspaceId: string
  taskId: string
  requirementLinks?: TaskRequirementLink[]
  humanDeltas?: HumanDeltaLight[]
  evidence?: EvidenceLight[]
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  mutated: []
}>()

const { t } = useI18n()
const taskAssets = useTaskDetailAssets()
const formRef = ref<InstanceType<typeof DecisionBackfillForm> | null>(null)

function handleSubmit() {
  formRef.value?.submit()
}

async function submitDecision(payload: DecisionMutationPayload) {
  const result = await taskAssets.createDecision(props.workspaceId, props.taskId, payload)
  if (result) {
    ElMessage.success(t('workspace_assets.task_detail.workbench.backfill_dialog.success'))
    emit('update:visible', false)
    emit('mutated')
  }
}

function handleOverlayPointerDown(e: PointerEvent) {
  if ((e.target as HTMLElement).classList.contains('modal-overlay')) {
    emit('update:visible', false)
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="modal-overlay" @pointerdown="handleOverlayPointerDown">
      <section class="modal glass-panel backfill-modal" role="dialog" aria-modal="true">
        <header class="modal-header">
          <div class="header-pattern" />
          <div class="header-icon">
            <div class="icon-ring" />
            <ClipboardList :size="24" />
          </div>

          <div class="header-text">
            <span class="eyebrow">{{ t('workspace_assets.task_detail.workbench.decisions.eyebrow') }}</span>
            <h2>{{ t('workspace_assets.task_detail.workbench.backfill_dialog.title') }}</h2>
          </div>

          <button type="button" class="close-btn" :disabled="taskAssets.saving.value" @click="emit('update:visible', false)">
            <X :size="20" />
          </button>
        </header>

        <div class="modal-content">
          <DecisionBackfillForm
            ref="formRef"
            :requirement-links="requirementLinks ?? []"
            :human-deltas="humanDeltas ?? []"
            :evidence="evidence ?? []"
            :saving="taskAssets.saving.value"
            :hide-actions="true"
            @submit="submitDecision"
          />

          <Transition name="fade">
            <div v-if="taskAssets.error.value" class="server-error">
              <div class="error-indicator" />
              <span>{{ taskAssets.error.value }}</span>
            </div>
          </Transition>

          <div class="modal-actions">
            <button type="button" class="btn-cancel" :disabled="taskAssets.saving.value" @click="emit('update:visible', false)">
              {{ t('common.cancel') }}
            </button>
            <button type="button" class="btn-submit btn-primary" :disabled="taskAssets.saving.value" @click="handleSubmit">
              <span v-if="taskAssets.saving.value" class="spinner" />
              {{ taskAssets.saving.value ? t('common.saving') : t('workspace_assets.task_detail.workbench.backfill_dialog.submit') }}
            </button>
          </div>
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
  width: min(680px, 100%);
  max-height: min(800px, 92vh);
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
  background: #eff6ff;
  color: #3b82f6;
}

.icon-ring {
  position: absolute;
  inset: -3px;
  border: 2px solid currentColor;
  border-radius: 1rem;
  opacity: 0.1;
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
  color: #3b82f6;
  display: block;
}

h2 {
  font-family: 'Poppins', sans-serif;
  font-size: 1.25rem;
  font-weight: 700;
  margin: 0;
  color: #0f172a;
  letter-spacing: -0.01em;
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
  padding: 2rem;
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

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  margin-top: 1.5rem;
  padding-top: 1.5rem;
  border-top: 1px solid #f1f5f9;
}

.btn-cancel {
  padding: 0.625rem 1.25rem;
  font-size: 0.875rem;
  font-weight: 600;
  color: #64748b;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-cancel:hover:not(:disabled) {
  background: #f8fafc;
  color: #0f172a;
  border-color: #cbd5e1;
}

.btn-submit {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.625rem 1.5rem;
  font-size: 0.875rem;
  font-weight: 600;
  color: #ffffff;
  border: none;
  border-radius: 0.75rem;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.btn-primary {
  background: linear-gradient(to bottom, #3b82f6, #2563eb);
  box-shadow: 0 1px 2px 0 rgba(59, 130, 246, 0.2);
}

.btn-primary:hover:not(:disabled) {
  background: linear-gradient(to bottom, #2563eb, #1d4ed8);
  transform: translateY(-1px);
  box-shadow: 0 4px 6px -1px rgba(59, 130, 246, 0.2);
}

.btn-submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none !important;
}

.spinner {
  width: 1rem;
  height: 1rem;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-radius: 50%;
  border-top-color: #ffffff;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
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
    font-size: 1.125rem;
  }
  .modal-content {
    padding: 1.5rem;
  }
}
</style>
