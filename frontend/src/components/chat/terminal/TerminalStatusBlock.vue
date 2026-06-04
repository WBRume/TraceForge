<script setup lang="ts">
import { computed, ref } from 'vue'

import type { TerminalTimelineEntry } from '@/utils/chat-terminal/timeline-types'

type StatusBlockEntry = Extract<TerminalTimelineEntry, { kind: 'status' | 'hitl' | 'result' }>

const props = defineProps<{
  entry: StatusBlockEntry
  formatTime: (value: string) => string
  t: (key: string, values?: Record<string, unknown>) => string
}>()

const emit = defineEmits<{
  (e: 'hitl-submit', cardId: string, response: string): void
}>()

const textAnswer = ref('')

const isHitlBoolean = computed(() => {
  if (props.entry.kind !== 'hitl') return false
  return props.entry.hitlType === 'boolean'
})

const submitTextAnswer = () => {
  if (props.entry.kind !== 'hitl') return
  const normalized = textAnswer.value.trim()
  if (!normalized) return
  emit('hitl-submit', props.entry.cardId, normalized)
  textAnswer.value = ''
}
</script>

<template>
  <div class="status-block" :class="`kind-${props.entry.kind}`">
    <template v-if="props.entry.kind === 'status'">
      <div class="status-head">
        <span class="status-tag">{{ props.entry.status || 'STATUS' }}</span>
        <span class="status-time">{{ props.formatTime(props.entry.createdAt) }}</span>
      </div>
      <p class="status-body">{{ props.entry.message }}</p>
      <p v-if="props.entry.model" class="status-meta">{{ props.entry.model }}</p>
    </template>

    <template v-else-if="props.entry.kind === 'result'">
      <div class="status-head">
        <span class="status-tag">{{ props.entry.success ? 'SUCCESS' : 'FAILED' }}</span>
        <span class="status-time">{{ props.formatTime(props.entry.createdAt) }}</span>
      </div>
      <p class="status-meta">
        {{ props.t('chat.cli_result_duration') }}: {{ (props.entry.durationMs / 1000).toFixed(1) }}s
        · {{ props.t('chat.cli_result_cost') }}: ${{ props.entry.costUsd.toFixed(4) }}
      </p>
      <pre v-if="props.entry.result" class="status-output">{{ props.entry.result }}</pre>
    </template>

    <template v-else>
      <div class="status-head">
        <span class="status-tag">HITL</span>
        <span class="status-time">{{ props.formatTime(props.entry.createdAt) }}</span>
      </div>
      <p class="status-body">{{ props.entry.prompt }}</p>
      <p v-if="props.entry.context" class="status-meta">{{ props.entry.context }}</p>
      <div v-if="!props.entry.answered" class="hitl-actions">
        <template v-if="isHitlBoolean">
          <button class="hitl-btn yes" @click="emit('hitl-submit', props.entry.cardId, 'y')">Y</button>
          <button class="hitl-btn no" @click="emit('hitl-submit', props.entry.cardId, 'n')">N</button>
        </template>
        <template v-else>
          <input
            v-model="textAnswer"
            type="text"
            class="hitl-input"
            @keyup.enter="submitTextAnswer"
          >
          <button class="hitl-btn yes" @click="submitTextAnswer">{{ props.t('common.confirm') }}</button>
        </template>
      </div>
      <p v-else class="status-meta">{{ props.t('chat.hitl_answer_submitted') }}</p>
    </template>
  </div>
</template>

<style scoped>
.status-block {
  border: 1px solid #2a3a53;
  border-radius: 10px;
  padding: 10px;
  background: #101a2a;
  color: #d4deea;
}

.status-block.kind-result {
  border-color: #255f4f;
}

.status-block.kind-hitl {
  border-color: #69561a;
}

.status-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
  font-size: 12px;
}

.status-tag {
  font-weight: 600;
  letter-spacing: 0.02em;
}

.status-time {
  color: #8ba0bc;
}

.status-body {
  font-size: 13px;
  margin: 0;
  white-space: pre-wrap;
}

.status-meta {
  margin: 6px 0 0;
  color: #8ba0bc;
  font-size: 12px;
  white-space: pre-wrap;
}

.status-output {
  margin-top: 8px;
  background: #09101d;
  border: 1px solid #243044;
  border-radius: 8px;
  padding: 8px;
  white-space: pre-wrap;
  overflow-x: auto;
  font-size: 12px;
}

.hitl-actions {
  margin-top: 8px;
  display: flex;
  gap: 8px;
}

.hitl-input {
  flex: 1;
  border: 1px solid #2a3a53;
  background: #09101d;
  color: #d4deea;
  border-radius: 8px;
  padding: 6px 8px;
}

.hitl-btn {
  border: 1px solid #2a3a53;
  background: #111b2c;
  color: #d4deea;
  border-radius: 8px;
  padding: 6px 12px;
  cursor: pointer;
}

.hitl-btn.yes {
  border-color: #255f4f;
}

.hitl-btn.no {
  border-color: #6d3046;
}
</style>

