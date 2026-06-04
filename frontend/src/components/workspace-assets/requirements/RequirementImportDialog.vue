<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Sparkles, X } from 'lucide-vue-next'
import RequirementCreateMethodStep from './RequirementCreateMethodStep.vue'
import RequirementImportContentStep from './RequirementImportContentStep.vue'
import RequirementManualCreateStep from './RequirementManualCreateStep.vue'
import RequirementPreviewEditor from './RequirementPreviewEditor.vue'
import RequirementPreviewProgress from './RequirementPreviewProgress.vue'
import RequirementSourceLinkStep from './RequirementSourceLinkStep.vue'
import type { RequirementImportBatch, RequirementPreviewJob } from '@/types/workspaceAssets'
import type {
  RequirementCreateStep,
  RequirementDirectImportPayload,
  RequirementManualPayload,
  RequirementPreviewConfirmPayload,
  RequirementPreviewPayload,
  RequirementReturnStep,
} from './requirementCreateTypes'

type DialogMode = 'create' | 'split'

const props = defineProps<{
  open: boolean
  batch: RequirementImportBatch | null
  previewJob?: RequirementPreviewJob | null
  mode?: DialogMode
  loading?: boolean
}>()

const emit = defineEmits<{
  close: []
  manual: [payload: RequirementManualPayload]
  direct: [payload: RequirementDirectImportPayload]
  preview: [payload: RequirementPreviewPayload]
  confirm: [payload: RequirementPreviewConfirmPayload]
  discardPreview: []
  clearPreviewJob: []
}>()

const { t } = useI18n()
const step = shallowRef<RequirementCreateStep>('method')
const returnStep = shallowRef<RequirementReturnStep>('file')
const resetKey = shallowRef(0)
const confirmReason = shallowRef('')

const isSplit = computed(() => props.mode === 'split')
const dialogTitle = computed(() => (
  isSplit.value
    ? t('workspace_assets.requirements.create.split_title')
    : t('workspace_assets.requirements.create.title')
))
const dialogEyebrow = computed(() => (
  isSplit.value
    ? t('workspace_assets.requirements.create.split_eyebrow')
    : t('workspace_assets.requirements.create.eyebrow')
))
const stepLabel = computed(() => {
  if (isSplit.value) return t('workspace_assets.requirements.create.step_preview')
  return t(`workspace_assets.requirements.create.steps.${step.value}`)
})
const showingPreviewProgress = computed(() => Boolean(props.previewJob && !props.batch))

watch(
  () => props.open,
  (open) => {
    if (!open) return
    step.value = isSplit.value || props.batch ? 'preview' : 'method'
    returnStep.value = 'file'
    confirmReason.value = ''
    resetKey.value += 1
  },
  { immediate: true },
)

watch(
  () => props.batch,
  (batch) => {
    if (batch) step.value = 'preview'
  },
  { immediate: true },
)

function selectStep(nextStep: Exclude<RequirementCreateStep, 'method' | 'preview'>) {
  step.value = nextStep
  if (nextStep === 'manual' || nextStep === 'file') returnStep.value = nextStep
}

function backToMethods() {
  step.value = 'method'
}

function createPreview(payload: RequirementPreviewPayload) {
  if (step.value === 'manual' || step.value === 'file') returnStep.value = step.value
  emit('preview', payload)
}

function discardPreview() {
  confirmReason.value = ''
  emit('discardPreview')
  step.value = returnStep.value
}

function clearPreviewProgress() {
  emit('clearPreviewJob')
  if (!isSplit.value) step.value = returnStep.value
}

function close() {
  emit('close')
}
</script>

<template>
  <Teleport to="body">
    <div v-if="props.open" class="modal-overlay" @click.self="close">
      <section class="modal glass-panel requirement-dialog" :aria-label="t('workspace_assets.requirements.create.aria_label')">
        <header class="modal-header">
          <div class="header-icon">
            <Sparkles :size="24" class="text-primary" />
          </div>
          <div class="header-text">
            <span class="eyebrow">{{ dialogEyebrow }}</span>
            <h2>{{ dialogTitle }}</h2>
            <p class="step-label">{{ stepLabel }}</p>
          </div>
          <button type="button" class="close-btn" @click="close" :title="t('workspace_assets.requirements.actions.close')">
            <X :size="20" />
          </button>
        </header>

        <div class="modal-content">
          <RequirementPreviewProgress
            v-if="showingPreviewProgress && props.previewJob"
            :job="props.previewJob"
            :split="isSplit"
            @back="clearPreviewProgress"
            @cancel="close"
          />

          <RequirementPreviewEditor
            v-else-if="isSplit || step === 'preview'"
            v-model:change-reason="confirmReason"
            :batch="props.batch"
            :loading="props.loading"
            :split="isSplit"
            @confirm="emit('confirm', $event)"
            @discard="discardPreview"
            @back="step = returnStep"
            @cancel="close"
          />

          <template v-else>
            <RequirementCreateMethodStep
              v-if="step === 'method'"
              @select="selectStep"
            />
            <RequirementManualCreateStep
              v-else-if="step === 'manual'"
              :loading="props.loading"
              :reset-key="resetKey"
              @submit="emit('manual', $event)"
              @preview="createPreview"
              @back="backToMethods"
              @cancel="close"
            />
            <RequirementImportContentStep
              v-else-if="step === 'file'"
              :loading="props.loading"
              :reset-key="resetKey"
              @direct="emit('direct', $event)"
              @preview="createPreview"
              @back="backToMethods"
              @cancel="close"
            />
            <RequirementSourceLinkStep
              v-else-if="step === 'source_link'"
              :loading="props.loading"
              :reset-key="resetKey"
              @submit="emit('manual', $event)"
              @back="backToMethods"
              @cancel="close"
            />
          </template>
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
  background: white;
  border-radius: 1.5rem;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: scale-up 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes scale-up {
  from { opacity: 0; transform: scale(0.95) translateY(10px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

.modal-header {
  display: flex;
  align-items: flex-start;
  gap: 1.25rem;
  padding: 2rem;
  border-bottom: 1px solid #f1f5f9;
  position: relative;
}

.header-icon {
  width: 3rem;
  height: 3rem;
  background: #f0f9ff;
  border-radius: 1rem;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.header-text {
  flex: 1;
}

.eyebrow {
  color: #0ea5e9;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  display: block;
  margin-bottom: 0.25rem;
}

.modal-header h2 {
  font-family: 'Poppins', sans-serif;
  font-size: 1.5rem;
  font-weight: 700;
  margin: 0;
  color: #0f172a;
}

.step-label {
  margin: 0.25rem 0 0;
  color: #64748b;
  font-size: 0.9375rem;
}

.close-btn {
  width: 2.5rem;
  height: 2.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 0.75rem;
  border: none;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.2s;
}

.close-btn:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.modal-content {
  flex: 1;
  overflow-y: auto;
  padding: 2rem;
}

.text-primary {
  color: #0ea5e9;
}

@media (max-width: 640px) {
  .modal-header {
    padding: 1.5rem;
    gap: 1rem;
  }
  .header-icon {
    width: 2.5rem;
    height: 2.5rem;
  }
  .modal-content {
    padding: 1.5rem;
  }
}
</style>
