<script setup lang="ts">
import { onMounted } from 'vue'
import { useWorkspaceStore } from '@/stores/workspace'
import WorkspaceQueueTab from '@/components/workspace/WorkspaceQueueTab.vue'

const wsStore = useWorkspaceStore()

onMounted(async () => {
  await wsStore.fetchWorkspaces()
})
</script>

<template>
  <div class="queue-list-page">
    <div class="mgmt-page-header">
      <div>
        <h2>{{ $t('queue_ops.title') }}</h2>
        <p class="mgmt-subtitle">{{ $t('queue_ops.subtitle') }}</p>
      </div>
    </div>

    <WorkspaceQueueTab :workspaces="wsStore.workspaces" />
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
