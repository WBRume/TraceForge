<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ priority: string }>()
const cls = computed(() => `case-prio-${String(props.priority || 'p2').toLowerCase()}`)
</script>

<template>
  <span class="case-prio-tag" :class="cls">{{ priority }}</span>
</template>

<style scoped>
.case-prio-tag {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 700;
  line-height: 1.5;
  white-space: nowrap;
}

.case-prio-p0 { color: #b91c1c; background: #fef2f2; border: 1px solid #fecaca; }
.case-prio-p1 { color: #c2410c; background: #fff7ed; border: 1px solid #fed7aa; }
.case-prio-p2 { color: #1d4ed8; background: #eff6ff; border: 1px solid #bfdbfe; }
.case-prio-p3 { color: #475569; background: #f8fafc; border: 1px solid #e2e8f0; }
</style>
