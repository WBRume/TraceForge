<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import WorkspaceAssetsShell from '@/components/workspace-assets/WorkspaceAssetsShell.vue'

type WorkspaceAssetsSection = 'requirements' | 'tasks' | 'workload' | 'knowledgeBase'

const route = useRoute()

const section = computed<WorkspaceAssetsSection>(() => {
  switch (route.name) {
    case 'workspaceAssetsRequirements':
      return 'requirements'
    case 'workspaceAssetsTasks':
      return 'tasks'
    case 'workspaceAssetsWorkload':
      return 'workload'
    case 'workspaceAssetsKnowledgeBase':
      return 'knowledgeBase'
    default:
      return 'requirements'
  }
})
</script>

<template>
  <WorkspaceAssetsShell :section="section" />
</template>
