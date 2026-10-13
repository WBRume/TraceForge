<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const props = defineProps<{ activity: { direction: string; done: number; total: number; bytes: number; totalBytes: number } }>()
const { t } = useI18n()
const size = (bytes: number) => bytes < 1048576 ? `${(bytes / 1024).toFixed(1)} KiB` : `${(bytes / 1048576).toFixed(1)} MiB`
</script>
<template>
  <div v-if="props.activity.total" class="transfer-status-wrap">
    <span class="transfer-status" role="status">
      {{ t(`collaboration.${props.activity.direction}`) }} · {{ props.activity.done }}/{{ props.activity.total }} {{ t('collaboration.files') }} · {{ size(props.activity.bytes) }}/{{ size(props.activity.totalBytes) }}
    </span>
    <div class="transfer-track">
      <div class="transfer-bar" :style="{ width: `${Math.min(100, Math.round((props.activity.bytes / (props.activity.totalBytes || 1)) * 100))}%` }"></div>
    </div>
  </div>
</template>
<style scoped>
.transfer-status-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 6px;
}
.transfer-status {
  font-size: 11px;
  color: var(--color-text-muted, #64748b);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.transfer-track {
  width: 100%;
  max-width: 280px;
  height: 4px;
  border-radius: 2px;
  background: rgba(14, 165, 233, 0.15);
  overflow: hidden;
}
.transfer-bar {
  height: 100%;
  border-radius: 2px;
  background: linear-gradient(90deg, #0ea5e9, #38bdf8);
  transition: width 0.2s ease;
}
</style>
