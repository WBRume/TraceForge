<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{ status: string }>()
const { t } = useI18n()

const label = computed(() => t(`case_center.status.${props.status}`))
const cls = computed(() => `case-status-${String(props.status).toLowerCase()}`)
</script>

<template>
  <span class="case-status-pill" :class="cls">{{ label }}</span>
</template>

<style scoped>
.case-status-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 600;
  line-height: 1.5;
  white-space: nowrap;
}

.case-status-draft { color: #475569; background: #f1f5f9; border: 1px solid #e2e8f0; }
.case-status-pending_review { color: #1d4ed8; background: #eff6ff; border: 1px solid #bfdbfe; }
.case-status-in_review { color: #b45309; background: #fffbeb; border: 1px solid #fde68a; }
.case-status-approved { color: #14532d; background: #f0fdf4; border: 1px solid #bbf7d0; }
.case-status-rejected { color: #b91c1c; background: #fef2f2; border: 1px solid #fecaca; }
</style>
