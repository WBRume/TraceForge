<script setup lang="ts">
import { computed } from 'vue'
import PdfPreview from '@/components/file-preview/PdfPreview.vue'
import api from '@/utils/api'

const props = defineProps<{ wsId: string; assetId: string; versionId?: string | null }>()
const source = computed(() => {
  const { wsId, assetId, versionId } = props
  return async () => (await api.get<ArrayBuffer>(
    `/workspaces/${encodeURIComponent(wsId)}/assets/${encodeURIComponent(assetId)}/file`,
    { responseType: 'arraybuffer', params: versionId ? { version_id: versionId } : undefined },
  )).data
})
</script>

<template>
  <PdfPreview :source="source" />
</template>
