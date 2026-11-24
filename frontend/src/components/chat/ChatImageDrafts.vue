<script setup lang="ts">
import { X } from '@/components/icons'
import type { ChatImageDraft } from '@/composables/chat/session/useChatImageDraft'

defineProps<{ items: readonly ChatImageDraft[]; disabled: boolean }>()
const emit = defineEmits<{ remove: [previewUrl: string] }>()
</script>

<template>
  <ul class="image-drafts" :aria-label="$t('chat.images.selected')">
    <li v-for="{ file, previewUrl } in items" :key="previewUrl" class="image-draft">
      <img class="image-preview" :src="previewUrl" :alt="file.name" :title="file.name" />
      <button
        type="button"
        class="remove-image"
        :aria-label="$t('chat.images.remove', { name: file.name })"
        :disabled="disabled"
        @click="emit('remove', previewUrl)"
      >
        <X :size="14" aria-hidden="true" />
      </button>
    </li>
  </ul>
</template>

<style scoped>
.image-drafts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0;
  padding: 8px 12px 0;
  list-style: none;
}
.image-draft {
  position: relative;
}
.image-preview {
  display: block;
  width: 64px;
  height: 64px;
  border-radius: 8px;
  background: var(--color-surface-overlay, #f1f5f9);
  object-fit: cover;
}
.remove-image {
  position: absolute;
  top: 3px;
  right: 3px;
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: rgba(15, 23, 42, 0.78);
  color: white;
  cursor: pointer;
}
.remove-image:disabled {
  opacity: 0.6;
  cursor: default;
}
</style>
