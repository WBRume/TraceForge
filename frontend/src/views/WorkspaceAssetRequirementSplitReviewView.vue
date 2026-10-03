<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import SplitReviewWorkbench from '@/components/workspace-assets/requirements/split-review/SplitReviewWorkbench.vue'
const route = useRoute()
const identity = computed(() => ({ wsId: String(route.params.wsId || ''), requirementId: String(route.params.requirementId || ''), batchId: String(route.params.batchId || '') }))
const identityKey = computed(() => JSON.stringify(identity.value))
</script>

<template>
  <SplitReviewWorkbench :key="identityKey" v-bind="identity" />
</template>
