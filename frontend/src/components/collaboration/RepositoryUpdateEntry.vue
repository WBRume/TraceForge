<script setup lang="ts">
import { computed, proxyRefs } from 'vue'
import { GitPullRequest, ChevronRight } from '@/components/icons'
import type { RepositoryUpdates } from '@/composables/collaboration/useRepositoryUpdates'

const props = defineProps<{ model: RepositoryUpdates }>()
const emit = defineEmits<{ open: [] }>()
const m = computed(() => proxyRefs(props.model))
const status = computed(() => {
  if (!m.value.plan || m.value.plan.state === 'APPLIED') return ''
  if (m.value.plan.storage_missing) return '需要恢复'
  if (m.value.conflicts) return `${m.value.conflicts} 个冲突`
  if (Object.keys(m.value.drafts).length) return '待确认编辑'
  return { PREPARING:'检查中', READY:m.value.plan.repositories.some(repo => repo.baseline !== repo.target) ? '待审查' : '',
    ADAPTING:'适配中', ADAPT_FAILED:'适配未完成', FAILED:'检查未完成', APPLYING:'需要恢复', RECOVERY_REQUIRED:'需要恢复', CONFLICTS:'待处理' }[m.value.plan.state]
})
</script>

<template>
  <button v-if="m.summary?.can_update !== false || m.plan" class="baseline-entry" :class="{ attention:status }" type="button" title="处理任务基线落后于远端分支的情况" @click="emit('open')">
    <GitPullRequest :size="14" /><span>更新任务基线</span><small v-if="status">{{ status }}</small><ChevronRight :size="13" />
  </button>
</template>

<style scoped>
.baseline-entry { display:inline-flex; align-items:center; gap:6px; padding:6px 9px; min-height:32px; border:1px solid #dbe5ef; border-radius:6px; background:#fff; color:#475569; font-size:12px; cursor:pointer; }
.baseline-entry:hover { color:#0284c7; background:#f0f9ff; border-color:#bae6fd; }
.baseline-entry:focus-visible { outline:2px solid #38bdf8; outline-offset:2px; }
.baseline-entry.attention { color:#b45309; border-color:#fde68a; background:#fffbeb; }
.baseline-entry small { font-size:10px; border-radius:4px; background:#fef3c7; padding:1px 5px; }
</style>
