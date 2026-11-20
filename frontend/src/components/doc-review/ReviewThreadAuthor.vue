<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import UserAvatar from '@/components/user/UserAvatar.vue'
import { formatTime } from '@/utils/chatFormatters'
import { reviewerColor } from '@/utils/skillReview'
import type { AssetThread } from '@/composables/asset-discussion/types'

const props = defineProps<{
  thread: Pick<AssetThread, 'creator_id' | 'creator_display_name' | 'creator_avatar_svg' | 'creator_avatar_url' | 'created_at'>
}>()
const { t } = useI18n()
const name = computed(() => props.thread.creator_display_name?.trim() || t('doc_review.unknown_initiator'))
</script>

<template>
  <span class="review-thread-author">
    <UserAvatar
      :display-name="name"
      :user-id="thread.creator_id"
      :avatar-svg="thread.creator_avatar_svg"
      :avatar-url="thread.creator_avatar_url"
      :accent-color="reviewerColor(thread.creator_id)"
      size="sm"
      aria-hidden="true"
    />
    <span class="author-meta">
      <strong :title="name">{{ name }}</strong>
      <time v-if="thread.created_at" :datetime="thread.created_at">{{ formatTime(thread.created_at) }}</time>
    </span>
  </span>
</template>

<style scoped>
.review-thread-author {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  text-align: left;
}
.author-meta {
  display: grid;
  gap: 2px;
  min-width: 0;
}
.author-meta strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-title);
  font-size: 13px;
}
.author-meta time {
  color: var(--color-text-muted);
  font-size: 11px;
}
</style>
