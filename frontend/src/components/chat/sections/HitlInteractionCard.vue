<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertCircle } from 'lucide-vue-next'
import { hitlOptionValue, hitlOptionLabel } from '@/composables/chat/cards/presenters'
import type { HitlCard } from '@/composables/chat/types'

/**
 * HITL（Human-in-the-loop）交互卡：boolean / select / 文本输入三种应答形态。
 * 输入草稿由卡片本地持有（卡对象生命周期即待应答期），提交时上报视图模型。
 */
const props = defineProps<{
  card: HitlCard
}>()

const emit = defineEmits<{
  (event: 'submit', cardId: string, value: string): void
}>()

const { t } = useI18n()
const inputValue = ref(props.card.tempInput || '')

watch(() => props.card.id, () => {
  inputValue.value = props.card.tempInput || ''
})

const submit = (value: string) => {
  emit('submit', props.card.id, value)
}
</script>

<template>
  <div class="pinned-card hitl-card">
    <div class="card-header hitl-header">
      <AlertCircle class="w-5 h-5 text-amber" />
      <h4>{{ t('chat.interrupt_confirm') }}</h4>
    </div>
    <div class="card-body">
      <p class="hitl-prompt">{{ props.card.prompt }}</p>
      <div v-if="props.card.context" class="context-box">
        <code>{{ props.card.context }}</code>
      </div>
    </div>
    <div class="hitl-actions">
      <template v-if="props.card.hitl_type === 'boolean'">
        <button class="btn-success" @click="submit('y')">{{ t('common.confirm') }} (Y)</button>
        <button class="btn-danger" @click="submit('n')">{{ t('common.cancel') }} (N)</button>
      </template>
      <template v-else-if="props.card.hitl_type === 'select' && props.card.options?.length">
        <button
          v-for="(option, index) in props.card.options"
          :key="`${props.card.id}-option-${index}`"
          class="btn-primary"
          @click="submit(hitlOptionValue(option))"
        >
          {{ hitlOptionLabel(option) }}
        </button>
      </template>
      <template v-else>
        <input
          type="text"
          v-model="inputValue"
          placeholder="..."
          class="input-field hitl-input"
          @keyup.enter="submit(inputValue)"
        >
        <button class="btn-primary" @click="submit(inputValue)">{{ t('common.confirm') }}</button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.hitl-card {
  background: white;
  border: 1px solid #FCD34D;
  border-left: 4px solid #F59E0B;
}
.hitl-header h4 { margin: 0; font-size: 0.95rem; color: #92400E; }
.hitl-prompt { font-weight: 500; margin: 8px 0; font-size: 0.9rem; }
.context-box {
  background: #F1F5F9;
  padding: 8px;
  border-radius: 4px;
  font-size: 0.85rem;
  margin-bottom: 8px;
}
.hitl-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.hitl-input {
  flex: 1;
  font-size: 0.875rem;
  padding: 6px 12px;
}
.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--color-text-body);
}
.card-body { margin-top: 4px; }

.btn-success {
  background: #10B981;
  color: white;
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;
}

.btn-danger {
  background: #EF4444;
  color: white;
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;
}
</style>
