<script setup lang="ts">
import { computed } from 'vue'
import { domainMilestones } from '@/utils/domainMilestones'

const props = defineProps<{ events?: unknown }>()
const milestones = computed(() => domainMilestones(props.events))
</script>

<template>
  <ol v-if="milestones.length" class="domain-milestones" aria-label="执行进度" aria-live="polite">
    <li v-for="event in milestones" :key="`${event.run_id}:${event.sequence}`" :data-stage="event.stage">
      <span class="milestone-dot" aria-hidden="true" />
      <span>{{ event.message }}</span>
      <details v-if="event.issues.length">
        <summary>查看校验详情</summary>
        <p v-for="(issue, index) in event.issues" :key="index">{{ issue }}</p>
      </details>
    </li>
  </ol>
</template>

<style scoped>
.domain-milestones { display: grid; gap: 7px; margin: 10px 0; padding: 0; list-style: none; color: #475569; font-size: 12px; }
.domain-milestones li { display: flex; flex-wrap: wrap; align-items: baseline; gap: 7px; }
.milestone-dot { width: 6px; height: 6px; border-radius: 50%; background: #64748b; flex-shrink: 0; }
[data-stage="repairing"] .milestone-dot { background: #b45309; }
[data-stage="persisted"] .milestone-dot { background: #15803d; }
[data-stage="failed"] .milestone-dot { background: #b91c1c; }
.domain-milestones details { flex-basis: 100%; margin-left: 13px; overflow-wrap: anywhere; }
.domain-milestones summary { cursor: pointer; }
.domain-milestones p { margin: 4px 0; }
</style>
