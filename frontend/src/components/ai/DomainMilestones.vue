<script setup lang="ts">
import { computed } from 'vue'
import { domainMilestones } from '@/utils/domainMilestones'

const props = defineProps<{ events?: unknown; active: boolean }>()
const current = computed(() => {
  if (!props.active) return null
  const events = domainMilestones(props.events)
  const latest = events[events.length - 1]
  return latest && latest.stage !== 'persisted' && latest.stage !== 'failed' ? latest : null
})
</script>

<template>
  <div v-if="current" class="domain-milestones" role="status" aria-label="执行进度" aria-live="polite">
    <div class="current-stage" :data-stage="current.stage">
      <span class="milestone-dot" aria-hidden="true" />
      <span>{{ current.message }}</span>
      <details v-if="current.issues.length">
        <summary>查看校验详情</summary>
        <p v-for="(issue, index) in current.issues" :key="index">{{ issue }}</p>
      </details>
    </div>
  </div>
</template>

<style scoped>
.domain-milestones { display: grid; gap: 7px; margin: 10px 0; padding: 0; list-style: none; color: #475569; font-size: 12px; }
.current-stage { display: flex; flex-wrap: wrap; align-items: baseline; gap: 7px; }
.milestone-dot { width: 6px; height: 6px; border-radius: 50%; background: #64748b; flex-shrink: 0; }
[data-stage="repairing"] .milestone-dot { background: #b45309; }
.domain-milestones details { flex-basis: 100%; margin-left: 13px; overflow-wrap: anywhere; }
.domain-milestones summary { cursor: pointer; }
.domain-milestones p { margin: 4px 0; }
</style>
