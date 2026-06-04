<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  status?: string | null
}>()

const { t, te } = useI18n()
const normalized = computed(() => String(props.status || 'UNKNOWN').toUpperCase())
const statusKey = computed(() =>
  `workspace_assets.task_detail.final_workflow.status.${normalized.value.toLowerCase().replace(/-/g, '_')}`,
)
const statusLabel = computed(() => te(statusKey.value) ? t(statusKey.value) : normalized.value)
</script>

<template>
  <span class="status-pill" :class="`is-${normalized.toLowerCase().replace(/_/g, '-')}`">
    {{ statusLabel }}
  </span>
</template>

<style scoped>
.status-pill {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 8px;
  border: 1px solid #d8dee8;
  border-radius: 6px;
  background: #f8fafc;
  color: #475569;
  font-size: 0.72rem;
  font-weight: 700;
}

.status-pill.is-complete,
.status-pill.is-verified,
.status-pill.is-accepted,
.status-pill.is-closed,
.status-pill.is-resolved,
.status-pill.is-baselined {
  border-color: #b7e4c7;
  background: #f0fdf4;
  color: #15803d;
}

.status-pill.is-active,
.status-pill.is-in-review,
.status-pill.is-open,
.status-pill.is-ready,
.status-pill.is-answered {
  border-color: #bfdbfe;
  background: #eff6ff;
  color: #1d4ed8;
}

.status-pill.is-blocked,
.status-pill.is-rejected,
.status-pill.is-need-clarification,
.status-pill.is-need-evidence,
.status-pill.is-block {
  border-color: #fecaca;
  background: #fef2f2;
  color: #b91c1c;
}

.status-pill.is-warning,
.status-pill.is-partial,
.status-pill.is-reopened {
  border-color: #fde68a;
  background: #fffbeb;
  color: #a16207;
}
</style>
