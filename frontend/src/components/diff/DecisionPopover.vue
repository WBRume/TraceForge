<script setup lang="ts">
import { reactive, watch, ref, nextTick, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { X } from 'lucide-vue-next'
import type { DeltaLineRef, DecisionMutationPayload } from '@/types/workspaceAssets'

const props = defineProps<{
  visible: boolean
  filePath: string
  lineStart: number
  lineEnd: number
  selectedText?: string
  deltaId: string
  anchorTop?: number
  anchorLeft?: number
}>()

const emit = defineEmits<{
  submit: [payload: DecisionMutationPayload]
  close: []
}>()

const { t } = useI18n()

const form = reactive({
  title: '',
  body: '',
  status: 'PROPOSED',
})

const touched = reactive({ title: false })
const inputRef = ref<HTMLInputElement | null>(null)

watch(() => props.visible, (v) => {
  if (v) {
    touched.title = false
    form.body = ''
    form.status = 'PROPOSED'
    const file = props.filePath.split('/').pop() || props.filePath
    if (props.lineStart === props.lineEnd) {
      form.title = `Decision on ${file}#L${props.lineStart}`
    } else {
      form.title = `Decision on ${file}#L${props.lineStart}-L${props.lineEnd}`
    }
    nextTick(() => inputRef.value?.focus())
  }
})

function handleSubmit() {
  touched.title = true
  if (!form.title.trim()) return
  const refs: DeltaLineRef[] = [{
    file_path: props.filePath,
    line_start: props.lineStart,
    line_end: props.lineEnd,
  }]
  emit('submit', {
    title: form.title.trim(),
    body: form.body.trim() || null,
    status: form.status,
    human_delta_id: props.deltaId,
    delta_line_refs: refs,
    source_type: 'TASK_DETAIL_BACKFILL',
  })
}

const fileBase = computed(() => props.filePath.split('/').pop() || props.filePath)
</script>

<template>
  <Transition name="pop">
    <div
      v-if="visible"
      class="decision-popover glass-panel"
      :style="{ top: anchorTop + 'px', left: anchorLeft + 'px' }"
      @mousedown.stop
      @click.stop
      @pointerdown.stop
    >
      <div class="popover-head">
        <span class="popover-file">{{ fileBase }}</span>
        <span class="popover-lines">L{{ lineStart }}<template v-if="lineStart !== lineEnd"> - L{{ lineEnd }}</template></span>
        <button class="popover-close" @click="emit('close')">
          <X :size="14" />
        </button>
      </div>

      <p v-if="selectedText" class="popover-selected-text">"{{ selectedText.slice(0, 200) }}"</p>

      <div class="popover-form">
        <input
          ref="inputRef"
          v-model="form.title"
          class="popover-input"
          :class="{ 'is-invalid': touched.title && !form.title.trim() }"
          :placeholder="t('workspace_assets.task_detail.workbench.fields.title')"
          @blur="touched.title = true"
          @keydown.enter.prevent="handleSubmit"
        />
        <textarea
          v-model="form.body"
          class="popover-textarea"
          :placeholder="t('workspace_assets.task_detail.workbench.fields.decision_body')"
          rows="2"
        />
        <select v-model="form.status" class="popover-select">
          <option value="PROPOSED">{{ t('workspace_assets.task_detail.workbench.status.proposed') }}</option>
          <option value="ACCEPTED">{{ t('workspace_assets.task_detail.workbench.status.accepted') }}</option>
          <option value="REJECTED">{{ t('workspace_assets.task_detail.workbench.status.rejected') }}</option>
        </select>
      </div>

      <div class="popover-actions">
        <button class="btn-cancel" @click="emit('close')">{{ t('common.cancel') }}</button>
        <button class="btn-submit" :disabled="!form.title.trim()" @click="handleSubmit">
          {{ t('workspace_assets.task_detail.workbench.decisions.submit') }}
        </button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.decision-popover {
  position: absolute;
  z-index: 1000;
  width: 340px;
  padding: 14px;
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.96);
  border: 1px solid rgba(56, 189, 248, 0.25);
  backdrop-filter: blur(16px);
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  gap: 10px;
  color: #e2e8f0;
  font-size: 13px;
}

.popover-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.popover-file {
  font-family: monospace;
  font-size: 12px;
  font-weight: 600;
  color: #7dd3fc;
}

.popover-lines {
  font-family: monospace;
  font-size: 11px;
  color: #94a3b8;
  margin-left: auto;
}

.popover-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  border-radius: 4px;
}

.popover-close:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #e2e8f0;
}

.popover-selected-text {
  margin: 0;
  padding: 6px 8px;
  font-family: monospace;
  font-size: 11px;
  color: #94a3b8;
  background: rgba(255, 255, 255, 0.04);
  border-radius: 4px;
  border-left: 2px solid #3b82f6;
  max-height: 64px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.popover-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.popover-input,
.popover-textarea,
.popover-select {
  width: 100%;
  padding: 6px 8px;
  font-size: 13px;
  color: #e2e8f0;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 6px;
  outline: none;
  font-family: inherit;
}

.popover-input:focus,
.popover-textarea:focus,
.popover-select:focus {
  border-color: #3b82f6;
  background: rgba(255, 255, 255, 0.08);
}

.popover-input.is-invalid {
  border-color: #dc2626;
}

.popover-textarea {
  resize: vertical;
  min-height: 48px;
}

.popover-select {
  cursor: pointer;
}

.popover-select option {
  background: #1e293b;
  color: #e2e8f0;
}

.popover-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}

.btn-cancel,
.btn-submit {
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 500;
  border-radius: 6px;
  border: none;
  cursor: pointer;
}

.btn-cancel {
  background: transparent;
  color: #94a3b8;
  border: 1px solid rgba(255, 255, 255, 0.12);
}

.btn-cancel:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #e2e8f0;
}

.btn-submit {
  background: #3b82f6;
  color: #fff;
}

.btn-submit:hover {
  background: #2563eb;
}

.btn-submit:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.pop-enter-active,
.pop-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.pop-enter-from,
.pop-leave-to {
  opacity: 0;
  transform: translateY(6px);
}
</style>
