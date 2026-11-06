<script setup lang="ts">
import { computed } from 'vue'
import { Check, CheckCircle2, CircleHelp, Clock, Loader2, OctagonPause, Play, XCircle } from '@/components/icons'
import { normalizeTaskStatus } from '@/utils/taskStatus'

const props = withDefaults(defineProps<{
  status?: string | null
  size?: number
}>(), { size: 18 })

const status = computed(() => normalizeTaskStatus(props.status))
const icons = {
  PROVISIONING: Clock,
  INITIALIZED: Play,
  RUNNING: Loader2,
  ROUND_COMPLETED: Check,
  AWAITING_INPUT: CircleHelp,
  INTERRUPTED: OctagonPause,
  COMPLETED: CheckCircle2,
  FAILED: XCircle,
}
const icon = computed(() => icons[status.value as keyof typeof icons] || CircleHelp)
</script>

<template>
  <span class="task-status-icon" :data-status="status" aria-hidden="true"
    :style="{ width: `${props.size}px`, height: `${props.size}px` }">
    <component :is="icon" class="task-status-glyph" :size="props.size" />
  </span>
</template>

<style scoped>
.task-status-icon {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  color: #64748b;
  vertical-align: middle;
}
.task-status-glyph {
  display: block;
  transform-origin: center;
}
.task-status-icon[data-status="INITIALIZED"] { color: #475569; }
.task-status-icon[data-status="RUNNING"] { color: #1d4ed8; }
.task-status-icon[data-status="ROUND_COMPLETED"],
.task-status-icon[data-status="COMPLETED"] { color: #166534; }
.task-status-icon[data-status="AWAITING_INPUT"] { color: #9a3412; }
.task-status-icon[data-status="INTERRUPTED"] { color: #854d0e; }
.task-status-icon[data-status="FAILED"] { color: #991b1b; }
.task-status-icon[data-status="RUNNING"] .task-status-glyph {
  animation: task-status-spin 1.2s linear infinite;
}
.task-status-icon[data-status="AWAITING_INPUT"] .task-status-glyph {
  animation: task-status-breathe 1.8s ease-in-out infinite;
}
.task-status-icon[data-status="AWAITING_INPUT"]::after {
  content: '';
  position: absolute;
  inset: -2px;
  border: 1px solid currentColor;
  border-radius: 50%;
  pointer-events: none;
  animation: task-status-attention 1.8s ease-out infinite;
}
@keyframes task-status-spin { to { transform: rotate(360deg); } }
@keyframes task-status-breathe {
  0%, 100% { opacity: 0.65; transform: scale(0.92); }
  50% { opacity: 1; transform: scale(1); }
}
@keyframes task-status-attention {
  0% { opacity: 0.35; transform: scale(0.85); }
  80%, 100% { opacity: 0; transform: scale(1.35); }
}
@media (prefers-reduced-motion: reduce) {
  .task-status-glyph,
  .task-status-icon[data-status="AWAITING_INPUT"]::after { animation: none !important; }
  .task-status-icon[data-status="AWAITING_INPUT"]::after { opacity: 0; }
}
</style>
