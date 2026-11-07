<script setup lang="ts">
import { computed } from 'vue'
import { CheckCircle2, CircleHelp, Clock, Flag, Loader2, OctagonPause, Play, XCircle } from '@/components/icons'
import { normalizeTaskStatus } from '@/utils/taskStatus'

const props = withDefaults(defineProps<{
  status?: string | null
  size?: number
}>(), { size: 18 })

const status = computed(() => normalizeTaskStatus(props.status))
// 轮次完成用旗标表达“阶段性完成”，已完成用圆勾表达“终态”，
// 避免工具栏纯图标模式下两个对号难以区分。
const icons = {
  PROVISIONING: Clock,
  INITIALIZED: Play,
  RUNNING: Loader2,
  ROUND_COMPLETED: Flag,
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
    <component :is="icon" class="task-status-glyph" :size="props.size" stroke-width="1.8" />
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
.task-status-icon[data-status="PROVISIONING"] { color: #7c3aed; }
.task-status-icon[data-status="INITIALIZED"] { color: #64748b; }
.task-status-icon[data-status="RUNNING"] { color: #0284c7; }
.task-status-icon[data-status="ROUND_COMPLETED"] { color: #0d9488; }
.task-status-icon[data-status="AWAITING_INPUT"] { color: #d97706; }
.task-status-icon[data-status="INTERRUPTED"] { color: #ea580c; }
.task-status-icon[data-status="COMPLETED"] { color: #16a34a; }
.task-status-icon[data-status="FAILED"] { color: #dc2626; }
.task-status-icon[data-status="RUNNING"] .task-status-glyph {
  animation: task-status-spin 1s linear infinite;
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
