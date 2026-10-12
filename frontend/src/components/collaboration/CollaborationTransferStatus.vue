<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const props = defineProps<{ activity: { direction: string; done: number; total: number; bytes: number; totalBytes: number } }>()
const { t } = useI18n()
const size = (bytes: number) => bytes < 1048576 ? `${(bytes / 1024).toFixed(1)} KiB` : `${(bytes / 1048576).toFixed(1)} MiB`
</script>
<template><span v-if="props.activity.total" class="transfer-status" role="status">{{ t(`collaboration.${props.activity.direction}`) }} · {{ props.activity.done }}/{{ props.activity.total }} {{ t('collaboration.files') }} · {{ size(props.activity.bytes) }}/{{ size(props.activity.totalBytes) }}</span></template>
<style scoped>.transfer-status { font-size: 11px; color: var(--color-text-muted); font-variant-numeric: tabular-nums; white-space: nowrap; }</style>
