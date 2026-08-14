<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ProjectLifecycleStatus } from '@/types/management'

const props = defineProps<{
  status: ProjectLifecycleStatus
}>()

const { t } = useI18n()

const toneMap: Record<ProjectLifecycleStatus, string> = {
  INITIATED: 'blue',
  DEVELOPING: 'amber',
  DELIVERING: 'green',
  MAINTAINING: 'gray',
  RETIRED: 'red',
}

const tone = computed(() => toneMap[props.status] ?? 'gray')
const label = computed(() => t('management.project.lifecycle_' + props.status.toLowerCase()))
</script>

<template>
  <span class="mgmt-status-pill" :class="tone">{{ label }}</span>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
