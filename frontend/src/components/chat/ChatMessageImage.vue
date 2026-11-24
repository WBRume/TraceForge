<script setup lang="ts">
import { shallowRef, watch } from 'vue'
import { readChatImage, type ChatImageReference } from '@/composables/chat/session/useChatImageDraft'

const props = defineProps<{ workspaceId: string; taskId: string; image: ChatImageReference }>()
const src = shallowRef('')
const failed = shallowRef(false)

watch([() => props.workspaceId, () => props.taskId, () => props.image.id], async ([workspaceId, taskId, imageId], _, onCleanup) => {
  const controller = new AbortController()
  src.value = ''
  failed.value = false
  let objectUrl = ''
  onCleanup(() => {
    controller.abort()
    if (objectUrl) URL.revokeObjectURL(objectUrl)
  })
  try {
    const data = await readChatImage(workspaceId, taskId, imageId, controller.signal)
    if (controller.signal.aborted) return
    objectUrl = URL.createObjectURL(data)
    src.value = objectUrl
  } catch {
    if (!controller.signal.aborted) failed.value = true
  }
}, { immediate: true })
</script>

<template>
  <a v-if="src" class="image-link" :href="src" target="_blank" rel="noopener" :title="image.filename">
    <img class="message-image" :src="src" :alt="image.filename" decoding="async" @error="failed = true; src = ''" />
  </a>
  <span v-else-if="failed" class="image-placeholder">{{ $t('chat.images.unavailable', { name: image.filename }) }}</span>
  <span v-else class="image-placeholder" role="status">{{ image.filename }}</span>
</template>

<style scoped>
.image-link {
  display: block;
  max-width: min(260px, 100%);
}
.message-image {
  display: block;
  max-width: 100%;
  max-height: 200px;
  border-radius: 8px;
  object-fit: contain;
}
.image-placeholder {
  font-size: 0.75rem;
  overflow-wrap: anywhere;
}
</style>
