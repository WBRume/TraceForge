<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import MemberWorkloadWorkbench from '@/components/workspace-assets/workload/MemberWorkloadWorkbench.vue'

const route = useRoute()
const workspaceId = computed(() => String(route.params.wsId || ''))
</script>

<template>
  <div class="workload-page">
    <MemberWorkloadWorkbench :workspace-id="workspaceId" />
  </div>
</template>

<style scoped>
.workload-page {
  padding: clamp(16px, 3vw, 32px);
}
</style>
