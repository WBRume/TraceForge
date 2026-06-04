<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ChatDecisionPayload } from '@/composables/useChatDecision'

const props = defineProps<{
  show: boolean
  message: Record<string, any> | null
  saving?: boolean
}>()

const emit = defineEmits<{
  close: []
  submit: [payload: ChatDecisionPayload]
}>()

const { t } = useI18n()

const form = reactive({
  title: '',
  body: '',
  impact_scope: '',
  promote_candidate: false,
})
const touched = reactive({ title: false })

const titleInvalid = computed(() => touched.title && !form.title.trim())

function resetForm() {
  const content = String(props.message?.content || '').trim()
  const firstLine = content.split(/\r?\n/).map(line => line.trim()).find(Boolean) || ''
  form.title = firstLine.slice(0, 80)
  form.body = content
  form.impact_scope = ''
  form.promote_candidate = false
  touched.title = false
}

function closePopover() {
  if (props.saving) return
  emit('close')
}

function submit() {
  touched.title = true
  if (!form.title.trim()) return
  emit('submit', {
    title: form.title.trim(),
    body: form.body.trim() || null,
    impact_scope: form.impact_scope.trim() || null,
    promote_candidate: form.promote_candidate,
  })
}

watch(
  () => [props.show, props.message?.id],
  () => {
    if (props.show) resetForm()
  },
  { immediate: true },
)
</script>

<template>
  <div v-if="show" class="decision-popover-container">
    <!-- Invisible overlay to catch clicks outside -->
    <div class="popover-backdrop" @click="closePopover"></div>
    
    <div class="decision-popover glass-panel">
      <!-- Caret pointing to the button -->
      <div class="popover-caret"></div>
      
      <form class="decision-form" @submit.prevent="submit">
        <label class="field">
          <span>{{ t('chat.decision.title') }} <b>*</b></span>
          <input
            v-model="form.title"
            :class="{ 'is-invalid': titleInvalid }"
            @blur="touched.title = true"
            :placeholder="t('chat.decision.title')"
            autofocus
          />
        </label>

        <label class="field">
          <span>{{ t('chat.decision.body') }}</span>
          <textarea v-model="form.body" rows="3" :placeholder="t('chat.decision.body')" />
        </label>

        <label class="field">
          <span>{{ t('chat.decision.impact_scope') }}</span>
          <input v-model="form.impact_scope" :placeholder="t('chat.decision.impact_scope')" />
        </label>

        <label class="check-row">
          <input v-model="form.promote_candidate" type="checkbox" />
          <span>{{ t('chat.decision.promote_candidate') }}</span>
        </label>

        <footer class="popover-actions">
          <button type="button" class="btn-secondary btn-sm" :disabled="saving" @click="closePopover">
            {{ t('common.cancel') }}
          </button>
          <button type="submit" class="btn-primary btn-sm" :disabled="saving">
            {{ saving ? t('common.saving') : t('chat.decision.save') }}
          </button>
        </footer>
      </form>
    </div>
  </div>
</template>

<style scoped>
.decision-popover-container {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 50;
}

.popover-backdrop {
  position: fixed;
  inset: 0;
  z-index: -1;
  background: transparent;
  cursor: default;
}

.decision-popover {
  position: relative;
  width: 320px;
  padding: 16px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
  border: 1px solid rgba(226, 232, 240, 0.8);
  animation: popover-fade-in 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  transform-origin: top right;
}

.popover-caret {
  position: absolute;
  top: -6px;
  right: 12px;
  width: 12px;
  height: 12px;
  background: rgba(255, 255, 255, 0.96);
  border-top: 1px solid rgba(226, 232, 240, 0.8);
  border-left: 1px solid rgba(226, 232, 240, 0.8);
  transform: rotate(45deg);
  z-index: 1;
}

@keyframes popover-fade-in {
  from { opacity: 0; transform: scale(0.95) translateY(-4px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

.decision-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
  position: relative;
  z-index: 2;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: #475569;
  font-size: 0.8rem;
  font-weight: 600;
}

.field b {
  color: #ef4444;
}

.field input,
.field textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #f8fafc;
  padding: 6px 10px;
  color: #0f172a;
  font-family: inherit;
  font-size: 0.85rem;
  transition: all 0.2s;
}

.field textarea {
  resize: vertical;
}

.field input:focus,
.field textarea:focus {
  outline: none;
  background: #ffffff;
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15);
}

.field .is-invalid {
  border-color: #ef4444;
  box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.15);
}

.check-row {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #475569;
  font-size: 0.8rem;
  cursor: pointer;
  margin-top: 4px;
}

.check-row input[type="checkbox"] {
  width: 14px;
  height: 14px;
  border-radius: 4px;
  cursor: pointer;
}

.popover-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 6px;
}

.btn-sm {
  padding: 4px 12px;
  font-size: 0.8rem;
  height: 28px;
  border-radius: 6px;
}
</style>
