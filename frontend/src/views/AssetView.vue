<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import WorkspaceAssetsShell from '@/components/workspace-assets/WorkspaceAssetsShell.vue'

type WorkspaceAssetsSection = 'requirements' | 'tasks' | 'traceability' | 'knowledgeBase'

const route = useRoute()

const section = computed<WorkspaceAssetsSection>(() => {
  switch (route.name) {
    case 'workspaceAssetsRequirements':
      return 'requirements'
    case 'workspaceAssetsTasks':
      return 'tasks'
    case 'workspaceAssetsTraceability':
      return 'traceability'
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
