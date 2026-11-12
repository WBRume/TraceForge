<script setup lang="ts">
import { shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import DiffViewer from '@/components/diff/DiffViewer.vue'

const props = defineProps<{ source: (signal?: AbortSignal) => Promise<ArrayBuffer> }>()
const { t } = useI18n()
const text = shallowRef('')
const loading = shallowRef(false)
const failed = shallowRef(false)
watch(() => props.source, async (load, _, cleanup) => {
  const request = new AbortController()
  cleanup(() => request.abort())
  text.value = ''
  loading.value = true
  failed.value = false
  try {
    const bytes = await load(request.signal)
    if (!request.signal.aborted) text.value = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
  } catch {
    if (!request.signal.aborted) failed.value = true
  } finally {
    if (!request.signal.aborted) loading.value = false
  }
}, { immediate: true })
</script>

<template>
  <div class="patch-preview custom-scrollbar">
    <p v-if="failed" role="alert">{{ t('file_preview.failed') }}</p>
    <DiffViewer v-else :diff-text="text" :loading="loading" />
  </div>
</template>

<style scoped>
.patch-preview { flex: 1; min-height: 0; overflow: auto; }
.patch-preview p { margin: 16px; color: #64748b; }
</style>
