<script setup lang="ts">
import { computed, shallowRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import UserAvatar from '@/components/user/UserAvatar.vue'
import type { AssetThread } from '@/composables/asset-discussion/types'
import { formatTime } from '@/utils/chatFormatters'
import { reviewerColor } from '@/utils/skillReview'
import { groupByReviewAuthor, type ReviewAnnotationTarget } from './reviewAnnotationRanges'

const props = defineProps<{
  target: ReviewAnnotationTarget | null
  threads: AssetThread[]
  selectedThreadId: string
}>()
const emit = defineEmits<{ close: []; 'open-thread': [threadId: string] }>()
const { t } = useI18n()
const panel = useTemplateRef<HTMLElement>('panel')
const authorId = shallowRef('')
const position = shallowRef({ left: '12px', top: '12px' })
const reviewers = computed(() => {
  const ids = new Set(props.target?.threadIds)
  return groupByReviewAuthor(props.threads.filter(thread => ids.has(thread.id))).map(threads => {
    const first = threads[0]!
    return {
      id: first.creator_id,
      name: first.creator_display_name?.trim() || t('doc_review.unknown_initiator'),
      avatarSvg: first.creator_avatar_svg,
      avatarUrl: first.creator_avatar_url,
      threads,
    }
  })
})
const activeReviewer = computed(() => reviewers.value.find(reviewer => reviewer.id === authorId.value) ?? reviewers.value[0])
const countLabel = computed(() => t(props.target?.multipleAnchors ? 'doc_review.line_thread_count' : 'doc_review.anchor_thread_count', {
  count: props.target?.threadIds.length || 0,
}))

watch(() => props.target, () => { authorId.value = '' })
watch([() => props.target, panel], ([target, element], _, cleanup) => {
  if (!target || !element) return
  const place = () => {
    const { width, height } = element.getBoundingClientRect()
    const left = `${Math.max(12, Math.min(target.left, window.innerWidth - width - 12))}px`
    const top = `${Math.max(12, Math.min(target.top, window.innerHeight - height - 12))}px`
    if (left !== position.value.left || top !== position.value.top) position.value = { left, top }
  }
  const dismissOutside = (event: Event) => {
    const node = event.target as Node | null
    if (node && (element.contains(node) || target.trigger?.contains(node))) return
    emit('close')
  }
  const events = new AbortController()
  const frameDocument = target.frame?.contentDocument
  for (const document of [window.document, frameDocument]) {
    document?.addEventListener('pointerdown', dismissOutside, { capture: true, signal: events.signal })
    document?.addEventListener('scroll', dismissOutside, { capture: true, passive: true, signal: events.signal })
  }
  window.addEventListener('resize', place, { signal: events.signal })
  const resize = new ResizeObserver(place)
  resize.observe(element)
  place()
  element.focus({ preventScroll: true })
  cleanup(() => {
    resize.disconnect()
    events.abort()
  })
}, { flush: 'post' })

function dismiss() {
  props.target?.trigger?.focus({ preventScroll: true })
  emit('close')
}

function quote(thread: AssetThread) {
  return thread.effective_anchor?.selected_text || thread.selected_text
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="target"
      ref="panel"
      class="review-popover glass-panel document-review-popover"
      :style="position"
      role="dialog"
      :aria-label="countLabel"
      tabindex="-1"
      @keydown.esc.stop.prevent="dismiss"
    >
      <div class="review-popover-head">
        <div class="review-popover-author">
          <UserAvatar
            v-if="activeReviewer"
            :display-name="activeReviewer.name"
            :avatar-svg="activeReviewer.avatarSvg"
            :avatar-url="activeReviewer.avatarUrl"
            :accent-color="reviewerColor(activeReviewer.id)"
            size="sm"
            aria-hidden="true"
          />
          <div class="author-info">
            <strong v-if="activeReviewer">{{ activeReviewer.name }}</strong>
            <span>{{ countLabel }}</span>
            <span v-if="reviewers.length > 1 && activeReviewer === reviewers[0]"> · {{ t('doc_review.earliest_initiator') }}</span>
          </div>
        </div>
        <button type="button" class="review-popover-close" :aria-label="t('common.close')" @click="dismiss">×</button>
      </div>

      <div v-if="reviewers.length > 1" class="review-popover-reviewers scrollbar-hide" role="group"
        :aria-label="t('doc_review.anchor_thread_order')">
        <button
          v-for="reviewer in reviewers"
          :key="reviewer.id"
          type="button"
          class="reviewer-switch-btn"
          :class="{ active: reviewer === activeReviewer }"
          :aria-label="reviewer.name"
          :aria-pressed="reviewer === activeReviewer"
          :title="reviewer.name"
          @click="authorId = reviewer.id"
        >
          <UserAvatar
            :display-name="reviewer.name"
            :avatar-svg="reviewer.avatarSvg"
            :avatar-url="reviewer.avatarUrl"
            :accent-color="reviewerColor(reviewer.id)"
            size="xs"
            aria-hidden="true"
          />
        </button>
      </div>

      <div v-if="activeReviewer" class="review-popover-list custom-scrollbar">
        <button
          v-for="thread in activeReviewer.threads"
          :key="thread.id"
          type="button"
          class="review-popover-item"
          :class="{ active: thread.id === selectedThreadId }"
          @click="emit('open-thread', thread.id)"
        >
          <p>{{ thread.messages[0]?.content || quote(thread) || t('doc_review.no_selected_text') }}</p>
          <span v-if="thread.messages[0]?.content && quote(thread)" class="thread-quote">{{ quote(thread) }}</span>
          <span class="thread-item-meta">
            <time class="comment-date" :datetime="thread.created_at">{{ formatTime(thread.created_at) }}</time>
            <span :class="{ 'status-open': thread.status === 'open' }">{{ t(`doc_review.thread_status_${thread.status}`) }}</span>
          </span>
        </button>
      </div>
      <span v-else class="comment-date" role="status">{{ t('common.loading') }}</span>
    </div>
  </Teleport>
</template>

<style scoped src="@/styles/review-annotations.css"></style>
<style scoped>
.document-review-popover {
  position: fixed;
  width: min(340px, calc(100vw - 24px));
  max-height: calc(100dvh - 24px);
}
.document-review-popover:focus { outline: none; }
.review-popover-close {
  flex: none;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: #64748b;
  width: 1.4rem;
  height: 1.4rem;
  padding: 0;
  font: 1.2rem/1 system-ui, sans-serif;
  cursor: pointer;
}
.review-popover-close:hover { background: #f1f5f9; color: #334155; }
.review-popover-item { text-align: start; }
.review-popover-item p, .thread-quote {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  overflow: hidden;
  overflow-wrap: anywhere;
}
.thread-quote {
  margin-top: 0.25rem;
  font-size: 0.75rem;
  color: #475569;
  -webkit-line-clamp: 1;
}
.thread-item-meta {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem;
  color: #64748b;
  font-size: 0.75rem;
}
.thread-item-meta .status-open { color: #0369a1; }
</style>
