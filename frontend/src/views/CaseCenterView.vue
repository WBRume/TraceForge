<script setup lang="ts">
import CaseCenterView from '@/components/case-center/CaseCenterView.vue'
import WorkspaceAssetsShell from '@/components/workspace-assets/WorkspaceAssetsShell.vue'
</script>

<template>
  <WorkspaceAssetsShell section="cases">
    <CaseCenterView embedded />
  </WorkspaceAssetsShell>
</template>
