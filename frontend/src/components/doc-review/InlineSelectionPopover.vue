<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

type SelectionPayload = {
  block_id: string
  selected_text: string
  char_start?: number
  char_end?: number
  anchor: { top: number; left: number }
}

const props = defineProps<{
  selection: SelectionPayload | null
  canComment: boolean
}>()

const emit = defineEmits<{
  close: []
  create: [{
    block_id: string
    selected_text: string
    char_start?: number
    char_end?: number
    body: string
  }]
}>()

const { t } = useI18n()

const body = ref('')
const bodyInvalid = ref(false)
let invalidTimer: number | null = null

const clearInvalidTimer = () => {
  if (invalidTimer !== null) {
    window.clearTimeout(invalidTimer)
    invalidTimer = null
  }
}

const triggerEmptyBodyFeedback = () => {
  bodyInvalid.value = false
  window.requestAnimationFrame(() => {
    bodyInvalid.value = true
  })
  clearInvalidTimer()
  invalidTimer = window.setTimeout(() => {
    bodyInvalid.value = false
    invalidTimer = null
  }, 520)
}

watch(
  () => props.selection?.block_id,
  () => {
    body.value = ''
    bodyInvalid.value = false
  },
)

watch(
  () => body.value,
  (value) => {
    if (value.trim()) {
      bodyInvalid.value = false
      clearInvalidTimer()
    }
  },
)

const createThread = () => {
  if (!props.selection) return
  if (!props.canComment) return
  const normalizedBody = body.value.trim()
  if (!normalizedBody) {
    triggerEmptyBodyFeedback()
    return
  }
  emit('create', {
    block_id: props.selection.block_id,
    selected_text: props.selection.selected_text,
    char_start: props.selection.char_start,
    char_end: props.selection.char_end,
    body: normalizedBody,
  })
}

onBeforeUnmount(() => {
  clearInvalidTimer()
})
</script>

<template>
  <div
    v-if="selection"
    class="inline-popover glass-panel"
    :style="{
      top: `${selection.anchor.top + 8}px`,
      left: `${selection.anchor.left}px`,
    }"
  >
    <header class="popover-head">
      <strong>{{ t('doc_review.create_annotation_title') }}</strong>
      <button class="close-btn" @click="emit('close')">×</button>
    </header>
    <p class="selected-text">“{{ selection.selected_text }}”</p>
    <textarea
      v-model="body"
      class="composer"
      :class="{ 'composer-invalid': bodyInvalid }"
      :aria-invalid="bodyInvalid ? 'true' : 'false'"
      :disabled="!canComment"
      :placeholder="t('doc_review.create_annotation_placeholder')"
    />
    <div class="actions">
      <button class="btn-secondary" @click="emit('close')">{{ t('common.cancel') }}</button>
      <button class="btn-primary" :disabled="!canComment" @click="createThread">
        {{ t('doc_review.create_annotation_action') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.inline-popover {
  position: fixed;
  z-index: 45;
  width: min(420px, calc(100vw - 32px));
  padding: 1.25rem;
  border-radius: var(--radius-xl);
  box-shadow: 0 20px 25px -5px rgba(2, 132, 199, 0.15), 0 8px 10px -6px rgba(2, 132, 199, 0.1);
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.8);
}

.popover-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: var(--color-text-title);
  margin-bottom: 6px;
}

.close-btn {
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  font-size: 18px;
  line-height: 1;
}

.selected-text {
  margin: 0 0 1rem;
  font-size: 0.875rem;
  color: #0369a1;
  background: rgba(14, 165, 233, 0.08);
  padding: 0.75rem;
  border-radius: var(--radius-lg);
  border: 1px solid rgba(14, 165, 233, 0.15);
  line-height: 1.5;
}

.composer {
  width: 100%;
  min-height: 80px;
  border-radius: var(--radius-lg);
  border: 1px solid rgba(2, 132, 199, 0.2);
  resize: vertical;
  padding: 0.75rem;
  font: inherit;
  font-size: 0.875rem;
  background: rgba(248, 250, 252, 0.8);
  transition: all 0.2s;
}

.composer:focus {
  outline: none;
  border-color: rgba(2, 132, 199, 0.5);
  background: #ffffff;
}

.composer-invalid {
  border-color: rgba(220, 38, 38, 0.8);
  box-shadow: 0 0 0 2px rgba(248, 113, 113, 0.22);
  background: rgba(254, 242, 242, 0.96);
  animation: composerInvalidShake 0.42s ease;
}

@keyframes composerInvalidShake {
  0% {
    transform: translateX(0);
  }
  20% {
    transform: translateX(-3px);
  }
  40% {
    transform: translateX(3px);
  }
  60% {
    transform: translateX(-2px);
  }
  80% {
    transform: translateX(2px);
  }
  100% {
    transform: translateX(0);
  }
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
}
</style>
