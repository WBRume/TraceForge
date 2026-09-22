<script setup lang="ts">
import { shallowRef } from 'vue'
import type { PlaybookHypothesis } from '@/types/diagnosisPlaybook'
defineProps<{ hypothesis: PlaybookHypothesis; disabled: boolean }>()
const emit = defineEmits<{ decide: [action: string, id: string, reason: string] }>()
const reason = shallowRef('')
</script>
<template>
  <article class="hypothesis">
    <strong>{{ hypothesis.id }} · {{ hypothesis.claim }}</strong><small>{{ hypothesis.state }}</small>
    <p>预测：{{ hypothesis.predictions.join('；') }}</p>
    <p>反证：{{ hypothesis.falsifiers.join('；') }}</p>
    <p v-if="hypothesis.reason">{{ hypothesis.reason }}</p>
    <input v-model="reason" aria-label="假说决策理由" placeholder="说明排除或恢复理由" />
    <button :disabled="disabled || !reason.trim()" @click="emit('decide', hypothesis.state === 'EXCLUDED' ? 'restore' : 'exclude', hypothesis.id, reason)">{{ hypothesis.state === 'EXCLUDED' ? '恢复假说' : '排除假说' }}</button>
  </article>
</template>
<style scoped>
.hypothesis { padding:10px 0; border-bottom:1px solid var(--border-color,#ddd); overflow-wrap:anywhere }.hypothesis small { margin-left:12px }.hypothesis p { margin:6px 0 }.hypothesis input { max-width:100%; padding:4px }
</style>
